"""
title: RAG_Chat KAHLE (Qdrant)
author: local
version: 0.3.0
description: Durchsucht die internen KAHLE Knowledgebases direkt in Qdrant und gibt zitierbaren Kontext zurück.
"""

from pydantic import BaseModel, Field
import os
import requests


def _env(*names, default=""):
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return default


def _post_json(url, payload, headers=None, timeout=60):
    response = requests.post(url, headers=headers or {}, json=payload, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _embed_query(base_url, api_key, model, query, timeout):
    body = _post_json(
        f"{base_url.rstrip('/')}/embeddings",
        {"model": model, "input": query},
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        timeout=timeout,
    )
    vector = ((body.get("data") or [{}])[0]).get("embedding")
    if not isinstance(vector, list):
        raise ValueError("Embedding API returned no embedding vector")
    return vector


def _search_collection(qdrant_url, collection, vector, limit, timeout):
    body = _post_json(
        f"{qdrant_url.rstrip('/')}/collections/{collection}/points/search",
        {"vector": vector, "limit": limit, "with_payload": True, "with_vector": False},
        timeout=timeout,
    )
    results = body.get("result") or []
    normalized = []
    for item in results:
        payload = item.get("payload") or {}
        text = payload.get("text") or payload.get("content") or ""
        if not text:
            continue
        normalized.append(
            {
                "collection": payload.get("kb") or collection,
                "doc_id": payload.get("doc_id") or "",
                "source_path": payload.get("source_path") or "",
                "chunk_index": payload.get("chunk_index"),
                "score": float(item.get("score") or 0.0),
                "text": str(text),
            }
        )
    return normalized


def _build_context(chunks):
    parts = []
    for index, chunk in enumerate(chunks, start=1):
        header = (
            f"[#{index} | {chunk['collection']} | {chunk['source_path']} "
            f"| chunk {chunk['chunk_index']} | score {chunk['score']:.3f}]"
        )
        parts.append(f"{header}\n{chunk['text'][:1800]}".strip())
    return "\n\n".join(parts).strip()


class Tools:
    class Valves(BaseModel):
        QDRANT_URL: str = Field(
            default="http://qdrant:6333",
            description="Interne Qdrant URL aus dem Open-WebUI Docker-Netzwerk",
        )
        IONOS_OPENAI_BASE_URL: str = Field(
            default="",
            description="Optional. Leer nutzt RAG_OPENAI_API_BASE_URL/OPENAI_API_BASE_URL aus der Umgebung.",
        )
        IONOS_API_KEY: str = Field(
            default="",
            description="Optional. Leer nutzt RAG_OPENAI_API_KEY/OPENAI_API_KEY aus der Umgebung.",
        )
        IONOS_EMBEDDING_MODEL: str = Field(
            default="",
            description="Optional. Leer nutzt RAG_EMBEDDING_MODEL oder BAAI/bge-m3.",
        )
        COLLECTIONS_CSV: str = Field(
            default="kahleallgemein,kahlekontext,kahlerichtlinien",
            description="Kommagetrennte Qdrant Collections, die durchsucht werden.",
        )
        ANSWER_THRESHOLD: float = Field(default=0.45, description="Mindestscore für FOUND true.")
        MAX_CHUNKS: int = Field(default=6, description="Maximale Anzahl Kontext-Chunks.")
        TIMEOUT_S: int = Field(default=60, description="HTTP Timeout in Sekunden.")

    def __init__(self):
        self.valves = self.Valves()

    async def rag_chat(self, query: str = "", __messages__: list[dict] | None = None) -> str:
        """
        Suche in den internen KAHLE Knowledgebases.
        Verwende dieses Tool immer, wenn die Nutzerfrage interne KAHLE-Informationen,
        Standorte, Marken, Prozesse, Richtlinien, Angebote, Personen, Kultur,
        Unternehmenswissen oder gespeicherte Knowledgebase-Inhalte betrifft.
        """
        query = str(query or "").strip()
        if not query and isinstance(__messages__, list):
            for message in reversed(__messages__):
                if not isinstance(message, dict):
                    continue
                if message.get("role") != "user":
                    continue
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    query = content.strip()
                    break
        if not query:
            return (
                "KAHLE_RAG_RESULT\n"
                "FOUND: false\n"
                "ERROR: Der Toolcall enthielt keinen query-Parameter und es konnte keine letzte User-Nachricht gelesen werden.\n"
                "INSTRUCTION: Rufe rag_chat erneut auf und setze query auf die letzte Nutzerfrage."
            )

        base_url = self.valves.IONOS_OPENAI_BASE_URL or _env(
            "RAG_OPENAI_API_BASE_URL",
            "OPENAI_API_BASE_URL",
            default="https://openai.inference.de-txl.ionos.com/v1",
        )
        api_key = self.valves.IONOS_API_KEY or _env("RAG_OPENAI_API_KEY", "OPENAI_API_KEY")
        model = self.valves.IONOS_EMBEDDING_MODEL or _env("RAG_EMBEDDING_MODEL", default="BAAI/bge-m3")
        qdrant_url = self.valves.QDRANT_URL or _env("QDRANT_URI", default="http://qdrant:6333")
        timeout = int(self.valves.TIMEOUT_S)

        if not api_key:
            return "KAHLE_RAG_RESULT\nFOUND: false\nERROR: IONOS API Key fehlt im Tool oder in der Container-Umgebung."

        collections = [c.strip() for c in self.valves.COLLECTIONS_CSV.split(",") if c.strip()]
        if not collections:
            return "KAHLE_RAG_RESULT\nFOUND: false\nERROR: Keine Qdrant Collections konfiguriert."

        try:
            vector = _embed_query(base_url, api_key, model, query, timeout)
            all_chunks = []
            per_collection_limit = max(int(self.valves.MAX_CHUNKS), 3)
            for collection in collections:
                all_chunks.extend(_search_collection(qdrant_url, collection, vector, per_collection_limit, timeout))
        except Exception as exc:
            return f"KAHLE_RAG_RESULT\nFOUND: false\nERROR: {exc}"

        all_chunks.sort(key=lambda item: item["score"], reverse=True)
        top_chunks = all_chunks[: int(self.valves.MAX_CHUNKS)]
        top_score = top_chunks[0]["score"] if top_chunks else 0.0
        threshold = float(self.valves.ANSWER_THRESHOLD)

        if not top_chunks or top_score < threshold:
            return (
                "KAHLE_RAG_RESULT\n"
                "FOUND: false\n"
                f"QUERY: {query}\n"
                "INSTRUCTION: Keine passenden internen Treffer. Antworte exakt: "
                "'Dazu habe ich keine internen Infos.'\n"
                f"META: top1_score={top_score:.3f} threshold={threshold:.2f}"
            )

        return (
            "KAHLE_RAG_RESULT\n"
            "FOUND: true\n"
            f"QUERY: {query}\n"
            "INSTRUCTION: Nutze AUSSCHLIESSLICH den Kontext unten. "
            "Keine Vermutungen oder Ergänzungen. Jede KAHLE-Aussage muss eine Quellenmarke [#] enthalten.\n"
            f"META: top1_score={top_score:.3f} threshold={threshold:.2f} model={model}\n\n"
            "KONTEXT (zitierbar mit [#]):\n"
            f"{_build_context(top_chunks)}"
        )
