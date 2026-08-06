from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

import requests


class RetrievalError(RuntimeError):
    pass


@dataclass(frozen=True)
class RetrievalScope:
    user_id: str
    knowledgebase_ids: tuple[str, ...]
    active_version_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.user_id:
            raise RetrievalError("authenticated_user_required")
        if not self.knowledgebase_ids:
            raise RetrievalError("no_readable_knowledgebases")
        if not self.active_version_ids:
            raise RetrievalError("no_active_readable_versions")


@dataclass(frozen=True)
class RetrievedChunk:
    point_id: str
    document_id: str
    version_id: str
    title: str
    content: str
    parent_content: str
    heading_path: tuple[str, ...]
    knowledgebase_ids: tuple[str, ...]
    source_id: str
    source_url: str
    valid_until: str
    authority: str
    conflict: bool
    retrieval_score: float
    rerank_score: float


class SparseQueryEncoder(Protocol):
    def encode_query(self, query: str) -> dict[str, list[int] | list[float]]: ...


class Reranker(Protocol):
    def rerank(self, query: str, documents: list[str], top_n: int) -> list[tuple[int, float]]: ...


def mandatory_acl_filter(scope: RetrievalScope, today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    return {
        "must": [
            {"key": "knowledgebase_ids", "match": {"any": list(scope.knowledgebase_ids)}},
            {"key": "version_id", "match": {"any": list(scope.active_version_ids)}},
            {"key": "status", "match": {"value": "active"}},
            {"key": "published", "match": {"value": True}},
            {"key": "valid_from", "range": {"lte": today.isoformat()}},
            {"key": "valid_until", "range": {"gte": today.isoformat()}},
        ]
    }


def reciprocal_rank_fusion(rankings: list[list[str]], k: int = 60) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, identifier in enumerate(ranking, start=1):
            scores[identifier] = scores.get(identifier, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


class PortalScopeClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 10):
        self.base_url, self.api_key, self.timeout = base_url.rstrip("/"), api_key, timeout

    def resolve(self, user_id: str) -> RetrievalScope:
        if not user_id or not self.api_key:
            raise RetrievalError("retrieval_scope_credentials_missing")
        try:
            response = requests.post(
                f"{self.base_url}/portal/internal/retrieval-scope",
                headers={"X-API-Key": self.api_key}, json={"user_id": user_id}, timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            return RetrievalScope(payload["user_id"], tuple(payload["knowledgebase_ids"]), tuple(payload["active_version_ids"]))
        except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
            raise RetrievalError("retrieval_scope_unavailable") from exc


class IonosReranker:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 60):
        self.base_url, self.api_key, self.model, self.timeout = base_url.rstrip("/"), api_key, model, timeout

    def rerank(self, query: str, documents: list[str], top_n: int) -> list[tuple[int, float]]:
        if not self.model or not self.api_key:
            raise RetrievalError("reranker_not_configured")
        try:
            response = requests.post(
                f"{self.base_url}/rerank",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={"model": self.model, "query": query, "documents": documents, "top_n": top_n},
                timeout=self.timeout,
            )
            response.raise_for_status()
            rows = response.json()["results"]
            return [(int(row["index"]), float(row["relevance_score"])) for row in rows]
        except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
            raise RetrievalError("reranker_unavailable") from exc


class QdrantHybridRetriever:
    def __init__(self, qdrant_url: str, collection_alias: str, sparse_encoder: SparseQueryEncoder,
                 reranker: Reranker, timeout: float = 30):
        self.qdrant_url, self.alias = qdrant_url.rstrip("/"), collection_alias
        self.sparse_encoder, self.reranker, self.timeout = sparse_encoder, reranker, timeout

    def retrieve(self, query: str, dense_vector: list[float], scope: RetrievalScope,
                 *, candidate_limit: int = 50, result_limit: int = 8,
                 today: date | None = None) -> list[RetrievedChunk]:
        if not query.strip() or not dense_vector:
            raise RetrievalError("query_and_dense_vector_required")
        if not 30 <= candidate_limit <= 50 or not 5 <= result_limit <= 8:
            raise RetrievalError("retrieval_limits_out_of_policy")
        acl = mandatory_acl_filter(scope, today)
        sparse = self.sparse_encoder.encode_query(query)
        build_id = str(sparse.pop("build_id", ""))
        if not build_id:
            raise RetrievalError("sparse_build_id_missing")
        acl["must"].append({"key": "build_id", "match": {"value": build_id}})
        body = {
            "prefetch": [
                {"query": dense_vector, "using": "dense", "filter": acl, "limit": candidate_limit},
                {"query": sparse, "using": "bm25", "filter": acl, "limit": candidate_limit},
            ],
            "query": {"fusion": "rrf"},
            "limit": candidate_limit,
            "with_payload": True,
        }
        try:
            response = requests.post(
                f"{self.qdrant_url}/collections/{self.alias}/points/query",
                json=body, timeout=self.timeout,
            )
            response.raise_for_status()
            points = response.json()["result"]["points"]
        except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
            raise RetrievalError("hybrid_search_unavailable") from exc
        candidates = self._document_centered(points, candidate_limit)
        reranked = self.reranker.rerank(query, [item["payload"]["content"] for item in candidates], result_limit)
        selected: list[RetrievedChunk] = []
        for index, score in reranked[:result_limit]:
            if index < 0 or index >= len(candidates):
                raise RetrievalError("reranker_response_invalid")
            point = candidates[index]
            payload = point["payload"]
            # Defense in depth: never trust an index response that violates the sent hard filter.
            if not set(payload.get("knowledgebase_ids") or ()).intersection(scope.knowledgebase_ids):
                raise RetrievalError("acl_violation_in_search_response")
            if str(payload.get("version_id") or "") not in scope.active_version_ids:
                raise RetrievalError("non_authoritative_version_returned")
            if payload.get("status") != "active" or payload.get("published") is not True:
                raise RetrievalError("inactive_result_returned")
            selected.append(RetrievedChunk(
                point_id=str(point["id"]), document_id=payload["document_id"], version_id=payload["version_id"],
                title=payload["title"], content=payload["content"], parent_content=payload.get("parent_content") or payload["content"],
                heading_path=tuple(payload.get("heading_path") or ()), knowledgebase_ids=tuple(payload["knowledgebase_ids"]),
                source_id=payload["source_id"], source_url=payload["source_url"], valid_until=payload["valid_until"],
                authority=payload.get("authority") or "", conflict=bool(payload.get("conflict")),
                retrieval_score=float(point.get("score") or 0), rerank_score=float(score),
            ))
        return selected

    @staticmethod
    def _document_centered(points: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        result, per_document = [], {}
        for point in points:
            payload = point.get("payload") or {}
            document_id = str(payload.get("document_id") or "")
            if not document_id:
                continue
            count = per_document.get(document_id, 0)
            if count >= 2:
                continue
            per_document[document_id] = count + 1
            result.append(point)
            if len(result) >= limit:
                break
        return result
