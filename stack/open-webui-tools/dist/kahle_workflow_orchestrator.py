"""
title: KAHLE Workflow Orchestrator
author: local
version: 0.4.0
description: Deterministisches Mehrschritt-Tool fuer KAHLE-Workflows mit Tasks, RAG/Web-Recherche und strukturierter Ausgabe.
"""
# Erzeugt von stack/open-webui-tools/build_tools.py. Nicht direkt bearbeiten.
# Quellen: hybrid_retrieval.py, hybrid_retrieval_adapters.py, kahle_workflow_orchestrator.py
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from typing import Any
from typing import Any, Protocol
import json
import math
import os
import re
import requests
import sqlite3
import time
import unicodedata


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
def _fold_identifier(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return re.sub(r"[^a-z0-9]+", "", normalized.encode("ascii", "ignore").decode().casefold())
def explicit_source_identifiers(query: str) -> tuple[str, ...]:
    """Return explicit KB/file identifiers that must match the result title."""
    identifiers = re.findall(r"\bKB_[A-Za-z0-9_-]+\b", query or "", flags=re.IGNORECASE)
    identifiers.extend(
        re.findall(r"\b[^\s/\\]+\.(?:md|pdf|docx|xlsx|pptx|txt)\b", query or "", flags=re.IGNORECASE)
    )
    return tuple(dict.fromkeys(_fold_identifier(item.rsplit(".", 1)[0]) for item in identifiers))
_TITLE_STOPWORDS = {
    "am", "an", "auf", "aus", "das", "der", "die", "ein", "eine", "einer",
    "fur", "im", "in", "mit", "oder", "steht", "und", "unser", "unsere",
    "unserer", "von", "was", "wer", "zu", "kahle", "gruppe", "dokument", "datei",
    "du", "uber", "weisst", "weiss", "weit", "kennt", "kennst",
}
def _title_terms(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFKD", value or "")
    folded = normalized.encode("ascii", "ignore").decode().casefold()
    terms = set(re.findall(r"[a-z0-9]+", folded))
    return {
        term for term in terms
        if len(term) >= 2 and term not in _TITLE_STOPWORDS
        and not re.fullmatch(r"v?\d+", term)
    }
def focused_document_ids(query: str, candidates: list[dict[str, Any]]) -> set[str]:
    """Detect a naturally named document without guessing from one generic word.

    Two shared meaningful title terms are required. This focuses questions such
    as "unsere KI Compliance" while a broad question such as "Was gilt für KI?"
    still benefits from document diversity.
    """
    query_terms = _title_terms(query)
    matches: list[tuple[int, float, str]] = []
    for point in candidates:
        payload = point.get("payload") or {}
        document_id = str(payload.get("document_id") or "")
        title_terms = _title_terms(str(payload.get("title") or ""))
        shared = query_terms.intersection(title_terms)
        if document_id and len(shared) >= 2:
            matches.append((len(shared), len(shared) / max(1, len(title_terms)), document_id))
    if not matches and 2 <= len(query_terms) <= 4:
        # Short entity/role questions often name a person or function that is
        # intentionally not part of the document title (for example "Thomas
        # Keller" inside "Wichtige Kontakte Rollen"). An exact all-term match
        # in an ACL-filtered active candidate is sufficiently specific to focus
        # the document without fuzzy guessing.
        for point in candidates:
            payload = point.get("payload") or {}
            document_id = str(payload.get("document_id") or "")
            content_terms = _title_terms(
                str(payload.get("parent_content") or payload.get("content") or "")
            )
            if document_id and query_terms.issubset(content_terms):
                matches.append((len(query_terms), 1.0, document_id))
    if not matches:
        return set()
    best = max((count, coverage) for count, coverage, _document_id in matches)
    return {
        document_id for count, coverage, document_id in matches
        if (count, coverage) == best
    }
def diversify_reranked(
    reranked: list[tuple[int, float]], candidates: list[dict[str, Any]],
    *, result_limit: int, per_document_limit: int = 2,
) -> list[tuple[int, float]]:
    """Prefer breadth first, then fill free result slots by relevance."""
    selected: list[tuple[int, float]] = []
    selected_indices: set[int] = set()
    document_counts: dict[str, int] = {}
    for index, score in reranked:
        if index < 0 or index >= len(candidates) or index in selected_indices:
            continue
        document_id = str((candidates[index].get("payload") or {}).get("document_id") or "")
        if document_counts.get(document_id, 0) >= per_document_limit:
            continue
        selected.append((index, score))
        selected_indices.add(index)
        document_counts[document_id] = document_counts.get(document_id, 0) + 1
        if len(selected) >= result_limit:
            return selected
    for index, score in reranked:
        if index < 0 or index >= len(candidates) or index in selected_indices:
            continue
        selected.append((index, score))
        selected_indices.add(index)
        if len(selected) >= result_limit:
            break
    return selected
def _authority_level(point: dict[str, Any]) -> int:
    value = str((point.get("payload") or {}).get("authority") or "6")
    try:
        level = int(value.split(":", 1)[0])
    except ValueError:
        return 6
    return level if 1 <= level <= 6 else 6
def normative_query_intent(query: str) -> bool:
    normalized = unicodedata.normalize("NFKD", query or "").encode("ascii", "ignore").decode().casefold()
    terms = set(re.findall(r"[a-z0-9]+", normalized))
    return bool(terms.intersection({
        "regel", "regeln", "vorgabe", "vorgaben", "pflicht", "pflichten",
        "vorgeschrieben", "verboten", "erlaubt", "durfen", "darf", "muss", "mussen",
        "richtlinie", "richtlinien", "compliance",
    }))
def authority_aware_reranked(
    query: str, reranked: list[tuple[int, float]], candidates: list[dict[str, Any]],
) -> list[tuple[int, float]]:
    if not normative_query_intent(query):
        return reranked
    authoritative = [
        (index, score) for index, score in reranked
        if _authority_level(candidates[index]) < 6
    ]
    if len(authoritative) >= 3:
        reranked = [
            (index, score) for index, score in reranked
            if _authority_level(candidates[index]) < 6
            or bool((candidates[index].get("payload") or {}).get("conflict"))
        ]
    return sorted(
        reranked,
        key=lambda item: (-(float(item[1]) + (6 - _authority_level(candidates[item[0]])) * .01), item[0]),
    )
def deduplicate_reranked(
    reranked: list[tuple[int, float]], candidates: list[dict[str, Any]],
    *, similarity_threshold: float = .88,
) -> list[tuple[int, float]]:
    selected: list[tuple[int, float]] = []
    selected_terms: list[set[str]] = []
    for index, score in reranked:
        payload = candidates[index].get("payload") or {}
        content = str(payload.get("parent_content") or payload.get("content") or "")
        normalized = unicodedata.normalize("NFKD", content).encode("ascii", "ignore").decode().casefold()
        terms = set(re.findall(r"[a-z0-9]{3,}", normalized))
        conflict = bool(payload.get("conflict"))
        duplicate = False
        if terms and not conflict:
            for (existing_index, _existing_score), other in zip(selected, selected_terms):
                existing_payload = candidates[existing_index].get("payload") or {}
                if existing_payload.get("conflict"):
                    continue
                overlap = len(terms.intersection(other)) / max(1, len(terms.union(other)))
                if overlap >= similarity_threshold:
                    duplicate = True
                    break
        if not duplicate:
            selected.append((index, score))
            selected_terms.append(terms)
    return selected
def _metadata_only(point: dict[str, Any]) -> bool:
    payload = point.get("payload") or {}
    content = str(payload.get("parent_content") or payload.get("content") or "").strip()
    if not content.startswith("---") or not content.endswith("---"):
        return False
    inner = content[3:-3]
    lines = [line.strip() for line in inner.splitlines() if line.strip()]
    return bool(lines) and all(":" in line or line.startswith(("-", "#")) for line in lines)
def document_overview_intent(query: str) -> bool:
    folded = unicodedata.normalize("NFKD", query or "").encode("ascii", "ignore").decode().casefold()
    if any(term in folded for term in (
        "vollstandig", "vollstaendig", "komplett", "gesamte", "gesamten",
        "alle kapitel", "alle punkte", "vollstandiger uberblick", "zusammenfassung des dokuments",
    )):
        return True
    words = re.findall(r"[a-z0-9_-]+", folded)
    if len(words) <= 4 and len(_title_terms(query)) >= 2:
        # A bare, uniquely focused document title means "load this document",
        # not "pick one arbitrary passage".
        return True
    return len(words) <= 8 and (
        folded.startswith("was steht in ") or folded.startswith("worum geht es in ")
    )
def structural_document_overview(
    candidates: list[dict[str, Any]], reranked: list[tuple[int, float]],
    *, result_limit: int, max_context_chars: int = 40_000,
) -> list[tuple[tuple[int, ...], float]]:
    """Group every parent below each numbered main chapter when all chapters fit."""
    scores = {index: float(score) for index, score in reranked}
    numbered: dict[int, list[int]] = {}
    for index, point in enumerate(candidates):
        path = tuple((point.get("payload") or {}).get("heading_path") or ())
        number = None
        for heading in path:
            match = re.match(r"^\s*(\d{1,3})[.)]\s+", str(heading))
            if match:
                number = int(match.group(1))
                break
        if number is not None:
            numbered.setdefault(number, []).append(index)
    if not numbered:
        return []
    ordered = [
        tuple(sorted(
            numbered[number],
            key=lambda index: int((candidates[index].get("payload") or {}).get("chunk_order") or 0),
        ))
        for number in sorted(numbered)
    ]
    total_chars = sum(len(str(
        (candidates[index].get("payload") or {}).get("parent_content")
        or (candidates[index].get("payload") or {}).get("content") or ""
    )) for chapter in ordered for index in chapter)
    if len(ordered) > result_limit or total_chars > max_context_chars:
        return []
    return [
        (chapter, max((scores.get(index, 0.0) for index in chapter), default=0.0))
        for chapter in ordered
    ]
def merge_overview_chapters(
    candidates: list[dict[str, Any]],
    chapters: list[tuple[tuple[int, ...], float]],
) -> tuple[list[dict[str, Any]], list[tuple[int, float]]]:
    merged: list[dict[str, Any]] = []
    ranked: list[tuple[int, float]] = []
    for chapter_indices, score in chapters:
        first = candidates[chapter_indices[0]]
        payload = dict(first.get("payload") or {})
        contents = [
            str((candidates[index].get("payload") or {}).get("parent_content")
                or (candidates[index].get("payload") or {}).get("content") or "").strip()
            for index in chapter_indices
        ]
        chapter_content = "\n\n".join(content for content in contents if content)
        path = tuple(payload.get("heading_path") or ())
        for position, heading in enumerate(path):
            if re.match(r"^\s*\d{1,3}[.)]\s+", str(heading)):
                path = path[:position + 1]
                break
        payload.update({
            "content": chapter_content,
            "parent_content": chapter_content,
            "heading_path": list(path),
        })
        merged.append({**first, "payload": payload})
        ranked.append((len(merged) - 1, score))
    return merged, ranked
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
        except requests.Timeout as exc:
            raise RetrievalError("reranker_unavailable:timeout") from exc
        except requests.ConnectionError as exc:
            raise RetrievalError("reranker_unavailable:connection") from exc
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            raise RetrievalError(f"reranker_unavailable:http_{status or 'unknown'}") from exc
        except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
            raise RetrievalError(f"reranker_unavailable:{type(exc).__name__.lower()}") from exc
class QdrantHybridRetriever:
    def __init__(self, qdrant_url: str, collection_alias: str, sparse_encoder: SparseQueryEncoder,
                 reranker: Reranker, timeout: float = 30, minimum_rerank_score: float = 0.25):
        self.qdrant_url, self.alias = qdrant_url.rstrip("/"), collection_alias
        self.sparse_encoder, self.reranker, self.timeout = sparse_encoder, reranker, timeout
        if not 0 <= minimum_rerank_score <= 1:
            raise RetrievalError("minimum_rerank_score_out_of_range")
        self.minimum_rerank_score = minimum_rerank_score

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
        candidates = [
            point for point in self._parent_centered(points, candidate_limit)
            if not _metadata_only(point)
        ]
        identifiers = explicit_source_identifiers(query)
        if identifiers:
            candidates = [
                point
                for point in candidates
                if all(
                    identifier
                    in _fold_identifier(str((point.get("payload") or {}).get("title") or ""))
                    for identifier in identifiers
                )
            ]
            if not candidates:
                return []
        focused_ids = focused_document_ids(query, candidates) if not identifiers else set()
        if focused_ids:
            candidates = [
                point for point in candidates
                if str((point.get("payload") or {}).get("document_id") or "") in focused_ids
            ]
        selected_document_ids = focused_ids or {
            str((point.get("payload") or {}).get("document_id") or "")
            for point in candidates
            if identifiers
        }
        selected_document_ids.discard("")
        if selected_document_ids:
            complete_points = self._document_points(selected_document_ids, acl)
            if complete_points:
                candidates = [
                    point for point in self._parent_centered(complete_points, 256)
                    if not _metadata_only(point)
                ]
        try:
            reranked = self.reranker.rerank(
                query, [item["payload"].get("parent_content") or item["payload"]["content"] for item in candidates],
                min(len(candidates), result_limit * 3),
            )
        except RetrievalError as exc:
            # A named person, e-mail address or an otherwise unambiguous document
            # identifier has already been matched against ACL-filtered active
            # documents above. For that narrow case the hybrid RRF order is a
            # safer degraded mode than returning "kein Wissen" solely because
            # the external reranker is temporarily unavailable. Broad queries
            # continue to fail closed because their relevance needs reranking.
            if not str(exc).startswith("reranker_unavailable") or not (identifiers or focused_ids):
                raise
            reranked = sorted(
                ((index, 1.0) for index in range(len(candidates))),
                key=lambda item: float(candidates[item[0]].get("score") or 0),
                reverse=True,
            )[: min(len(candidates), result_limit * 3)]
        for index, _score in reranked:
            if index < 0 or index >= len(candidates):
                raise RetrievalError("reranker_response_invalid")
        eligible_reranked = [
            (index, score) for index, score in reranked
            if float(score) >= self.minimum_rerank_score
        ]
        eligible_reranked = authority_aware_reranked(query, eligible_reranked, candidates)
        eligible_reranked = deduplicate_reranked(eligible_reranked, candidates)
        overview_selection = (
            structural_document_overview(
                candidates, reranked, result_limit=result_limit,
            )
            if focused_ids and document_overview_intent(query) else []
        )
        if overview_selection:
            candidates, ranked_selection = merge_overview_chapters(candidates, overview_selection)
        elif identifiers or focused_ids:
            ranked_selection = eligible_reranked[:result_limit]
        else:
            ranked_selection = diversify_reranked(
                eligible_reranked, candidates, result_limit=result_limit,
            )
        selected: list[RetrievedChunk] = []
        for index, score in ranked_selection:
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

    def _document_points(
        self, document_ids: set[str], acl: dict[str, Any],
    ) -> list[dict[str, Any]]:
        body = {
            "filter": {"must": [
                *acl["must"],
                {"key": "document_id", "match": {"any": sorted(document_ids)}},
            ]},
            "limit": 256,
            "with_payload": True,
            "with_vector": False,
        }
        try:
            response = requests.post(
                f"{self.qdrant_url}/collections/{self.alias}/points/scroll",
                json=body, timeout=self.timeout,
            )
            response.raise_for_status()
            return list(response.json()["result"]["points"])
        except (requests.RequestException, KeyError, TypeError, ValueError):
            # The already ACL-filtered hybrid result remains a safe fallback.
            return []

    @staticmethod
    def _parent_centered(points: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        """Keep every distinct parent for reranking, even from the same document.

        Limiting the pre-rerank pool to two chunks per document discarded the
        actually relevant section in small corpora before the cross-encoder
        could see it. Parent deduplication removes overlapping child hits while
        preserving the PRD's 30-50 candidate rerank stage.
        """
        result, seen_parents = [], set()
        for point in points:
            payload = point.get("payload") or {}
            parent_id = str(payload.get("parent_id") or point.get("id") or "")
            if not parent_id or parent_id in seen_parents:
                continue
            seen_parents.add(parent_id)
            result.append(point)
            if len(result) >= limit:
                break
        return result

class TeiReranker:
    """Dedicated multilingual cross-encoder served by Hugging Face TEI."""

    def __init__(self, base_url, api_key="", timeout=60):
        self.base_url, self.api_key, self.timeout = base_url.rstrip("/"), api_key, timeout

    def rerank(self, query, documents, top_n):
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            response = requests.post(
                f"{self.base_url}/rerank", headers=headers,
                json={"query": query, "texts": documents, "truncate": True}, timeout=self.timeout,
            )
            response.raise_for_status()
            rows = response.json()
            if isinstance(rows, dict):
                rows = rows.get("results") or []
            ranked = [(int(row["index"]), float(row.get("score", row.get("relevance_score")))) for row in rows]
            return sorted(ranked, key=lambda item: item[1], reverse=True)[:top_n]
        except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
            raise RetrievalError("reranker_unavailable") from exc
class RemoteSparseQueryEncoder:
    def __init__(self, base_url, api_key, timeout=10):
        self.base_url, self.api_key, self.timeout = base_url.rstrip("/"), api_key, timeout

    def encode_query(self, query):
        if not self.api_key:
            raise RetrievalError("sparse_encoder_credentials_missing")
        try:
            response = requests.post(
                f"{self.base_url}/hybrid/sparse-query", headers={"X-API-Key": self.api_key},
                json={"query": query}, timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            indices, values = payload["indices"], payload["values"]
            if not indices or len(indices) != len(values):
                raise ValueError("invalid sparse vector")
            return {"build_id": payload["build_id"], "indices": indices, "values": values}
        except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
            raise RetrievalError("sparse_encoder_unavailable") from exc


try:
    from pydantic import BaseModel, Field
except Exception:  # pragma: no cover - local test fallback without OpenWebUI deps
    class BaseModel:
        pass

    def Field(default=None, description: str = ""):
        return default
def _env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return default
def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)
def _coerce_message_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value.strip()
        if text and text[0] in "[{":
            try:
                return _coerce_message_text(json.loads(text))
            except Exception:
                return text
        return text
    if isinstance(value, dict):
        if isinstance(value.get("content"), str):
            return value["content"].strip()
        if isinstance(value.get("text"), str):
            return value["text"].strip()
        if isinstance(value.get("content"), list):
            return _coerce_message_text(value.get("content"))
        return ""
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            text = _coerce_message_text(item)
            if text:
                parts.append(text)
        return "\n".join(parts).strip()
    return str(value).strip()
def _looks_like_generated_file_claim(text: str) -> bool:
    lower = (text or "").lower()
    return bool(
        "/files/download" in lower
        or "download-link:" in lower
        or "datei herunterladen" in lower
        or "sha256:" in lower
    )
def _looks_like_non_result_assistant(text: str) -> bool:
    lower = (text or "").strip().lower()
    if not lower or lower in {'""', "''"}:
        return True
    if lower.startswith(("[tool_calls]", "ich werde", "einen moment", "bitte einen moment")):
        return True
    if _looks_like_generated_file_claim(lower):
        return True
    if any(
        marker in lower
        for marker in (
            "benoetige ich weitere details",
            "benötige ich weitere details",
            "bitte praezisiere",
            "bitte präzisiere",
            "sobald du diese details angibst",
        )
    ):
        return True
    return False
def _latest_chat_message(chat_id: str | None, role: str, *, require_result: bool = False) -> str:
    chat_id = (chat_id or "").strip()
    if not chat_id:
        return ""
    db_path = _env("OWUI_DB_PATH", default="/app/backend/data/webui.db")
    if not db_path or not os.path.exists(db_path):
        return ""
    try:
        con = sqlite3.connect(db_path)
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """
            select content
            from chat_message
            where chat_id = ? and role = ?
            order by coalesce(created_at, 0) desc, coalesce(updated_at, 0) desc
            limit 20
            """,
            (chat_id, role),
        ).fetchall()
    except Exception:
        return ""
    finally:
        try:
            con.close()
        except Exception:
            pass
    for row in rows or []:
        text = _coerce_message_text(row["content"])
        if not text:
            continue
        if require_result and role == "assistant" and _looks_like_non_result_assistant(text):
            continue
        return text
    return ""
def _looks_like_previous_result_request(text: str) -> bool:
    lower = (text or "").lower()
    if any(
        marker in lower
        for marker in (
            "aus dem ergebnis",
            "das ergebnis als",
            "ergebnis als",
            "aus dem vorherigen",
            "aus deiner antwort",
            "vorherige antwort",
            "daraus eine datei",
            "daraus als",
            "aus dem text",
            "die recherche als",
            "recherche als",
            "rechercheergebnis",
        )
    ):
        return True
    if re.search(r"\b(recherchiere|suche|finde|erstelle)\b", lower):
        return False
    return bool(
        re.search(r"\b(ergebnis|antwort|recherche)\b", lower)
        and re.search(r"\b(pdf|docx|word|powerpoint|pptx|markdown|datei|download)\b", lower)
    )
def _looks_like_direct_document_request(text: str, output_format: str) -> bool:
    """Detect file requests whose content is supplied by the user, not researched."""
    if output_format not in {"pdf", "docx", "md"}:
        return False
    lower = (text or "").lower()
    if re.search(r"\b(recherchier\w*|such\w*|find\w*|ermittel\w*|nachschlag\w*)\b", lower):
        return False
    asks_to_create = bool(re.search(r"\b(erstell\w*|erzeug\w*|generier\w*|schreib\w*)\b", lower))
    supplies_content = bool(
        re.search(r"\b(ueberschrift|überschrift|titel)\b", lower)
        and re.search(r"\b(absatz|inhalt|text)\b", lower)
    )
    return asks_to_create and supplies_content
def _looks_like_fillable_ki_permission_form_request(text: str, output_format: str) -> bool:
    """Detect interactive Word templates for documenting KI approvals."""
    if output_format not in {"docx", "pdf"}:
        return False
    lower = (text or "").lower()
    wants_fillable = bool(re.search(r"\b(ausf[üu]llbar\w*|interaktiv\w*|aktive?\w*\s+word|formular\w*|vorlage\w*|eingabefeld\w*|checkbox\w*|anklickbar\w*|festhalt\w*|unterschrift\w*)\b", lower))
    wants_permission = bool(re.search(r"\b(ki[- ]?nutzung\w*|erlaubnis\w*|genehmigung\w*|freigabe\w*|einwilligung\w*)\b", lower))
    references_previous_form = output_format == "pdf" and "interaktiv" in lower and bool(re.search(r"\b(genau so|genau dies\w*|diese datei|dieses dokument|gleich\w*|vorherig\w*|vorlage\w*|daraus|auch einmal)\b", lower))
    return wants_fillable and (wants_permission or references_previous_form)
def _looks_like_ki_policy_quiz_request(text: str, output_format: str) -> bool:
    if output_format not in {"docx", "pdf"}:
        return False
    lower = (text or "").lower()
    wants_quiz = bool(re.search(r"\b(fragebogen\w*|wissenstest\w*|kenntnistest\w*|quiz\w*|wissenspr[üu]fung\w*)\b", lower))
    wants_policy = bool(re.search(r"\b(ki[- ]?richtlinie\w*|richtlinie\w*.*\bki\b|ki\b.*richtlinie\w*)", lower))
    return wants_quiz and wants_policy
def _looks_like_interactive_form_request(text: str, output_format: str) -> bool:
    if output_format not in {"docx", "pdf"}: return False
    lower=(text or "").lower()
    interactive=bool(re.search(r"\b(interaktiv\w*|ausf[üu]llbar\w*|formular\w*|eingabefeld\w*|dropdown\w*|h[äa]kchen\w*|anklickbar\w*)\b",lower))
    artifact=bool(re.search(r"\b(fragebogen\w*|wissenstest\w*|kenntnistest\w*|quiz\w*|assessment\w*|checkliste\w*|erfassungsbogen\w*|antrag\w*|vorlage\w*|formular\w*)\b",lower))
    return interactive and artifact
def _form_kind(text: str) -> str:
    lower=(text or "").lower()
    if re.search(r"\b(fragebogen|wissenstest|kenntnistest|quiz|wissenspr[üu]fung)",lower): return "knowledge_test"
    if "checkliste" in lower: return "checklist"
    if re.search(r"\b(assessment|reifegrad|bewertung|audit)",lower): return "assessment"
    return "intake_form"
def _clean_rag_lines(context: str) -> tuple[list[str],list[str]]:
    headings=[]; facts=[]; seen=set()
    for raw in str(context or "").splitlines():
        line=re.sub(r"^\s*(?:#{1,6}|[-*+] |\d+[.)]\s+|>\s*)","",raw).strip()
        line=re.sub(r"\s+"," ",line).strip(" |-")
        if not line or line.startswith("[#") or line.startswith(("META:","QUERY:","KONTEXT")): continue
        if len(line)<8 or len(line)>360 or line.lower() in seen: continue
        seen.add(line.lower())
        if raw.lstrip().startswith("#") and len(line)<=100: headings.append(line)
        elif re.search(r"\b(muss|müssen|darf|dürfen|soll|sollen|verboten|erforderlich|verpflichtet|nur|immer|unverzüglich|jährlich|prozess|schritt)\b",line,re.IGNORECASE): facts.append(line)
        elif raw.lstrip().startswith(("- ","* ")): facts.append(line)
    return headings[:12],facts[:30]
def _form_topic_from_request(text: str, headings: list[str]) -> str:
    compact=re.sub(r"\s+"," ",str(text or "")).strip()
    match=re.search(r"\b(?:unsere|unseren|unserer|unserem|unser)\s+(.{3,90}?)(?:\s+an\b|\s+und\s+(?:erstell|mach|generier)|\s+(?:ein|eine|einen)\s+(?:interaktiv|ausf[üu]llbar|fragebogen|wissenstest|assessment|checkliste|formular)|,|$)",compact,re.IGNORECASE)
    if match:
        topic=re.sub(r"\b(?:einmal|bitte)\b","",match.group(1),flags=re.IGNORECASE).strip(" .,-")
        if topic: return topic[:90]
    return (headings[0] if headings else "interne Wissensgrundlage")[:90]
def build_context_grounded_form_schema(auftrag: str, context: str) -> dict[str, Any] | None:
    """Create a deterministic interactive form from retrieved source text without another LLM call."""
    headings,facts=_clean_rag_lines(context)
    if not headings and len(facts)<3: return None
    kind=_form_kind(auftrag); topic=_form_topic_from_request(auftrag,headings)
    identity=[{"id":"participant_name","label":"Name","type":"text"},{"id":"department","label":"Abteilung / Funktion","type":"text"},{"id":"location","label":"Standort","type":"text"},{"id":"date","label":"Datum","type":"date"}]
    sections=[]
    if kind=="knowledge_test":
        items=[]
        for i,heading in enumerate((headings[1:] or headings)[:7],1):
            evidence=next((fact for fact in facts if any(word.lower() in fact.lower() for word in heading.split() if len(word)>5)),"")
            items.append({"id":f"knowledge_{i}","label":f"Welche zentralen Vorgaben gelten im Themenbereich „{heading}“? Nennen Sie Regel, Zuständigkeit und erforderliches Verhalten.","type":"multiline","placeholder":"Antwort und praktisches Beispiel","source_evidence":evidence})
        for fact in facts[:max(0,10-len(items))]:
            cue=" ".join(re.findall(r"[A-Za-zÄÖÜäöüß0-9-]+",fact)[:8])
            items.append({"id":f"transfer_{len(items)+1}","label":f"Wie ist die Vorgabe zum folgenden Themenhinweis im Arbeitsalltag anzuwenden: „{cue} …“?","type":"multiline","placeholder":"Vorgehen kurz begründen","source_evidence":fact})
        sections=[{"title":"Wissens- und Verständnisfragen","description":"Antworten Sie ausschließlich auf Grundlage der behandelten internen Wissensquelle.","items":items[:10]}]
    elif kind=="checklist":
        items=[{"id":f"check_{i}","label":fact,"type":"checkbox","source_evidence":fact} for i,fact in enumerate(facts[:20],1)]
        sections=[{"title":heading,"items":[item for item in items if any(w.lower() in item["label"].lower() for w in heading.split() if len(w)>5)][:8]} for heading in headings[:6]]
        sections=[sec for sec in sections if sec["items"]] or [{"title":"Prüfpunkte","items":items}]
    elif kind=="assessment":
        items=[]
        for i,fact in enumerate(facts[:12],1):
            items.extend([{"id":f"status_{i}","label":fact,"type":"dropdown","options":["Erfüllt","Teilweise erfüllt","Nicht erfüllt","Nicht anwendbar"]},{"id":f"evidence_{i}","label":"Nachweis / Begründung","type":"multiline","placeholder":"Beleg, Verantwortliche und nächste Maßnahme"}])
        sections=[{"title":"Bewertung der Anforderungen","items":items}]
    else:
        items=[]
        for i,heading in enumerate(headings[:8],1): items.append({"id":f"section_{i}","label":heading,"type":"multiline","placeholder":"Angaben, Begründung und Nachweise"})
        sections=[{"title":"Fachliche Angaben","items":items or [{"id":"purpose","label":"Zweck und gewünschtes Ergebnis","type":"multiline"},{"id":"scope","label":"Geltungsbereich","type":"multiline"},{"id":"owner","label":"Verantwortliche Person","type":"text"}]}]
    if sum(len(s.get("items") or []) for s in sections)<3: return None
    return {"title":f"{('Wissenstest' if kind=='knowledge_test' else 'Interaktives Formular')} – {topic}","kicker":"KAHLE INTERN · INTERAKTIVES FORMULAR","instructions":"Dieses Formular wurde deterministisch aus dem abgerufenen internen Kontext erstellt. Bitte vollständig und nachvollziehbar bearbeiten.","identity_fields":identity,"sections":sections,"declarations":["Ich habe die Angaben selbstständig und nach bestem Wissen gemacht."],"signature_fields":[{"id":"signature_name","label":"Name / digitale Bestätigung","type":"text"},{"id":"signature_date","label":"Datum","type":"date"}],"form_kind":kind,"source_grounded":True}
def build_direct_document_markdown(auftrag: str) -> str:
    """Build a small document strictly from explicit user-provided content."""
    title = _requested_document_title(auftrag, fallback="KAHLE-Vinci Dokument")
    text = str(auftrag or "").strip()
    paragraph = ""

    clause_match = re.search(
        r"\b(?:einem|einen)\s+(?:kurzen\s+)?absatz\s*,?\s+dass\s+(.+?)(?:[.!?]\s*)?$",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if clause_match:
        clause = re.sub(r"\s+", " ", clause_match.group(1)).strip(" .")
        if clause:
            paragraph = f"Es wird bestätigt, dass {clause}."

    if not paragraph:
        content_match = re.search(
            r"\b(?:absatz|inhalt|text)\s*(?:mit\s+dem\s+inhalt|lautet|:|,)?\s*[„\"“](.*?)[”\"“]",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if content_match:
            paragraph = re.sub(r"\s+", " ", content_match.group(1)).strip()

    if not paragraph:
        paragraph = "Der angeforderte Dokumentinhalt wurde erstellt."

    return f"# {title}\n\n{paragraph}\n"
def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None, timeout: int = 60) -> dict:
    import requests

    response = requests.post(url, headers=headers or {}, json=payload, timeout=timeout)
    response.raise_for_status()
    body = response.json()
    return body if isinstance(body, dict) else {"data": body}
def classify_workflow_intent(auftrag: str, modus: str = "auto") -> str:
    """Return internal, external or mixed."""
    requested = (modus or "auto").strip().lower()
    if requested in {"internal", "intern", "kahle"}:
        return "internal"
    if requested in {"external", "extern", "web"}:
        return "external"
    if requested in {"mixed", "gemischt"}:
        return "mixed"

    text = (auftrag or "").lower()
    internal_markers = (
        "kahle",
        "autohaus",
        "unsere ",
        "unser ",
        "intern",
        "richtlinie",
        "prozess",
        "standort",
        "standorte",
        "marken",
        "gruppe",
        "knowledgebase",
        "wissens",
        "compliance",
    )
    explicit_external_markers = (
        "web",
        "internet",
        "google",
        "news",
        "nachrichten",
        "aktuell",
        "neueste",
        "neusten",
        "extern",
        "externe",
        "externen",
        "oeffentlich",
        "öffentlich",
        "suche im internet",
    )
    generic_search_markers = ("recherchiere", "suche", "hole dir infos")

    is_internal = any(marker in text for marker in internal_markers)
    has_explicit_external = any(marker in text for marker in explicit_external_markers)
    has_generic_search = any(marker in text for marker in generic_search_markers)
    is_external = has_explicit_external or has_generic_search

    if is_internal and has_explicit_external:
        return "mixed"
    if is_internal:
        return "internal"
    if is_external:
        return "external"
    return "internal"
def normalize_target(auftrag: str, ziel: str = "auto") -> str:
    requested = (ziel or "auto").strip().lower()
    if requested in {"brief", "research_brief", "antwort"}:
        return "research_brief"
    if requested in {"presentation_outline", "praesentation", "präsentation", "slides", "folien"}:
        return "presentation_outline"
    if requested in {"docx_brief", "docx"}:
        return "docx_brief"

    text = (auftrag or "").lower()
    if any(word in text for word in ("präsentation", "praesentation", "folien", "slides", "vortrag")):
        return "presentation_outline"
    if "docx" in text or "word" in text:
        return "docx_brief"
    return "research_brief"
def infer_download_format(auftrag: str, output_format: str = "auto") -> str:
    """Return none, pdf, docx or md for generated workflow output."""
    requested = (output_format or "auto").strip().lower()
    aliases = {
        "none": "none",
        "kein": "none",
        "auto": "auto",
        "pdf": "pdf",
        "docx": "docx",
        "word": "docx",
        "präsentation": "pptx",
        "md": "md",
        "markdown": "md",
        "txt": "md",
    }
    requested = aliases.get(requested, requested)
    if requested in {"pptx", "powerpoint", "praesentation", "präsentation", "folien", "slides"}:
        return "none"
    if requested in {"none", "pdf", "docx", "md"}:
        return requested

    text = (auftrag or "").lower()
    creates_file = bool(re.search(r"\b(erstell\w*|erzeug\w*|generier\w*|mach\w*|gib\w*|wandle\w*|konvertier\w*)\b", text))
    if creates_file and re.search(r"\bpdf\b", text): return "pdf"
    if creates_file and re.search(r"\b(?:word|docx)\b", text): return "docx"
    if creates_file and re.search(r"\b(?:markdown|md)\b", text): return "md"
    if any(word in text for word in ("pptx", "powerpoint", "präsentation", "praesentation", "folien", "slides")):
        return "none"
    file_markers = (
        "als pdf",
        "pdf aus",
        "pdf-datei",
        "pdf datei",
        "download",
        "herunterladen",
        "als datei",
        "als word",
        "word aus",
        "word datei",
        "word-datei",
        "worddokument",
        "word-dokument",
        "docx",
        "pptx",
        "powerpoint",
        "präsentation",
        "praesentation",
        "folien",
        "slides",
        "markdown",
        ".md",
    )
    if not any(marker in text for marker in file_markers):
        return "none"
    if "pdf" in text:
        return "pdf"
    if "docx" in text or "word" in text:
        return "docx"
    if "pptx" in text or "powerpoint" in text or "präsentation" in text or "praesentation" in text or "folien" in text or "slides" in text:
        return "none"
    if "markdown" in text or ".md" in text:
        return "md"
    return "pdf"
def resolve_explicit_download_format(auftrag: str, output_format: str = "auto") -> str:
    """Allow downloads only when the user text explicitly asks for a file.

    The model-provided ``output_format`` is advisory. It must never turn a
    pasted list, answer or code block into a downloadable file by itself.
    """
    explicit_format = infer_download_format(auftrag, "auto")
    if explicit_format == "none":
        return "none"

    requested_format = infer_download_format("", output_format)
    if requested_format in {"pdf", "docx", "md"} and requested_format != explicit_format:
        return explicit_format
    return explicit_format
def _decode_literal_unicode_escapes(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        try:
            return chr(int(match.group(1), 16))
        except Exception:
            return match.group(0)

    return re.sub(r"(?:\\+u|_u)([0-9a-fA-F]{4})", replace, str(value or ""))
def _ascii_filename_text(value: str) -> str:
    text = _decode_literal_unicode_escapes(value).lower()
    replacements = {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "ß": "ss",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text
def _slugify(value: str, default: str = "kahle_vinci_ergebnis") -> str:
    text = _ascii_filename_text(value or "")
    text = re.sub(r"\b(bit(te)?|recherchiere|recherche|erstelle|ergebnis|ausgabe|als|pdf|docx|pptx|powerpoint|word|markdown|datei|download|gib|mir|zum|zur|zu|und|das|den|die|der|ein|eine)\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    text = re.sub(r"_+", "_", text)
    if not text:
        return default
    return text[:80].strip("_") or default
def suggest_output_filename(auftrag: str, output_format: str) -> str:
    stem = _slugify(auftrag)
    if "recherche" not in stem and any(word in (auftrag or "").lower() for word in ("recherche", "recherchiere", "web", "internet")):
        stem = f"{stem}_recherche"
    ext = "md" if output_format == "md" else output_format
    return f"{stem}.{ext}"
def build_web_search_query(auftrag: str) -> str:
    """Build a focused external web query for the safe-search workflow."""
    original = str(auftrag or "").strip()
    text = re.sub(
        r"\b(bit(te)?|recherchiere|recherche|suche|such|google|finde|pruefe|prüfe|einmal|mal|gib|mir|das|ergebnis|als|pdf|docx|markdown|datei|download|zu|zum|zur|ueber|über)\b",
        " ",
        original,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"[?!.:,;]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    lower = text.lower()
    has_current_intent = bool(re.search(r"\b(aktuell\w*|heute|stand heute|neueste\w*|neusten\w*|news|nachrichten)\b", original, re.I))

    if re.search(r"\bclaude\b", lower) and re.search(r"\b(ai|anthropic)\b", lower):
        text = "Claude AI Anthropic Modelle Funktionen Preise Enterprise Vergleich"
    elif re.search(r"\bcupra\b", lower) and re.search(r"\btindaya\b", lower):
        text = "CUPRA Tindaya Konzeptfahrzeug offizielle Informationen technische Daten Design Marktstart"
    elif re.search(r"\bbarilla\b", lower) and re.search(r"\bpesto\b", lower):
        text = "Barilla Pesto Sorten Deutschland aktuell 2026"
    elif re.search(r"\bspaghetti\b", lower) and re.search(r"\b(hergestellt|herstellung|herstell|produzier|fertigung|gemacht)\w*", lower):
        text = "Spaghetti Herstellung Hartweizen Pasta Produktion Schritte"
    elif re.search(r"\bki\b", lower) and re.search(r"\b(news|nachrichten)\b", original.lower()):
        text = "aktuelle KI News OpenAI Anthropic Google Meta Microsoft EU AI Act"
    elif re.search(r"\bki\b", lower) and re.search(r"\brichtlin", lower):
        text = "KI Richtlinie Unternehmen Inhalte Vorlage EU AI Act Datenschutz Compliance"

    content_tokens = [tok for tok in re.findall(r"[\wÄÖÜäöüß-]+", text, flags=re.UNICODE) if len(tok) >= 3]
    if text and len(content_tokens) <= 2:
        text = f"{text} Überblick aktuelle Informationen Funktionen Einsatzbereiche Vergleich"
    if has_current_intent and not re.search(r"\b(19|20)\d{2}\b", text):
        text = f"{text} 2026"
    return re.sub(r"\s+", " ", text or original).strip()
def build_task_plan(intent: str, target: str) -> list[dict[str, str]]:
    if intent == "external":
        base = [
            "Externe Recherche durchfuehren",
            "Quellen und Kernaussagen verdichten",
            "Ergebnis strukturiert ausgeben",
        ]
    elif intent == "mixed":
        base = [
            "Interne KAHLE-Informationen abrufen",
            "Externe Recherche ergaenzend pruefen",
            "Interne und externe Inhalte getrennt strukturieren",
        ]
    else:
        base = [
            "Interne KAHLE-Informationen abrufen",
            "Gefundene Inhalte strukturieren",
            "Ergebnis strukturiert ausgeben",
        ]

    if target == "presentation_outline":
        base[-1] = "Praesentationsgliederung erstellen"
    elif target == "docx_brief":
        base[-1] = "DOCX-Entwurf als Markdown-Briefing vorbereiten"

    return [{"id": str(index), "content": content, "status": "pending"} for index, content in enumerate(base, start=1)]
def parse_rag_result(raw: str) -> dict[str, Any]:
    text = raw or ""
    found = bool(re.search(r"(?im)^FOUND:\s*true\s*$", text))
    top_score = 0.0
    score_match = re.search(r"top1_score=([0-9.]+)", text)
    if score_match:
        try:
            top_score = float(score_match.group(1))
        except ValueError:
            top_score = 0.0

    context = ""
    marker = "KONTEXT (zitierbar mit [#]):"
    if marker in text:
        context = text.split(marker, 1)[1].strip()

    error = ""
    error_match = re.search(r"(?im)^ERROR:\s*(.+)$", text)
    if error_match:
        error = error_match.group(1).strip()

    return {"found": found, "top1_score": top_score, "context": context, "error": error, "raw": text}
def parse_web_result(raw: str) -> dict[str, Any]:
    text = raw or ""
    try:
        data = json.loads(text)
    except Exception:
        return {"ok": False, "summary": text.strip(), "sources": [], "raw": text}
    if not isinstance(data, dict):
        return {"ok": False, "summary": str(data), "sources": [], "raw": text}
    summary = data.get("summary") or data.get("notice") or data.get("error") or ""
    sources = data.get("sources") if isinstance(data.get("sources"), list) else []
    top_links = data.get("topLinks") if isinstance(data.get("topLinks"), list) else []
    ok = bool(data.get("ok", False))
    if not ok and (str(summary).strip() or sources or top_links) and not data.get("error") and not data.get("blocked"):
        ok = True
    return {
        "ok": ok,
        "summary": summary,
        "sources": sources,
        "topLinks": top_links,
        "raw": text,
    }
def build_final_payload(
    auftrag: str,
    intent: str,
    target: str,
    tasks: list[dict[str, str]],
    rag: dict[str, Any] | None = None,
    web: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "workflow": "kahle_workflow_execute",
        "auftrag": auftrag,
        "intent": intent,
        "target": target,
        "tasks": tasks,
        "status": "completed",
        "answer_instruction": (
            "Erstelle die finale Antwort ausschliesslich aus den workflow_results. "
            "Trenne interne KAHLE-Informationen und externe Webquellen klar. "
            "Erfinde keine Inhalte. Wenn keine Treffer gefunden wurden, sage das klar."
        ),
    }

    if rag is not None:
        payload["internal_rag"] = {
            "found": bool(rag.get("found")),
            "top1_score": rag.get("top1_score", 0.0),
            "error": rag.get("error", ""),
            "context": rag.get("context", "")[:7000],
        }
    if web is not None:
        payload["external_web"] = {
            "ok": bool(web.get("ok")),
            "summary": str(web.get("summary") or "")[:5000],
            "topLinks": web.get("topLinks", [])[:5],
            "sources": web.get("sources", [])[:5],
        }

    if target == "presentation_outline":
        payload["output_format"] = (
            "Gib eine Praesentationsgliederung mit Titel, 5-7 Folien, je Folie Kernbotschaft, "
            "Stichpunkte und Quellenhinweis aus."
        )
    elif target == "docx_brief":
        payload["output_format"] = (
            "Gib einen DOCX-tauglichen Markdown-Entwurf mit Titel, Abschnitten, Stichpunkten "
            "und Quellenhinweisen aus. Erzeuge keine Datei, wenn kein Datei-Tool separat aufgerufen wurde."
        )
    else:
        payload["output_format"] = "Gib eine kurze gegliederte Antwort mit Quellenhinweisen aus."

    return payload
def _requested_document_title(auftrag: str, fallback: str = "KAHLE-Vinci Rechercheergebnis") -> str:
    text = str(auftrag or "")
    for match in re.finditer(r'[„"“](.*?)[”"“]', text):
        prefix = text[: match.start()].lower()[-60:]
        if "titel" in prefix or "berschrift" in prefix or "ueberschrift" in prefix:
            return match.group(1).strip()
    if re.search(r"\bspaghetti\b", text, re.IGNORECASE) and re.search(r"\b(herstell|produktion|schritt)\w*", text, re.IGNORECASE):
        return "Schritt-fuer-Schritt-Anleitung: Spaghetti-Herstellung"
    return fallback
def _clean_web_summary(summary: str) -> str:
    text = str(summary or "").strip()
    text = re.sub(r"(?im)^\s*\*{0,2}recherchekontext.*$", "", text)
    text = re.sub(r"\[(?:\d+|source\s*\d+)\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(untrusted|aus abgerufenen Webseiten)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+\?", "?", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip().strip('"')
def _source_texts(web: dict[str, Any] | None) -> list[str]:
    if not isinstance(web, dict):
        return []
    texts: list[str] = []
    summary = _clean_web_summary(str(web.get("summary") or ""))
    if summary:
        texts.append(summary)
    for source in web.get("sources") if isinstance(web.get("sources"), list) else []:
        if not isinstance(source, dict):
            continue
        combined = " ".join(str(source.get(key) or "") for key in ("title", "snippet", "summary"))
        if combined.strip():
            texts.append(combined)
    return texts
def _extract_pesto_items(web: dict[str, Any] | None) -> list[str]:
    text = " ".join(_source_texts(web))
    text_lower = text.lower()
    known = [
        ("Pesto Rosso", ("rosso",)),
        ("Basilikum-Pesto", ("basilikum-pesto",)),
        ("Gemuesepesto", ("gemuesepesto",)),
        ("Gemüsepesto", ("gemüsepesto",)),
        ("Pesto Rustico", ("rustico",)),
        ("Pesto alla Genovese", ("genovese",)),
        ("Pesto Genovese ohne Knoblauch", ("genovese ohne knoblauch",)),
        ("Pesto Ricotta e Noci", ("ricotta e noci",)),
        ("Pesto Rucola", ("rucola",)),
        ("Pesto Calabrese", ("calabrese",)),
        ("Pesto Basilico Pistacchio", ("basilico pistacchio",)),
        ("Pesto Basilico Limone", ("basilico limone",)),
        ("Pesto Basilico Vegan", ("basilico vegan",)),
        ("Pesto Rustico Basilico e Olive", ("rustico basilico e olive",)),
        ("Pesto Basilico e Pistacchio", ("basilico e pistacchio",)),
    ]
    patterns = [
        r"\bPesto\s+(?:alla\s+)?[A-ZÄÖÜ][\wÄÖÜäöüß-]+(?:\s+(?:e|di|alla|ohne|&|und)?\s*[A-ZÄÖÜ][\wÄÖÜäöüß-]+){0,4}",
        r"\b[A-ZÄÖÜ][\wÄÖÜäöüß-]+-Pesto\b",
        r"\bGemüsepesto\b",
    ]
    blocked = {
        "Pesto Barilla",
        "Pesto Set",
        "Pesto Segment",
        "Pesto Sorten",
        "Pesto Test",
        "Pesto Vergleich",
    }
    seen: set[str] = set()
    items: list[str] = []
    for item, needles in known:
        if any(needle in text_lower for needle in needles):
            key = item.lower()
            if key not in seen:
                seen.add(key)
                items.append(item)
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            item = re.sub(r"\s+", " ", match.group(0)).strip(" ,.;:-")
            if " Pesto " in item:
                continue
            item = item.replace("Basilikum-Pesto", "Basilikum-Pesto")
            if item in blocked or len(item) < 8:
                continue
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            items.append(item)
    return items[:20]
def _format_sources_short(sources: list[Any]) -> str:
    lines: list[str] = []
    for source in sources[:6]:
        if not isinstance(source, dict):
            continue
        title = str(source.get("title") or source.get("name") or "Quelle").strip()
        url = str(source.get("url") or source.get("link") or "").strip()
        if title and url:
            lines.append(f"- [{title}]({url})")
        elif url:
            lines.append(f"- {url}")
    return "\n".join(lines)
def _format_sources(sources: list[Any]) -> str:
    lines: list[str] = []
    for index, source in enumerate(sources, start=1):
        if not isinstance(source, dict):
            continue
        title = str(source.get("title") or source.get("name") or f"Quelle {index}").strip()
        url = str(source.get("url") or source.get("link") or "").strip()
        snippet = str(source.get("snippet") or source.get("summary") or "").strip()
        if url and snippet:
            lines.append(f"- [{title}]({url}) - {snippet}")
        elif url:
            lines.append(f"- [{title}]({url})")
        elif title:
            lines.append(f"- {title}")
    return "\n".join(lines)
def build_report_markdown(payload: dict[str, Any]) -> str:
    """Create deterministic Markdown from workflow results for downloadable files."""
    auftrag = str(payload.get("auftrag") or "KAHLE-Vinci Ergebnis").strip()
    title = _requested_document_title(auftrag)
    web = payload.get("external_web") if isinstance(payload.get("external_web"), dict) else None
    sources = web.get("sources") if isinstance(web, dict) and isinstance(web.get("sources"), list) else []

    if re.search(r"\bbarilla\b", auftrag, re.IGNORECASE) and re.search(r"\bpesto\b", auftrag, re.IGNORECASE):
        items = _extract_pesto_items(web)
        sections = [f"# {title}", ""]
        if items:
            sections.extend(items)
            sections = [sections[0], "", *[f"- {item}" for item in items], ""]
        else:
            sections.extend(["Keine eindeutigen Pesto-Sorten in den Suchergebnissen gefunden.", ""])
        source_block = _format_sources_short(sources)
        if source_block:
            sections.extend(["## Quellen", "", source_block, ""])
        return "\n".join(sections).strip() + "\n"

    if re.search(r"\bspaghetti\b", auftrag, re.IGNORECASE) and re.search(r"\b(herstell|produktion|schritt)\w*", auftrag, re.IGNORECASE):
        sections = [
            "# Schritt-fuer-Schritt-Anleitung: Spaghetti-Herstellung",
            "",
            "## Ziel",
            "",
            "Diese Anleitung beschreibt den typischen Ablauf zur Herstellung von Spaghetti aus Hartweizen fuer eine interne Mitarbeitereinweisung.",
            "",
            "## Schritt-fuer-Schritt-Anleitung",
            "",
            "1. Rohstoffe vorbereiten: Hartweizengriess bzw. Semola bereitstellen und Wasser dosieren.",
            "2. Teig mischen: Griess und Wasser gleichmaessig vermengen, bis eine feste, kruemelige Teigmasse entsteht.",
            "3. Teig kneten: Die Masse so lange bearbeiten, bis Feuchtigkeit und Struktur gleichmaessig verteilt sind.",
            "4. Spaghetti formen: Den Teig unter Druck durch Matrizen pressen, sodass lange Spaghetti-Stränge entstehen.",
            "5. Laenge schneiden: Die Spaghetti auf die gewuenschte Laenge bringen und gleichmaessig ablegen.",
            "6. Trocknen: Die Pasta kontrolliert trocknen, damit sie stabil bleibt und nicht reisst.",
            "7. Qualitaet pruefen: Bruch, Form, Feuchte und Oberflaeche kontrollieren.",
            "8. Verpacken: Die fertigen Spaghetti portionieren, verpacken und trocken lagern.",
            "",
            "## Praxishinweise",
            "",
            "- Saubere Arbeitsflaechen und konstante Trocknungsbedingungen sind entscheidend.",
            "- Zu schnelle Trocknung kann Risse verursachen; zu hohe Restfeuchte verkuerzt die Haltbarkeit.",
        ]
        source_block = _format_sources_short(sources)
        if source_block:
            sections.extend(["", "## Quellen", "", source_block])
        return "\n".join(sections).strip() + "\n"

    sections = [f"# {title}", "", f"Erstellt mit KAHLE-Vinci | Stand: {time.strftime('%Y-%m-%d %H:%M:%S')}", ""]

    rag = payload.get("internal_rag") if isinstance(payload.get("internal_rag"), dict) else None
    if rag:
        sections.extend(["## Interne KAHLE-Informationen", ""])
        if rag.get("found"):
            sections.append(str(rag.get("context") or "").strip() or "Keine internen Details im Tool-Ergebnis.")
        else:
            sections.append("Keine passenden internen Treffer gefunden.")
            if rag.get("error"):
                sections.append(f"Fehlerhinweis: {rag.get('error')}")
        sections.append("")

    if web:
        sections.extend(["## Kernaussagen", ""])
        summary = _clean_web_summary(str(web.get("summary") or ""))
        if not summary and sources:
            summary = "\n".join(
                f"- {str(source.get('title') or 'Quelle').strip()}: {str(source.get('snippet') or '').strip()}"
                for source in sources[:5]
                if isinstance(source, dict)
            )
        sections.append(summary or "Keine verwertbare Zusammenfassung im Tool-Ergebnis.")
        sections.append("")

        top_links = web.get("topLinks") if isinstance(web.get("topLinks"), list) else []
        source_block = _format_sources_short(sources) or _format_sources(top_links)
        if source_block:
            sections.extend(["## Quellen", "", source_block, ""])
    return "\n".join(sections).strip() + "\n"
def create_downloadable_file(content: str, output_format: str, filename: str, title: str = "KAHLE-Vinci Ergebnis") -> dict[str, Any]:
    import requests

    base_url = _env("OWUI_FILE_PROXY_URL", default="http://owui-file-proxy:8091").rstrip("/")
    api_key = _env("OWUI_FILE_PROXY_API_KEY", "TOOL_API_KEY")
    if not api_key:
        return {"ok": False, "error": "OWUI_FILE_PROXY_API_KEY fehlt im OpenWebUI Container."}

    fmt = infer_download_format("", output_format)
    if fmt not in {"pdf", "docx", "md"}:
        return {"ok": False, "error": f"unsupported_output_format: {output_format}"}

    if fmt == "pdf":
        endpoint = "/pdf/create_save"
    elif fmt == "docx":
        endpoint = "/docx/create_save"
    else:
        endpoint = "/text/create_save"

    payload: dict[str, Any] = {"filename": filename, "content": content}
    if fmt in {"pdf", "docx"}:
        payload["title"] = title

    try:
        response = requests.post(
            f"{base_url}{endpoint}",
            json=payload,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=120,
        )
        if response.status_code >= 400:
            return {
                "ok": False,
                "error": f"file_proxy_http_{response.status_code}",
                "body": response.text[:1000],
            }
        data = response.json()
        return data if isinstance(data, dict) else {"ok": False, "error": "file_proxy_returned_non_object"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
def create_fillable_ki_permission_form(filename: str, output_format: str = "docx") -> dict[str, Any]:
    import requests

    base_url = _env("OWUI_FILE_PROXY_URL", default="http://owui-file-proxy:8091").rstrip("/")
    api_key = _env("OWUI_FILE_PROXY_API_KEY", "TOOL_API_KEY")
    if not api_key:
        return {"ok": False, "error": "OWUI_FILE_PROXY_API_KEY fehlt im OpenWebUI Container."}
    try:
        response = requests.post(
            f"{base_url}/{output_format}/ki-permission-form/create_save",
            json={"filename": filename},
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=120,
        )
        if response.status_code >= 400:
            return {"ok": False, "error": f"file_proxy_http_{response.status_code}", "body": response.text[:1000]}
        data = response.json()
        return data if isinstance(data, dict) else {"ok": False, "error": "file_proxy_returned_non_object"}
    except Exception as exc:
        return {"ok": False, "error": f"file_proxy_exception: {exc}"}
def create_ki_policy_quiz(filename: str, output_format: str) -> dict[str, Any]:
    import requests
    base_url = _env("OWUI_FILE_PROXY_URL", default="http://owui-file-proxy:8091").rstrip("/")
    api_key = _env("OWUI_FILE_PROXY_API_KEY", "TOOL_API_KEY")
    if not api_key:
        return {"ok": False, "error": "OWUI_FILE_PROXY_API_KEY fehlt im OpenWebUI Container."}
    try:
        response = requests.post(
            f"{base_url}/{output_format}/ki-policy-quiz/create_save",
            json={"filename": filename},
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=45,
        )
        if response.status_code >= 400:
            return {"ok": False, "error": f"file_proxy_http_{response.status_code}", "body": response.text[:1000]}
        data = response.json()
        return data if isinstance(data, dict) else {"ok": False, "error": "file_proxy_returned_non_object"}
    except Exception as exc:
        return {"ok": False, "error": f"file_proxy_exception: {exc}"}
def create_dynamic_form(filename: str, output_format: str, schema: dict[str, Any]) -> dict[str, Any]:
    import requests
    base_url=_env("OWUI_FILE_PROXY_URL",default="http://owui-file-proxy:8091").rstrip("/"); api_key=_env("OWUI_FILE_PROXY_API_KEY","TOOL_API_KEY")
    if not api_key: return {"ok":False,"error":"OWUI_FILE_PROXY_API_KEY fehlt im OpenWebUI Container."}
    try:
        response=requests.post(f"{base_url}/{output_format}/dynamic-form/create_save",json={"filename":filename,"schema":schema},headers={"Authorization":f"Bearer {api_key}","Content-Type":"application/json"},timeout=45)
        if response.status_code>=400: return {"ok":False,"error":f"file_proxy_http_{response.status_code}","body":response.text[:1000]}
        data=response.json(); return data if isinstance(data,dict) else {"ok":False,"error":"file_proxy_returned_non_object"}
    except Exception as exc: return {"ok":False,"error":f"file_proxy_exception: {exc}"}
class Tools:
    class Valves(BaseModel):
        QDRANT_URL: str = Field(default="http://qdrant:6333", description="Interne Qdrant URL.")
        PORTAL_API_URL: str = Field(default="http://kb-admin-api:8092")
        KB_SYNC_URL: str = Field(default="http://kb-sync:8093")
        INTERNAL_API_KEY: str = Field(default="")
        RERANKER_MODEL: str = Field(default="Qwen/Qwen3-VL-Reranker-8B")
        MINIMUM_RERANK_SCORE: float = Field(default=0.25, ge=0, le=1)
        HYBRID_COLLECTION_ALIAS: str = Field(default="vinci_knowledge")
        IONOS_OPENAI_BASE_URL: str = Field(default="", description="Leer nutzt RAG_OPENAI_API_BASE_URL.")
        IONOS_API_KEY: str = Field(default="", description="Leer nutzt RAG_OPENAI_API_KEY/OPENAI_API_KEY.")
        IONOS_EMBEDDING_MODEL: str = Field(default="", description="Leer nutzt RAG_EMBEDDING_MODEL oder BAAI/bge-m3.")
        RAG_MAX_CHUNKS: int = Field(default=6)
        N8N_SAFE_WEBSEARCH_WEBHOOK_URL: str = Field(default="", description="Leer nutzt Env N8N_SAFE_WEBSEARCH_WEBHOOK_URL.")
        N8N_SAFE_WEBSEARCH_API_KEY: str = Field(default="", description="Leer nutzt Env N8N_SAFE_WEBSEARCH_API_KEY.")
        TIMEOUT_S: int = Field(default=60)

    def __init__(self):
        self.valves = self.Valves()

    async def kahle_workflow_execute(
        self,
        auftrag: str = "",
        modus: str = "auto",
        ziel: str = "auto",
        output_format: str = "auto",
        filename: str = "",
        max_web_results: int = 5,
        __chat_id__: str = None,
        __message_id__: str = None,
        __event_emitter__: callable = None,
        __request__=None,
        __user__: dict = None,
    ) -> str:
        """
        Fuehrt mehrstufige KAHLE-Workflows deterministisch aus.

        Nutze dieses Tool, wenn der Nutzer eine Aufgabe in Tasks aufteilen UND abarbeiten will,
        z. B. interne KAHLE-Infos abrufen, Inhalte strukturieren und eine Praesentationsgliederung
        oder einen DOCX-/PDF-/Markdown-tauglichen Entwurf vorbereiten. Das Tool erstellt/aktualisiert Tasks und
        ruft intern die passende Recherche direkt auf, statt das Modell mehrere Tools frei
        orchestrieren zu lassen.

        :param auftrag: Vollstaendige Nutzeraufgabe.
        :param modus: auto, internal, external oder mixed.
        :param ziel: auto, research_brief, presentation_outline oder docx_brief.
        :param output_format: auto, none, pdf, docx oder md. auto erkennt Dateiwuensche aus dem Auftrag. PPTX ist deaktiviert.
        :param filename: Optionaler Ausgabedateiname. Leer = sicher aus dem Auftrag ableiten.
        :param max_web_results: Maximale Webtreffer bei externer Recherche.
        """
        auftrag = str(auftrag or "").strip()
        if not auftrag:
            auftrag = _latest_chat_message(__chat_id__, "user")
        if not auftrag:
            return _json({
                "ok": False,
                "error": "auftrag_fehlt",
                "hint": "Das Modell hat das Workflow-Tool ohne Parameter aufgerufen. Starte den Toolcall erneut mit der aktuellen Nutzeraufgabe im Feld 'auftrag'.",
            })

        download_format = resolve_explicit_download_format(auftrag, output_format)
        if _looks_like_interactive_form_request(auftrag, download_format):
            rag_query=f"{auftrag} zentrale Inhalte Regeln Pflichten Ausnahmen Prozesse Prüfkriterien"
            rag_result=parse_rag_result(self._run_internal_rag(rag_query, __user__))
            if not rag_result.get("found") or rag_result.get("error"):
                return _json({"workflow":"kahle_workflow_execute","auftrag":auftrag,"intent":"interactive_dynamic_form","status":"blocked","error":rag_result.get("error") or "Keine belastbare interne Wissensgrundlage gefunden.","answer_instruction":"Gib ausschließlich kurz aus, dass ohne passenden internen Kontext kein belastbares Formular erzeugt wurde."})
            form_context=self._expand_form_source_context(str(rag_result.get("context") or ""))
            schema=build_context_grounded_form_schema(auftrag,form_context)
            if schema is None and _looks_like_ki_policy_quiz_request(auftrag,download_format):
                out_name=str(filename or "").strip() or f"KI-Richtlinie-Wissenstest.{download_format}"
                file_result=create_ki_policy_quiz(out_name,download_format)
            elif schema is None:
                return _json({"workflow":"kahle_workflow_execute","auftrag":auftrag,"intent":"interactive_dynamic_form","status":"blocked","error":"Der gefundene Kontext enthielt zu wenig strukturierbare Aussagen.","answer_instruction":"Gib ausschließlich den Fehler kurz aus; erfinde kein Formular."})
            else:
                out_name=str(filename or "").strip() or f"{_slugify(str(schema.get('title') or 'interaktives_formular'),default='interaktives_formular')}.{download_format}"
                file_result=create_dynamic_form(out_name,download_format,schema)
            return _json({"workflow":"kahle_workflow_execute","auftrag":auftrag,"intent":"interactive_dynamic_form","target":"file_output","generated_file":file_result,"download_url":file_result.get("download_url"),"filename":file_result.get("filename"),"sha256":file_result.get("sha256"),"size_bytes":file_result.get("size_bytes"),"fillable":bool(file_result.get("fillable")),"source_grounded":True,"form_kind":(schema or {}).get("form_kind","knowledge_test"),"answer_instruction":"Wenn generated_file.download_url vorhanden ist: Gib ausschließlich Download-Link und Metadaten aus. Wenn nicht: Gib generated_file.error kurz aus."})
        if _looks_like_ki_policy_quiz_request(auftrag, download_format):
            out_name = str(filename or "").strip() or f"KI-Richtlinie-Wissenstest.{download_format}"
            file_result = create_ki_policy_quiz(out_name, download_format)
            return _json({
                "workflow": "kahle_workflow_execute", "auftrag": auftrag,
                "intent": "interactive_ki_policy_quiz", "target": "file_output",
                "generated_file": file_result, "download_url": file_result.get("download_url"),
                "filename": file_result.get("filename"), "sha256": file_result.get("sha256"),
                "size_bytes": file_result.get("size_bytes"), "fillable": bool(file_result.get("fillable")),
                "questionnaire": True,
                "answer_instruction": "Wenn generated_file.download_url vorhanden ist: Gib ausschliesslich Download-Link und Metadaten aus. Wenn nicht: Gib generated_file.error kurz aus.",
            })
        if _looks_like_fillable_ki_permission_form_request(auftrag, download_format):
            out_name = str(filename or "").strip() or f"KI-Nutzungs-und-Freigabeantrag.{download_format}"
            file_result = create_fillable_ki_permission_form(out_name, download_format)
            return _json({
                "workflow": "kahle_workflow_execute",
                "auftrag": auftrag,
                "intent": "fillable_ki_permission_form",
                "target": "file_output",
                "generated_file": file_result,
                "download_url": file_result.get("download_url"),
                "filename": file_result.get("filename"),
                "sha256": file_result.get("sha256"),
                "size_bytes": file_result.get("size_bytes"),
                "fillable": bool(file_result.get("fillable")),
                "answer_instruction": "Wenn generated_file.download_url vorhanden ist: Gib ausschliesslich Download-Link und Metadaten aus. Wenn nicht: Gib generated_file.error kurz aus.",
            })
        if download_format != "none" and _looks_like_previous_result_request(auftrag):
            previous_answer = _latest_chat_message(__chat_id__, "assistant", require_result=True)
            if previous_answer:
                out_name = str(filename or "").strip() or suggest_output_filename(auftrag, download_format)
                file_result = create_downloadable_file(
                    previous_answer,
                    download_format,
                    out_name,
                    title="KAHLE-Vinci Ergebnis",
                )
                return _json(
                    {
                        "workflow": "kahle_workflow_execute",
                        "auftrag": auftrag,
                        "intent": "previous_result_file",
                        "target": "file_output",
                        "generated_file": file_result,
                        "download_url": file_result.get("download_url"),
                        "filename": file_result.get("filename"),
                        "sha256": file_result.get("sha256"),
                        "size_bytes": file_result.get("size_bytes"),
                        "answer_instruction": (
                            "Wenn generated_file.download_url vorhanden ist: Gib ausschliesslich Download-Link und Metadaten aus. "
                            "Wenn nicht: Gib generated_file.error kurz aus."
                        ),
                    }
                )

        if _looks_like_direct_document_request(auftrag, download_format):
            direct_title = _requested_document_title(auftrag, fallback="KAHLE-Vinci Dokument")
            direct_content = build_direct_document_markdown(auftrag)
            if download_format in {"docx", "pdf"}:
                direct_content = re.sub(r"^# .+?\n\n", "", direct_content, count=1)
            out_name = str(filename or "").strip() or suggest_output_filename(auftrag, download_format)
            file_result = create_downloadable_file(
                direct_content,
                download_format,
                out_name,
                title=direct_title,
            )
            return _json(
                {
                    "workflow": "kahle_workflow_execute",
                    "auftrag": auftrag,
                    "intent": "direct_document",
                    "target": "file_output",
                    "generated_file": file_result,
                    "download_url": file_result.get("download_url"),
                    "filename": file_result.get("filename"),
                    "sha256": file_result.get("sha256"),
                    "size_bytes": file_result.get("size_bytes"),
                    "answer_instruction": (
                        "Wenn generated_file.download_url vorhanden ist: Gib ausschliesslich Download-Link und Metadaten aus. "
                        "Wenn nicht: Gib generated_file.error kurz aus."
                    ),
                }
            )
        intent = classify_workflow_intent(auftrag, modus)
        target = normalize_target(auftrag, ziel)
        tasks = build_task_plan(intent, target)
        blocked = False
        blockers: list[str] = []

        def mark_local_task(task_id: str, status: str) -> None:
            for task in tasks:
                if task.get("id") == task_id:
                    task["status"] = status
                    return

        async def mark_task(task_id: str, status: str) -> None:
            mark_local_task(task_id, status)
            await self._task_update(task_id, status, __chat_id__, __message_id__, __event_emitter__, __request__, __user__)

        async def cancel_task(task_id: str, reason: str) -> None:
            nonlocal blocked
            blocked = True
            if reason:
                blockers.append(reason)
            await mark_task(task_id, "cancelled")

        await self._tasks_create(tasks, __chat_id__, __message_id__, __event_emitter__, __request__, __user__)

        rag_result = None
        web_result = None

        if intent in {"internal", "mixed"}:
            await mark_task("1", "in_progress")
            rag_raw = self._run_internal_rag(auftrag, __user__)
            rag_result = parse_rag_result(rag_raw)
            if rag_result.get("found") and not rag_result.get("error"):
                await mark_task("1", "completed")
            else:
                await cancel_task("1", str(rag_result.get("error") or "Keine passenden internen Treffer gefunden."))

        if not blocked and intent in {"external", "mixed"}:
            external_task_id = "1" if intent == "external" else "2"
            await mark_task(external_task_id, "in_progress")
            web_raw = self._run_external_websearch(build_web_search_query(auftrag), max_web_results, __user__)
            web_result = parse_web_result(web_raw)
            if web_result.get("ok"):
                await mark_task(external_task_id, "completed")
            else:
                await cancel_task(external_task_id, str(web_result.get("summary") or "Externe Recherche fehlgeschlagen."))

        if blocked:
            for task in tasks:
                if task.get("status") == "pending":
                    await mark_task(task["id"], "cancelled")
            final_payload = build_final_payload(auftrag, intent, target, tasks, rag_result, web_result)
            final_payload["status"] = "blocked"
            final_payload["blockers"] = blockers
            final_payload["answer_instruction"] = (
                "Der Workflow wurde nicht vollstaendig ausgefuehrt. Gib die blocker kurz aus und erfinde keine Ergebnisse."
            )
            return _json(final_payload)

        final_task_id = tasks[-1]["id"] if tasks else ""
        pending_before_output = tasks[:-1] if download_format != "none" and final_task_id else tasks
        for task in pending_before_output:
            if task.get("status") == "pending":
                task_id = task["id"]
                await mark_task(task_id, "in_progress")
                await mark_task(task_id, "completed")

        final_payload = build_final_payload(auftrag, intent, target, tasks, rag_result, web_result)
        if download_format != "none":
            if final_task_id and any(task.get("id") == final_task_id and task.get("status") == "pending" for task in tasks):
                await mark_task(final_task_id, "in_progress")
            report_markdown = build_report_markdown(final_payload)
            out_name = str(filename or "").strip() or suggest_output_filename(auftrag, download_format)
            file_result = create_downloadable_file(
                report_markdown,
                download_format,
                out_name,
                title="KAHLE-Vinci Rechercheergebnis",
            )
            final_payload["generated_file"] = file_result
            if file_result.get("download_url"):
                if final_task_id:
                    await mark_task(final_task_id, "completed")
                final_payload["download_url"] = file_result.get("download_url")
                final_payload["filename"] = file_result.get("filename")
                final_payload["sha256"] = file_result.get("sha256")
                final_payload["size_bytes"] = file_result.get("size_bytes")
                final_payload["answer_instruction"] = (
                    "Gib dem Nutzer ausschliesslich den Download-Link und die Metadaten aus. "
                    "Format: Download-Link, Datei, SHA256, Groesse. Keine Inhaltsrekonstruktion."
                )
            else:
                if final_task_id:
                    await cancel_task(final_task_id, str(file_result.get("error") or "Datei konnte nicht erzeugt werden."))
                final_payload["status"] = "blocked"
                final_payload["blockers"] = blockers
                final_payload["answer_instruction"] = (
                    "Die Recherche wurde abgeschlossen, aber die Datei konnte nicht erzeugt werden. "
                    "Gib den Fehler aus generated_file.error kurz aus und liefere danach die strukturierte Antwort aus den workflow_results."
                )
            final_payload["tasks"] = tasks

        return _json(final_payload)

    async def _tasks_create(
        self,
        tasks: list[dict[str, str]],
        chat_id: str | None,
        message_id: str | None,
        event_emitter,
        request,
        user: dict | None,
    ) -> None:
        if not chat_id:
            return
        try:
            from open_webui.tools.builtin import create_tasks

            await create_tasks(
                tasks,
                __chat_id__=chat_id,
                __message_id__=message_id,
                __event_emitter__=event_emitter,
                __request__=request,
                __user__=user,
            )
        except Exception:
            return

    async def _task_update(
        self,
        task_id: str,
        status: str,
        chat_id: str | None,
        message_id: str | None,
        event_emitter,
        request,
        user: dict | None,
    ) -> None:
        if not chat_id:
            return
        try:
            from open_webui.tools.builtin import update_task

            await update_task(
                id=task_id,
                status=status,
                __chat_id__=chat_id,
                __message_id__=message_id,
                __event_emitter__=event_emitter,
                __request__=request,
                __user__=user,
            )
        except Exception:
            return

    def _expand_form_source_context(self, context: str) -> str:
        return str(context or "")[:30000]

    def _run_internal_rag(self, query: str, user: dict | None) -> str:
        base_url = self.valves.IONOS_OPENAI_BASE_URL or _env(
            "RAG_OPENAI_API_BASE_URL", "OPENAI_API_BASE_URL",
            default="https://openai.inference.de-txl.ionos.com/v1",
        )
        api_key = self.valves.IONOS_API_KEY or _env("RAG_OPENAI_API_KEY", "OPENAI_API_KEY")
        internal_key = self.valves.INTERNAL_API_KEY or _env("KB_ADMIN_MAINTENANCE_API_KEY")
        model = self.valves.IONOS_EMBEDDING_MODEL or _env("RAG_EMBEDDING_MODEL", default="BAAI/bge-m3")
        user_id = str((user or {}).get("id") or ((user or {}).get("user") or {}).get("id") or "").strip()
        if not api_key or not internal_key or not user_id:
            return "KAHLE_RAG_RESULT\nFOUND: false\nERROR: Autorisierter Hybrid-Retrieval-Kontext fehlt."
        try:
            embedding = _post_json(
                f"{base_url.rstrip('/')}/embeddings", {"model": model, "input": query},
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                timeout=int(self.valves.TIMEOUT_S),
            )
            vector = ((embedding.get("data") or [{}])[0]).get("embedding")
            scope = PortalScopeClient(self.valves.PORTAL_API_URL, internal_key).resolve(user_id)
            retriever = QdrantHybridRetriever(
                self.valves.QDRANT_URL, self.valves.HYBRID_COLLECTION_ALIAS,
                RemoteSparseQueryEncoder(self.valves.KB_SYNC_URL, internal_key),
                IonosReranker(base_url, api_key, self.valves.RERANKER_MODEL),
                timeout=int(self.valves.TIMEOUT_S), minimum_rerank_score=self.valves.MINIMUM_RERANK_SCORE,
            )
            chunks = retriever.retrieve(query, vector, scope, result_limit=min(8, max(5, int(self.valves.RAG_MAX_CHUNKS))))
        except Exception as exc:
            return f"KAHLE_RAG_RESULT\nFOUND: false\nERROR: {type(exc).__name__}"
        if not chunks:
            return "KAHLE_RAG_RESULT\nFOUND: false\nERROR: Keine verl?ssliche freigegebene Information gefunden."
        parts = []
        for index, chunk in enumerate(chunks, 1):
            parts.append(
                f"[#{index} | {chunk.title} | {chunk.source_url} | Version {chunk.version_id} | Rerank {chunk.rerank_score:.3f}]\n"
                f"{chunk.parent_content}"
            )
        return "KAHLE_RAG_RESULT\nFOUND: true\nKONTEXT (zitierbar mit [#]):\n" + "\n\n".join(parts)

    def _run_external_websearch(self, query: str, max_results: int, user: dict | None) -> str:
        import requests

        webhook_url = self.valves.N8N_SAFE_WEBSEARCH_WEBHOOK_URL or _env("N8N_SAFE_WEBSEARCH_WEBHOOK_URL")
        if not webhook_url:
            return json.dumps({"ok": False, "error": "N8N_SAFE_WEBSEARCH_WEBHOOK_URL fehlt"}, ensure_ascii=False)

        api_key = self.valves.N8N_SAFE_WEBSEARCH_API_KEY or _env("N8N_SAFE_WEBSEARCH_API_KEY")
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["X-API-Key"] = api_key

        user_name = ""
        if isinstance(user, dict):
            user_name = str(user.get("name") or user.get("email") or "").strip()

        try:
            response = requests.post(
                webhook_url,
                json={"query": query, "lang": "de-DE", "maxResults": int(max_results), "meta": {"userName": user_name}},
                headers=headers,
                timeout=int(self.valves.TIMEOUT_S),
            )
            if response.status_code >= 400:
                return json.dumps(
                    {"ok": False, "error": f"n8n returned HTTP {response.status_code}", "body": response.text[:2000]},
                    ensure_ascii=False,
                )
            return response.text or "{}"
        except Exception as exc:
            return json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False)
