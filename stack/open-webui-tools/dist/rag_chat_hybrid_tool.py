"""title: RAG Chat KAHLE Hybrid
version: 1.0.0
description: Berechtigungsgefilterte Dense+BM25-Suche mit RRF, Reranking und Quellen.
"""
# Erzeugt von stack/open-webui-tools/build_tools.py. Nicht direkt bearbeiten.
# Quellen: hybrid_retrieval.py, hybrid_retrieval_adapters.py, rag_chat_hybrid_tool.py
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from pydantic import BaseModel, Field
from typing import Any, Protocol
import hashlib
import json
import math
import os
import re
import requests
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
    "du", "uber", "weisst", "weiss", "weit", "kennt", "kennst", "ist", "sind",
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
_OPENING_HOURS_LOCATIONS = (
    ("hannover",),
    ("wunstorf",),
    ("wedemark",),
    ("walsrode",),
    ("neustadt", "rubenberge"),
    ("nienburg",),
    ("stadthagen",),
)
def opening_hours_all_locations_intent(query: str) -> bool:
    folded = unicodedata.normalize("NFKD", query or "").encode("ascii", "ignore").decode().casefold()
    if not ("offnungszeiten" in folded or "oeffnungszeiten" in folded):
        return False
    location_hits = sum(all(token in folded for token in location) for location in _OPENING_HOURS_LOCATIONS)
    return any(token in folded for token in ("alle standorte", "allgemein", "alles")) or location_hits >= 4
def focused_document_ids_for_query(
    query: str, candidates: list[dict[str, Any]],
) -> set[str]:
    if opening_hours_all_locations_intent(query):
        return set()
    return focused_document_ids(query, candidates)
def rerank_candidate_count(query: str, candidate_count: int, *, result_limit: int) -> int:
    if opening_hours_all_locations_intent(query):
        return min(candidate_count, 50)
    return min(candidate_count, result_limit * 3)
def _opening_hours_location_matches(
    point: dict[str, Any], location: tuple[str, ...],
) -> bool:
    payload = point.get("payload") or {}
    identity = "\n".join((
        str(payload.get("title") or ""),
        " > ".join(str(item) for item in (payload.get("heading_path") or ())),
    ))
    text = "\n".join((
        identity,
        str(payload.get("parent_content") or payload.get("content") or ""),
    ))
    folded_identity = (
        unicodedata.normalize("NFKD", identity)
        .encode("ascii", "ignore").decode().casefold()
    )
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().casefold()
    has_hours = (
        "offnungszeiten" in folded
        or "oeffnungszeiten" in folded
        or bool(re.search(r"\bmo\s*[-–]\s*fr\b", folded))
    )
    return has_hours and all(token in folded_identity for token in location)
def missing_opening_hours_locations(
    candidates: list[dict[str, Any]],
) -> list[tuple[str, ...]]:
    return [
        location for location in _OPENING_HOURS_LOCATIONS
        if not any(_opening_hours_location_matches(point, location) for point in candidates)
    ]
def diversify_opening_hours_locations(
    reranked: list[tuple[int, float]], candidates: list[dict[str, Any]],
    *, result_limit: int,
) -> list[tuple[int, float]]:
    """Return at most one opening-hours passage for each known location."""
    selected: list[tuple[int, float]] = []
    selected_indices: set[int] = set()
    for location in _OPENING_HOURS_LOCATIONS:
        for index, score in reranked:
            if index < 0 or index >= len(candidates) or index in selected_indices:
                continue
            if _opening_hours_location_matches(candidates[index], location):
                selected.append((index, score))
                selected_indices.add(index)
                break
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
        try:
            sparse = self.sparse_encoder.encode_query(query)
            build_id = str(sparse.pop("build_id", ""))
            if not build_id:
                raise RetrievalError("sparse_build_id_missing")
        except RetrievalError as exc:
            if not str(exc).startswith("sparse_"):
                raise
            sparse = None
            build_id = ""
        if build_id:
            acl["must"].append({"key": "build_id", "match": {"value": build_id}})
        if sparse is None:
            # Dense retrieval remains ACL-filtered and is still checked by the
            # external reranker. A temporary sparse encoder outage must not
            # make valid internal knowledge disappear completely.
            body = {
                "query": dense_vector,
                "using": "dense",
                "filter": acl,
                "limit": candidate_limit,
                "with_payload": True,
            }
        else:
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
        if opening_hours_all_locations_intent(query):
            candidates = self._complete_opening_hours_locations(candidates, acl)
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
        focused_ids = focused_document_ids_for_query(query, candidates) if not identifiers else set()
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
                rerank_candidate_count(query, len(candidates), result_limit=result_limit),
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
        elif opening_hours_all_locations_intent(query):
            ranked_selection = diversify_opening_hours_locations(
                reranked, candidates, result_limit=result_limit,
            )
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

    def _complete_opening_hours_locations(
        self, candidates: list[dict[str, Any]], acl: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Recover location passages omitted from the broad top-50 fusion pool.

        This remains one user-visible tool call. Only missing, known locations
        receive a narrow BM25 lookup and every recovered point still carries
        the same mandatory ACL filter.
        """
        result = list(candidates)
        seen = {
            str((point.get("payload") or {}).get("parent_id") or point.get("id") or "")
            for point in result
        }
        for location in missing_opening_hours_locations(result):
            try:
                sparse = self.sparse_encoder.encode_query(
                    "Öffnungszeiten Standort " + " ".join(location)
                    + " Verkauf Service Teiledienst"
                )
                sparse.pop("build_id", None)
                response = requests.post(
                    f"{self.qdrant_url}/collections/{self.alias}/points/query",
                    json={
                        "query": sparse,
                        "using": "bm25",
                        "filter": acl,
                        "limit": 8,
                        "with_payload": True,
                    },
                    timeout=self.timeout,
                )
                response.raise_for_status()
                points = response.json()["result"]["points"]
            except (RetrievalError, requests.RequestException, KeyError, TypeError, ValueError):
                continue
            for point in self._parent_centered(points, 8):
                identity = str(
                    (point.get("payload") or {}).get("parent_id") or point.get("id") or ""
                )
                if identity in seen or _metadata_only(point):
                    continue
                if _opening_hours_location_matches(point, location):
                    result.append(point)
                    seen.add(identity)
        return result

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


def _feedback_link(chat_id, message_id):
    """Bewusst einfache, von OpenWebUI stabil verarbeitete Portaladresse."""
    return (
        "[Wissensfehler melden]"
        f"(/wissen/?feedback=1&chat_id={chat_id}&message_id={message_id})"
    )
def _missing_rag_result(query, chat_id, message_id):
    evidence = _evidence_bundle(
        query,
        missing_information=[
            "Für die konkrete Anfrage liegt keine ausreichende freigegebene Evidenz vor."
        ],
    )
    return (
        "KAHLE_RAG_RESULT\nFOUND: false\n"
        f"{_evidence_bundle_line(evidence)}\n"
        "ANSWER: Dazu habe ich keine verlässliche freigegebene Information.\n"
        f"FEEDBACK_LINK: {_feedback_link(chat_id, message_id)}"
    )
def _hybrid_setting(primary, fallback=""):
    return os.environ.get(primary) or fallback
def _hybrid_embed(base_url, api_key, model, query, timeout):
    response = requests.post(
        f"{base_url.rstrip('/')}/embeddings",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": model, "input": query}, timeout=timeout,
    )
    response.raise_for_status()
    vector = response.json()["data"][0]["embedding"]
    if not vector:
        raise RetrievalError("dense_embedding_unavailable")
    return vector
def _hybrid_user_id(user):
    if not isinstance(user, dict):
        return ""
    return str(user.get("id") or (user.get("user") or {}).get("id") or "").strip()
def _sanitize_rag_query(query):
    """Remove an OpenWebUI answer prompt accidentally forwarded as query.

    Some native tool-capable models may repeat the complete synthesis prompt,
    including a previous ``<context>`` block, when they invoke rag_chat again.
    Retrieval must only see the user's actual question at the end. Normal
    queries are returned unchanged.
    """
    value = str(query or "").strip()
    if "KAHLE_RAG_RESULT" not in value or "</context>" not in value.lower():
        return value
    value = re.split(r"</context>", value, flags=re.IGNORECASE)[-1].strip()
    return re.sub(r"^query\s*[:=-]?\s*", "", value, flags=re.IGNORECASE).strip()
def _expand_kahle_query_aliases(query):
    """Expand unambiguous internal shorthand before every retrieval stage.

    Location codes intentionally remain case-sensitive: lowercase ``nie`` and
    ``neu`` are normal German words. This keeps natural questions unchanged
    while supporting the uppercase codes employees use in daily work.
    """
    value = str(query or "").strip()
    aliases = (
        ("TD", "Teiledienst"),
        ("VK", "Verkauf"),
        ("HAN", "Hannover"),
        ("WUN", "Wunstorf"),
        ("WED", "Wedemark"),
        ("WAL", "Walsrode"),
        ("NEU", "Neustadt am Rübenberge"),
        ("NIE", "Nienburg"),
        ("STA", "Stadthagen"),
        ("SHG", "Stadthagen"),
    )
    for alias, canonical in aliases:
        value = re.sub(
            rf"(?<![A-Za-z0-9])(?:LOC-)?{re.escape(alias)}(?![A-Za-z0-9])",
            canonical,
            value,
        )
    return value
def _clarification_for_query(query):
    """Ask for the required scope instead of returning an arbitrary long list."""
    value = str(query or "").strip().casefold()
    customer_lock = (
        re.search(r"\b(?:kunde|kunden)(?:\b|(?=sperr|entsperr))", value)
        and re.search(r"(?:\b(?:sperr|entsperr)\w*|\bkunden(?:sperr|entsperr)\w*)", value)
        and re.search(r"\b(?:vaudis|vaudisx|dse)\b", value)
    )
    marketing_scope = re.search(
        r"\b(?:werbung|werbewiderspruch|befragung(?:en)?|kontaktfreigabe(?:n)?|dse[- ]einstellung(?:en)?)\b",
        value,
    )
    general_scope = re.search(
        r"\b(?:allgemein(?:e|en|er)?|vollstaendig(?:e|en|er)?|vollständig(?:e|en|er)?|"
        r"verkaufssperre|auftragssperre|finanzsperre)\b",
        value,
    )
    if customer_lock and not marketing_scope and not general_scope:
        return (
            "Geht es darum, Werbung und Befragungen für den Kunden zu sperren, "
            "oder um eine allgemeine Kundensperre in Vaudis?"
        )
    if not re.search(r"\b(?:öffnungszeiten|oeffnungszeiten|öffnungszeit|oeffnungszeit)\b", value):
        return ""
    locations = (
        "hannover", "wunstorf", "neustadt", "rübenberge", "ruebenberge",
        "wedemark", "walsrode", "nienburg", "stadthagen",
    )
    if any(location in value for location in locations):
        return ""
    return (
        "Für welchen Standort und welchen Bereich (Verkauf, Service oder "
        "Teiledienst) brauchst du die Öffnungszeiten?"
    )
def _guided_response_for_query(query):
    """Return deterministic next steps for clarified high-risk internal intents.

    The actual marketing opt-out process remains source-driven through RAG.
    A general customer lock has deliberately no operational how-to in Vinci;
    the user must contact data protection with the two required facts.
    """
    value = str(query or "").strip().casefold()
    customer_lock = (
        re.search(r"\b(?:kunde|kunden)(?:\b|(?=sperr|entsperr))", value)
        and re.search(r"(?:\b(?:sperr|entsperr)\w*|\bkunden(?:sperr|entsperr)\w*)", value)
        and re.search(r"\b(?:vaudis|vaudisx|dse)\b", value)
    )
    general_scope = re.search(
        r"\b(?:allgemein(?:e|en|er)?|vollstaendig(?:e|en|er)?|vollständig(?:e|en|er)?|"
        r"verkaufssperre|auftragssperre|finanzsperre)\b",
        value,
    )
    if not customer_lock or not general_scope:
        return ""
    return (
        "Bitte wende dich mit der Kundennummer und dem Grund der gewünschten "
        "Sperre an [datenschutz@kahle.de](mailto:datenschutz@kahle.de?"
        "subject=Allgemeine%20Kundensperre%20in%20Vaudis&"
        "body=Kundennummer%3A%20%0AGrund%20der%20gew%C3%BCnschten%20Sperre%3A%20)."
    )
def _rag_answer_instruction(query):
    """Return query-specific grounding rules without replacing retrieval."""
    value = str(query or "").strip().casefold()
    marketing_scope = re.search(
        r"\b(?:werbung|werbesperre|werbewiderspruch|befragung(?:en)?|"
        r"kontaktfreigabe(?:n)?|dse[- ]einstellung(?:en)?)\b",
        value,
    )
    instruction = (
        "Antworte nur aus CONTEXT. Belege jede konkrete interne Aussage mit [Quelle N]. "
        "Bei Konflikt nicht stillschweigend entscheiden. "
    )
    if marketing_scope:
        instruction += (
            "Nutze ausschließlich einschlägige Textstellen zu Werbewiderspruch, Werbung, "
            "automatisierten Befragungen, DSE-Kontaktfreigaben und Sperrliste. "
            "Leite keine allgemeine Kundensperre und keine Felder, Register oder Datenkategorien "
            "aus anderen Vaudis-Handbuchtreffern ab. Nenne insbesondere besondere Merkmale oder "
            "Finanzdaten nur, wenn die einschlägige Quelle zum Werbewiderspruch dies ausdrücklich verlangt. "
        )
    return instruction
def _fold_evidence_text(value):
    return (
        str(value or "").casefold()
        .replace("ä", "ae").replace("ö", "oe")
        .replace("ü", "ue").replace("ß", "ss")
    )
def _procedural_evidence_intent(query):
    value = _fold_evidence_text(query)
    value = re.sub(
        r"\b(?:kein(?:e|en|er|es)?|ohne)\s+"
        r"(?:\w+\s+){0,2}"
        r"(?:anleitung|schritte?|ablaufschritte?|vorgehen|ablauf)\w*",
        "",
        value,
    )
    if any(marker in value for marker in ("anleitung", "schritt", "vorgehen", "ablauf")):
        return True
    return bool(
        re.search(
            r"\bwie\s+(?:"
            r"kann|muss|soll|darf|gehe|verfahre|funktioniert|laeuft|"
            r"bedien|nutz|verwend|richt|beantrag|aender|pfleg|meld|"
            r"fuehr|oeffn|waehl|trag|gib|erfass|speicher|bestaetig|"
            r"erstell|plan|buch|sperr"
            r")\w*\b",
            value,
        )
    )
def _context_has_procedure(context):
    value = _fold_evidence_text(context)
    patterns = (
        r"\bo?ffn\w*", r"\bnavigier\w*", r"\bklick\w*",
        r"\bwaehl\w*", r"\b(?:eingeb\w*|gib)\b", r"\berfass\w*",
        r"\bspeicher\w*", r"\bbestaetig\w*", r"\berstell\w*",
    )
    return sum(bool(re.search(pattern, value)) for pattern in patterns) >= 3
def _evidence_bundle(query, context="", sources=None, missing_information=None):
    source_items = list(sources or [])
    missing = list(missing_information or [])
    claims = []
    for source in source_items:
        number = source.get("number")
        claim = str(source.get("evidence_text") or "").strip()
        if number and claim:
            claims.append({"source_id": f"#{number}", "text": claim[:1000]})
    clean_sources = [
        {key: value for key, value in source.items() if key != "evidence_text"}
        for source in source_items
    ]
    conflicts = [
        f"#{source['number']}"
        for source in source_items
        if source.get("number") and source.get("conflict")
    ]
    if not source_items:
        status = "unsupported"
    else:
        status = "supported"
        if conflicts:
            status = "partially_supported"
            missing.append(
                "Die Quellen enthalten einen gekennzeichneten inhaltlichen Konflikt."
            )
        if _procedural_evidence_intent(query) and not _context_has_procedure(context):
            status = "partially_supported"
            missing.append(
                "Die Quellen bestätigen das Thema, enthalten aber keine ausreichende Anleitung."
            )
    return {
        "schema_version": "kahle.evidence-bundle.v1",
        "status": status,
        "supported_claims": claims,
        "missing_information": missing,
        "conflicts": conflicts,
        "sources": clean_sources,
    }
def _evidence_bundle_line(bundle):
    return "EVIDENCE_BUNDLE_JSON: " + json.dumps(bundle, ensure_ascii=False, separators=(",", ":"))
def _hybrid_record_event(portal_url, internal_key, user_id, query, found,
                         source_count, started_at, error_code=None):
    """Best-effort Betriebsmetrik ohne Fragetext oder Dokumentinhalt."""
    try:
        requests.post(
            f"{portal_url.rstrip('/')}/portal/internal/retrieval-events",
            headers={"X-API-Key": internal_key, "Content-Type": "application/json"},
            json={
                "user_id": user_id,
                "query_hash": hashlib.sha256(query.encode("utf-8")).hexdigest(),
                "found": bool(found),
                "source_count": int(source_count),
                "latency_ms": max(0, round((time.monotonic() - started_at) * 1000)),
                "error_code": error_code,
            },
            timeout=1,
        )
    except requests.RequestException:
        pass
class Tools:
    class Valves(BaseModel):
        PORTAL_API_URL: str = Field(default="http://kb-admin-api:8092")
        INTERNAL_API_KEY: str = Field(default="")
        KB_SYNC_URL: str = Field(default="http://kb-sync:8093")
        QDRANT_URL: str = Field(default="http://qdrant:6333")
        COLLECTION_ALIAS: str = Field(default="vinci_knowledge")
        IONOS_OPENAI_BASE_URL: str = Field(default="")
        IONOS_API_KEY: str = Field(default="")
        IONOS_EMBEDDING_MODEL: str = Field(default="")
        RERANKER_MODEL: str = Field(default="Qwen/Qwen3-VL-Reranker-8B")
        MINIMUM_RERANK_SCORE: float = Field(default=0.25, ge=0, le=1)
        TIMEOUT_S: int = Field(default=60)

    def __init__(self):
        self.valves = self.Valves()

    async def rag_chat(self, query: str = "", __user__: dict | None = None, __chat_id__: str = "", __message_id__: str = "") -> str:
        """Durchsucht ausschließlich freigegebenes Wissen, das der angemeldete Nutzer lesen darf."""
        query = _expand_kahle_query_aliases(_sanitize_rag_query(query))
        started_at = time.monotonic()
        user_id = _hybrid_user_id(__user__)
        internal_key = self.valves.INTERNAL_API_KEY or _hybrid_setting("KB_ADMIN_MAINTENANCE_API_KEY")
        api_key = self.valves.IONOS_API_KEY or _hybrid_setting("RAG_OPENAI_API_KEY", _hybrid_setting("OPENAI_API_KEY"))
        base_url = self.valves.IONOS_OPENAI_BASE_URL or _hybrid_setting(
            "RAG_OPENAI_API_BASE_URL", _hybrid_setting("OPENAI_API_BASE_URL", "https://openai.inference.de-txl.ionos.com/v1")
        )
        model = self.valves.IONOS_EMBEDDING_MODEL or _hybrid_setting("RAG_EMBEDDING_MODEL", "BAAI/bge-m3")
        clarification = _clarification_for_query(query)
        if clarification:
            evidence = _evidence_bundle(query, missing_information=[clarification])
            return (
                "KAHLE_RAG_RESULT\nFOUND: false\n"
                "CLARIFICATION_REQUIRED: true\n"
                f"{_evidence_bundle_line(evidence)}\n"
                f"ANSWER: {clarification}\n"
                f"FEEDBACK_LINK: {_feedback_link(__chat_id__, __message_id__)}"
            )
        guided_response = _guided_response_for_query(query)
        if guided_response:
            evidence = _evidence_bundle(
                query,
                missing_information=[
                    "Für eine operative Anleitung liegt keine freigegebene Evidenz vor."
                ],
            )
            return (
                "KAHLE_RAG_RESULT\nFOUND: true\n"
                "GUIDED_RESPONSE: true\n"
                f"{_evidence_bundle_line(evidence)}\n"
                f"ANSWER: {guided_response}\n"
                f"FEEDBACK_LINK: {_feedback_link(__chat_id__, __message_id__)}"
            )
        if not query or not user_id or not internal_key or not api_key:
            return _missing_rag_result(query, __chat_id__, __message_id__)
        try:
            scope = PortalScopeClient(self.valves.PORTAL_API_URL, internal_key).resolve(user_id)
            dense = _hybrid_embed(base_url, api_key, model, query, int(self.valves.TIMEOUT_S))
            retriever = QdrantHybridRetriever(
                self.valves.QDRANT_URL, self.valves.COLLECTION_ALIAS,
                RemoteSparseQueryEncoder(self.valves.KB_SYNC_URL, internal_key),
                IonosReranker(base_url, api_key, self.valves.RERANKER_MODEL),
                timeout=int(self.valves.TIMEOUT_S), minimum_rerank_score=self.valves.MINIMUM_RERANK_SCORE,
            )
            chunks = retriever.retrieve(query, dense, scope)
        except Exception as exc:
            error_code = (
                str(exc).strip()
                if isinstance(exc, RetrievalError) and str(exc).strip()
                else type(exc).__name__
            )
            _hybrid_record_event(self.valves.PORTAL_API_URL, internal_key, user_id, query,
                                 False, 0, started_at, error_code)
            return (
                "KAHLE_RAG_RESULT\nFOUND: false\n"
                f"{_evidence_bundle_line(_evidence_bundle(query, missing_information=[error_code]))}\n"
                "ANSWER: Dazu habe ich keine verlässliche freigegebene Information.\n"
                f"ERROR_CODE: {error_code}\n"
                f"FEEDBACK_LINK: {_feedback_link(__chat_id__, __message_id__)}"
            )
        if not chunks:
            _hybrid_record_event(self.valves.PORTAL_API_URL, internal_key, user_id, query,
                                 False, 0, started_at)
            return _missing_rag_result(query, __chat_id__, __message_id__)
        context, sources = [], []
        for index, chunk in enumerate(chunks, 1):
            heading = " > ".join(chunk.heading_path)
            context.append(f"[Quelle {index}] {chunk.title} | {heading}\n{chunk.parent_content}")
            sources.append({
                "number": index, "title": chunk.title, "document_id": chunk.document_id,
                "version_id": chunk.version_id, "valid_until": chunk.valid_until,
                "source_url": chunk.source_url, "conflict": chunk.conflict,
                "knowledgebase_ids": list(chunk.knowledgebase_ids),
                "evidence_text": chunk.parent_content,
            })
        joined_context = "\n\n".join(context)
        evidence = _evidence_bundle(query, joined_context, sources)
        _hybrid_record_event(self.valves.PORTAL_API_URL, internal_key, user_id, query,
                             True, len(sources), started_at)
        return (
            "KAHLE_RAG_RESULT\nFOUND: true\n"
            f"{_evidence_bundle_line(evidence)}\n"
            f"INSTRUCTION: {_rag_answer_instruction(query)}\n"
            f"CONTEXT:\n{joined_context}\n"
            f"SOURCES_JSON: {json.dumps(sources, ensure_ascii=False)}\n"
            f"FEEDBACK_LINK: {_feedback_link(__chat_id__, __message_id__)}"
        )
