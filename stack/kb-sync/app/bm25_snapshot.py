from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from .hybrid_index import BM25Corpus, german_tokens, stable_term_index
except ImportError:  # pragma: no cover
    from hybrid_index import BM25Corpus, german_tokens, stable_term_index


@dataclass(frozen=True)
class BM25Snapshot:
    build_id: str
    document_count: int
    document_frequency: dict[str, int]

    @classmethod
    def from_corpus(cls, build_id: str, corpus: BM25Corpus) -> "BM25Snapshot":
        return cls(build_id, corpus.document_count, dict(corpus.document_frequency))

    def encode_query(self, query: str) -> dict[str, Any]:
        by_index: dict[int, float] = {}
        for token in set(german_tokens(query)):
            frequency = self.document_frequency.get(token, 0)
            value = math.log(1 + (self.document_count - frequency + 0.5) / (frequency + 0.5))
            index = stable_term_index(token)
            by_index[index] = by_index.get(index, 0.0) + value
        items = sorted(by_index.items())
        return {
            "build_id": self.build_id,
            "indices": [index for index, _ in items],
            "values": [round(value, 8) for _, value in items],
        }

    def save_atomic(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(self.__dict__, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        os.replace(temporary, path)

    @classmethod
    def load(cls, path: Path) -> "BM25Snapshot":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(str(payload["build_id"]), int(payload["document_count"]), {
            str(key): int(value) for key, value in payload["document_frequency"].items()
        })
