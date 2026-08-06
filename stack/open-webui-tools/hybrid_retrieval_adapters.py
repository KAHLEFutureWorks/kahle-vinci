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
