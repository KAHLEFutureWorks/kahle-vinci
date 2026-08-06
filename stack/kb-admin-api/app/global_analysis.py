from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Callable, Iterable, Protocol

import requests

try:
    from .portal_governance import SQLiteGovernanceStore
except ImportError:  # pragma: no cover
    from portal_governance import SQLiteGovernanceStore


class GlobalAnalysisError(ValueError):
    pass


@dataclass(frozen=True)
class ComparisonThresholds:
    very_high: float = 0.88
    medium: float = 0.65
    low: float = 0.35

    def __post_init__(self) -> None:
        if not 0 <= self.low < self.medium < self.very_high <= 1:
            raise GlobalAnalysisError("invalid_similarity_thresholds")


@dataclass(frozen=True)
class CorpusDocument:
    document_id: str
    version_id: str
    title: str
    markdown: str
    knowledgebase_ids: tuple[str, ...]
    status: str = "active"


@dataclass(frozen=True)
class GlobalMatch:
    document_id: str
    version_id: str
    title: str
    knowledgebase_ids: tuple[str, ...]
    level: str
    combined_score: float
    lexical_score: float
    semantic_score: float | None
    version_candidate: bool
    conflicting_passages: tuple[str, ...] = ()


@dataclass(frozen=True)
class GlobalAnalysisResult:
    normalized_sha256: str
    exact_document_id: str | None
    matches: tuple[GlobalMatch, ...]
    contradiction_document_ids: tuple[str, ...]


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class ContradictionProvider(Protocol):
    def compare(self, new_text: str, existing_text: str) -> tuple[str, ...]: ...


def normalize_markdown(markdown: str) -> str:
    value = re.sub(r"\A---\s*\n.*?\n---\s*\n", "", markdown, flags=re.S)
    value = re.sub(r"<!--.*?-->", " ", value, flags=re.S)
    value = re.sub(r"[`*_>#|\[\]()]", " ", value)
    value = value.casefold().replace("ß", "ss")
    value = re.sub(r"[^a-z0-9äöü€%.,:+/-]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def normalized_sha256(markdown: str) -> str:
    return hashlib.sha256(normalize_markdown(markdown).encode("utf-8")).hexdigest()


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9äöü][a-z0-9äöü+./%-]{1,}", normalize_markdown(text))


def _version_title_key(title: str) -> str:
    value = normalize_markdown(title)
    value = re.sub(r"\b(?:v(?:ersion)?\s*)?\d+(?:[._-]\d+)*\b", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def lexical_similarity(left: str, right: str) -> float:
    a, b = Counter(_tokens(left)), Counter(_tokens(right))
    if not a or not b:
        return 0.0
    weighted_jaccard = sum((a & b).values()) / sum((a | b).values())
    sequence = SequenceMatcher(None, normalize_markdown(left), normalize_markdown(right)).ratio()
    return round(0.7 * weighted_jaccard + 0.3 * sequence, 6)


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        raise GlobalAnalysisError("invalid_embedding_dimensions")
    denominator = math.sqrt(sum(x * x for x in left)) * math.sqrt(sum(x * x for x in right))
    if not denominator:
        return 0.0
    return max(0.0, min(1.0, sum(x * y for x, y in zip(left, right)) / denominator))


class IonosEmbeddingProvider:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 60):
        self.base_url, self.api_key, self.model, self.timeout = base_url.rstrip("/"), api_key, model, timeout

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            response = requests.post(
                f"{self.base_url}/embeddings",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "input": texts},
                timeout=self.timeout,
            )
            response.raise_for_status()
            rows = sorted(response.json()["data"], key=lambda row: row["index"])
            return [row["embedding"] for row in rows]
        except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
            raise GlobalAnalysisError("embedding_service_unavailable") from exc


class ConservativeContradictionDetector:
    """Local high-precision detector; ambiguous cases are left to the model/admin."""

    NEGATION = re.compile(r"\b(nicht|kein(?:e[rmns]?)?|niemals|unzulässig|verboten)\b", re.I)
    NUMBER = re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:%|€|eur|tage?|stunden?|km)?\b", re.I)

    def compare(self, new_text: str, existing_text: str) -> tuple[str, ...]:
        findings: list[str] = []
        new_sentences = self._sentences(new_text)
        old_sentences = self._sentences(existing_text)
        for new in new_sentences:
            best = max(old_sentences, key=lambda old: lexical_similarity(new, old), default="")
            if not best or lexical_similarity(new, best) < 0.50:
                continue
            if bool(self.NEGATION.search(new)) != bool(self.NEGATION.search(best)):
                findings.append(f"Negation unterscheidet sich: {new[:180]} ↔ {best[:180]}")
                continue
            new_numbers, old_numbers = set(self.NUMBER.findall(new)), set(self.NUMBER.findall(best))
            if new_numbers and old_numbers and new_numbers != old_numbers:
                findings.append(f"Zahlenwert unterscheidet sich: {new[:180]} ↔ {best[:180]}")
        return tuple(findings[:5])

    @staticmethod
    def _sentences(text: str) -> list[str]:
        return [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", text) if len(part.strip()) >= 20]


class GlobalCorpus:
    """Global review corpus. It intentionally has no user ACL filter."""

    def __init__(self, store: SQLiteGovernanceStore):
        self.store = store
        with self.store.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS global_analysis_corpus (
                    version_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    markdown TEXT NOT NULL,
                    normalized_sha256 TEXT NOT NULL,
                    knowledgebase_ids_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_global_analysis_hash
                    ON global_analysis_corpus(normalized_sha256);
                """
            )

    def upsert(self, document: CorpusDocument) -> None:
        with self.store.connect() as db:
            db.execute(
                """
                INSERT INTO global_analysis_corpus (
                    version_id, document_id, title, markdown, normalized_sha256,
                    knowledgebase_ids_json, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(version_id) DO UPDATE SET
                    title=excluded.title, markdown=excluded.markdown,
                    normalized_sha256=excluded.normalized_sha256,
                    knowledgebase_ids_json=excluded.knowledgebase_ids_json,
                    status=excluded.status, updated_at=CURRENT_TIMESTAMP
                """,
                (document.version_id, document.document_id, document.title, document.markdown,
                 normalized_sha256(document.markdown), json.dumps(document.knowledgebase_ids), document.status),
            )

    def documents(self, exclude_version_id: str | None = None) -> list[CorpusDocument]:
        query = "SELECT * FROM global_analysis_corpus WHERE status IN ('active','pending','superseded')"
        params: tuple[str, ...] = ()
        if exclude_version_id:
            query += " AND version_id <> ?"
            params = (exclude_version_id,)
        with self.store.connect() as db:
            rows = db.execute(query, params).fetchall()
        return [CorpusDocument(row["document_id"], row["version_id"], row["title"], row["markdown"],
                               tuple(json.loads(row["knowledgebase_ids_json"])), row["status"]) for row in rows]


class GlobalDocumentAnalyzer:
    def __init__(self, corpus: GlobalCorpus, embedding_provider: EmbeddingProvider | None = None,
                 contradiction_provider: ContradictionProvider | None = None,
                 thresholds: ComparisonThresholds | None = None):
        self.corpus = corpus
        self.embedding_provider = embedding_provider
        self.contradiction_provider = contradiction_provider or ConservativeContradictionDetector()
        self.thresholds = thresholds or ComparisonThresholds()

    def analyze(self, *, version_id: str, title: str, markdown: str) -> GlobalAnalysisResult:
        documents = self.corpus.documents(exclude_version_id=version_id)
        digest = normalized_sha256(markdown)
        exact = next((doc.document_id for doc in documents if normalized_sha256(doc.markdown) == digest), None)
        semantic: list[float | None] = [None] * len(documents)
        if documents and self.embedding_provider:
            vectors = self.embedding_provider.embed([markdown] + [doc.markdown for doc in documents])
            if len(vectors) != len(documents) + 1:
                raise GlobalAnalysisError("invalid_embedding_response")
            semantic = [cosine_similarity(vectors[0], vector) for vector in vectors[1:]]

        matches: list[GlobalMatch] = []
        contradictions: list[str] = []
        for doc, semantic_score in zip(documents, semantic):
            lexical = lexical_similarity(markdown, doc.markdown)
            combined = lexical if semantic_score is None else 0.45 * lexical + 0.55 * semantic_score
            level = self._level(combined)
            if level == "none" and doc.document_id != exact:
                continue
            conflicts = self.contradiction_provider.compare(markdown, doc.markdown) if combined >= self.thresholds.medium else ()
            if conflicts:
                contradictions.append(doc.document_id)
            title_score = lexical_similarity(_version_title_key(title), _version_title_key(doc.title))
            matches.append(GlobalMatch(
                doc.document_id, doc.version_id, doc.title, doc.knowledgebase_ids,
                "identical" if doc.document_id == exact else level, round(combined, 6), lexical,
                round(semantic_score, 6) if semantic_score is not None else None,
                title_score >= 0.75 and doc.document_id != exact, conflicts,
            ))
        matches.sort(key=lambda item: (item.level == "identical", item.combined_score), reverse=True)
        return GlobalAnalysisResult(digest, exact, tuple(matches), tuple(dict.fromkeys(contradictions)))

    def _level(self, score: float) -> str:
        if score >= self.thresholds.very_high:
            return "very_high"
        if score >= self.thresholds.medium:
            return "medium"
        if score >= self.thresholds.low:
            return "low"
        return "none"
