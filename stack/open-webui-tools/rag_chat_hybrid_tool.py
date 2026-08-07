"""title: RAG Chat KAHLE Hybrid
version: 1.0.0
description: Berechtigungsgefilterte Dense+BM25-Suche mit RRF, Reranking und Quellen.
"""
# ACHTUNG: Diese Datei ist NICHT in OpenWebUI installierbar.
# Sie verweist auf Klassen aus hybrid_retrieval.py und laeuft allein mit
# NameError. Installiere die gebaute Fassung aus dist/ desselben Namens:
#     python stack/open-webui-tools/build_tools.py
#     -> stack/open-webui-tools/dist/<diese Datei>

import json
import os
import requests
from pydantic import BaseModel, Field


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
        TIMEOUT_S: int = Field(default=60)

    def __init__(self):
        self.valves = self.Valves()

    async def rag_chat(self, query: str = "", __user__: dict | None = None, __chat_id__: str = "", __message_id__: str = "") -> str:
        """Durchsucht ausschließlich freigegebenes Wissen, das der angemeldete Nutzer lesen darf."""
        query = str(query or "").strip()
        user_id = _hybrid_user_id(__user__)
        internal_key = self.valves.INTERNAL_API_KEY or _hybrid_setting("KB_ADMIN_MAINTENANCE_API_KEY")
        api_key = self.valves.IONOS_API_KEY or _hybrid_setting("RAG_OPENAI_API_KEY", _hybrid_setting("OPENAI_API_KEY"))
        base_url = self.valves.IONOS_OPENAI_BASE_URL or _hybrid_setting(
            "RAG_OPENAI_API_BASE_URL", _hybrid_setting("OPENAI_API_BASE_URL", "https://openai.inference.de-txl.ionos.com/v1")
        )
        model = self.valves.IONOS_EMBEDDING_MODEL or _hybrid_setting("RAG_EMBEDDING_MODEL", "BAAI/bge-m3")
        if not query or not user_id or not internal_key or not api_key:
            return "KAHLE_RAG_RESULT\nFOUND: false\nANSWER: Dazu habe ich keine verlässliche freigegebene Information."
        try:
            scope = PortalScopeClient(self.valves.PORTAL_API_URL, internal_key).resolve(user_id)
            dense = _hybrid_embed(base_url, api_key, model, query, int(self.valves.TIMEOUT_S))
            retriever = QdrantHybridRetriever(
                self.valves.QDRANT_URL, self.valves.COLLECTION_ALIAS,
                RemoteSparseQueryEncoder(self.valves.KB_SYNC_URL, internal_key),
                IonosReranker(base_url, api_key, self.valves.RERANKER_MODEL),
                timeout=int(self.valves.TIMEOUT_S),
            )
            chunks = retriever.retrieve(query, dense, scope)
        except Exception as exc:
            return (
                "KAHLE_RAG_RESULT\nFOUND: false\n"
                "ANSWER: Dazu habe ich keine verlässliche freigegebene Information.\n"
                f"ERROR_CODE: {type(exc).__name__}"
            )
        if not chunks:
            return "KAHLE_RAG_RESULT\nFOUND: false\nANSWER: Dazu habe ich keine verlässliche freigegebene Information."
        context, sources = [], []
        for index, chunk in enumerate(chunks, 1):
            heading = " > ".join(chunk.heading_path)
            context.append(f"[Quelle {index}] {chunk.title} | {heading}\n{chunk.parent_content}")
            sources.append({
                "number": index, "title": chunk.title, "document_id": chunk.document_id,
                "version_id": chunk.version_id, "valid_until": chunk.valid_until,
                "source_url": chunk.source_url, "conflict": chunk.conflict,
            })
        joined_context = "\n\n".join(context)
        return (
            "KAHLE_RAG_RESULT\nFOUND: true\n"
            "INSTRUCTION: Antworte nur aus CONTEXT. Belege jede konkrete interne Aussage mit [Quelle N]. "
            "Bei Konflikt nicht stillschweigend entscheiden.\n"
            f"CONTEXT:\n{joined_context}\n"
            f"SOURCES_JSON: {json.dumps(sources, ensure_ascii=False)}\n"
            f"FEEDBACK_LINK: [Wissensfehler melden](/wissen/?feedback=1&chat_id={__chat_id__}&message_id={__message_id__})"
        )
