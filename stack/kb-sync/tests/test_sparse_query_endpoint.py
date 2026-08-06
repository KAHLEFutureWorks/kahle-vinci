import threading
from pathlib import Path
from types import SimpleNamespace

import requests

from app.bm25_snapshot import BM25Snapshot
from app.hybrid_index import BM25Corpus
from app.kb_sync import ReindexRequestHandler, ThreadingHTTPServer


def test_sparse_query_endpoint_requires_service_key_and_returns_build_bound_vector(tmp_path: Path):
    snapshot_path = tmp_path / "bm25.json"
    BM25Snapshot.from_corpus("build-1", BM25Corpus(["Aktion A1b", "Service Termin"])).save_atomic(snapshot_path)
    ReindexRequestHandler.sync_service = SimpleNamespace(config=SimpleNamespace(
        internal_api_key="secret", hybrid_snapshot_path=snapshot_path,
    ))
    server = ThreadingHTTPServer(("127.0.0.1", 0), ReindexRequestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        assert requests.post(f"{base}/hybrid/sparse-query", json={"query": "A1b"}).status_code == 401
        response = requests.post(
            f"{base}/hybrid/sparse-query", headers={"X-API-Key": "secret"}, json={"query": "A1b"}
        )
        assert response.status_code == 200
        assert response.json()["build_id"] == "build-1"
        assert response.json()["indices"]
    finally:
        server.shutdown()
        server.server_close()
