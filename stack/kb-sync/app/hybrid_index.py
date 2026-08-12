from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable


GERMAN_STOPWORDS = {
    "aber", "alle", "als", "am", "an", "auch", "auf", "aus", "bei", "bis", "da", "das",
    "dass", "dem", "den", "der", "des", "die", "durch", "ein", "eine", "einer", "eines",
    "er", "es", "für", "hat", "im", "in", "ist", "mit", "nach", "nicht", "oder", "sich",
    "sie", "sind", "so", "welche", "welcher", "welches", "gilt", "gelten", "über", "um", "und", "von", "vor", "wie", "wir", "zu", "zum", "zur",
}


def german_tokens(text: str) -> list[str]:
    value = (text or "").casefold().replace("ß", "ss")
    tokens = re.findall(r"[a-zäöü0-9][a-zäöü0-9+./_-]{1,}", value)
    return [token for token in tokens if token not in GERMAN_STOPWORDS]


def stable_term_index(token: str) -> int:
    # Qdrant sparse indices are uint32; reserve the sign bit for broad client compatibility.
    return int.from_bytes(hashlib.blake2s(token.encode("utf-8"), digest_size=4).digest(), "big") & 0x7FFFFFFF


@dataclass(frozen=True)
class SparseVector:
    indices: tuple[int, ...]
    values: tuple[float, ...]

    def qdrant(self) -> dict[str, list[float] | list[int]]:
        return {"indices": list(self.indices), "values": list(self.values)}


class BM25Corpus:
    def __init__(self, documents: Iterable[str], *, k1: float = 1.2, b: float = 0.75,
                 average_length: float | None = None):
        tokenized = [german_tokens(document) for document in documents]
        self.document_count = len(tokenized)
        measured_average = sum(map(len, tokenized)) / self.document_count if self.document_count else 1.0
        self.average_length = average_length or measured_average
        self.document_frequency: Counter[str] = Counter()
        for tokens in tokenized:
            self.document_frequency.update(set(tokens))
        self.k1, self.b = k1, b

    def document_vector(self, text: str) -> SparseVector:
        tokens = german_tokens(text)
        frequencies = Counter(tokens)
        length = max(len(tokens), 1)
        weights = {
            token: (frequency * (self.k1 + 1)) /
            (frequency + self.k1 * (1 - self.b + self.b * length / self.average_length))
            for token, frequency in frequencies.items()
        }
        return self._vector(weights)

    def query_vector(self, query: str) -> SparseVector:
        # Qdrant's IDF modifier maintains corpus statistics as points are added
        # and removed. Query vectors therefore carry term frequency only.
        weights = {token: 1.0 for token in set(german_tokens(query))}
        return self._vector(weights)

    @staticmethod
    def _vector(weights: dict[str, float]) -> SparseVector:
        # Hash collisions are summed deterministically instead of emitting duplicate indices.
        by_index: dict[int, float] = {}
        for token, value in weights.items():
            index = stable_term_index(token)
            by_index[index] = by_index.get(index, 0.0) + value
        items = sorted(by_index.items())
        return SparseVector(tuple(index for index, _ in items), tuple(round(value, 8) for _, value in items))


@dataclass(frozen=True)
class ChildChunk:
    child_id: str
    parent_id: str
    order: int
    heading_path: tuple[str, ...]
    content: str
    parent_content: str
    kind: str


class ParentChildChunker:
    """Markdown-aware chunking that keeps sections and table rows auditable."""

    HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
    TABLE_SEPARATOR = re.compile(r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$")

    def __init__(self, child_max_chars: int = 900, parent_max_chars: int = 5000):
        if child_max_chars < 200 or parent_max_chars < child_max_chars:
            raise ValueError("invalid_chunk_sizes")
        self.child_max_chars, self.parent_max_chars = child_max_chars, parent_max_chars

    def chunk(self, document_id: str, markdown: str) -> list[ChildChunk]:
        sections = self._sections(self._without_frontmatter(markdown))
        chunks: list[ChildChunk] = []
        order = 0
        for section_index, (heading_path, body) in enumerate(sections):
            parent_id = f"{document_id}:p{section_index}"
            for part, kind in self._children(body):
                chunks.append(ChildChunk(
                    child_id=f"{parent_id}:c{order}", parent_id=parent_id, order=order,
                    heading_path=heading_path, content=part,
                    parent_content=body[: self.parent_max_chars], kind=kind,
                ))
                order += 1
        return chunks

    @staticmethod
    def _without_frontmatter(markdown: str) -> str:
        clean = (markdown or "").lstrip("\ufeff")
        if not clean.startswith("---"):
            return clean
        match = re.match(r"\A---[ \t]*\n.*?\n---[ \t]*(?:\n|\Z)", clean, flags=re.S)
        return clean[match.end():] if match else clean

    def _sections(self, markdown: str) -> list[tuple[tuple[str, ...], str]]:
        headings: list[str] = []
        current: list[str] = []
        result: list[tuple[tuple[str, ...], str]] = []

        def flush() -> None:
            body = "\n".join(current).strip()
            if body:
                result.append((tuple(headings), body))

        for line in (markdown or "").replace("\r\n", "\n").split("\n"):
            match = self.HEADING.match(line)
            if match:
                flush()
                current.clear()
                level, title = len(match.group(1)), match.group(2).strip()
                headings[:] = headings[: level - 1]
                headings.append(title)
            else:
                current.append(line)
        flush()
        return result or [((), (markdown or "").strip())]

    def _children(self, body: str) -> list[tuple[str, str]]:
        blocks = [block.strip() for block in re.split(r"\n\s*\n", body) if block.strip()]
        result: list[tuple[str, str]] = []
        buffer = ""
        for block in blocks:
            if self._is_table(block):
                if buffer:
                    result.extend((part, "text") for part in self._split_text(buffer))
                    buffer = ""
                result.extend((part, "table") for part in self._split_table(block))
                continue
            candidate = f"{buffer}\n\n{block}".strip() if buffer else block
            if len(candidate) <= self.child_max_chars:
                buffer = candidate
            else:
                if buffer:
                    result.extend((part, "text") for part in self._split_text(buffer))
                buffer = block
        if buffer:
            result.extend((part, "text") for part in self._split_text(buffer))
        return result

    def _split_text(self, text: str) -> list[str]:
        if len(text) <= self.child_max_chars:
            return [text]
        sentences = re.split(r"(?<=[.!?])\s+|\n", text)
        chunks: list[str] = []
        current = ""
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            if len(sentence) > self.child_max_chars:
                if current:
                    chunks.append(current)
                    current = ""
                chunks.extend(sentence[i:i + self.child_max_chars] for i in range(0, len(sentence), self.child_max_chars))
            elif not current or len(current) + len(sentence) + 1 <= self.child_max_chars:
                current = f"{current} {sentence}".strip()
            else:
                chunks.append(current)
                current = sentence
        if current:
            chunks.append(current)
        return chunks

    def _split_table(self, table: str) -> list[str]:
        lines = [line.strip() for line in table.splitlines() if line.strip()]
        if len(lines) < 2:
            return self._split_text(table)
        header = lines[:2] if self.TABLE_SEPARATOR.match(lines[1]) else lines[:1]
        rows = lines[len(header):]
        result: list[str] = []
        for row in rows or [""]:
            value = "\n".join(header + ([row] if row else []))
            if len(value) <= self.child_max_chars:
                result.append(value)
            else:
                # Retain header for every continuation so column meaning is never lost.
                available = max(50, self.child_max_chars - len("\n".join(header)) - 1)
                result.extend("\n".join(header + [row[i:i + available]]) for i in range(0, len(row), available))
        return result

    @staticmethod
    def _is_table(block: str) -> bool:
        lines = block.splitlines()
        return len(lines) >= 2 and "|" in lines[0] and "|" in lines[1]
