import pytest

import offline_hybrid_eval as evaluation


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_tei_reranker_uses_fused_top_candidates_and_maps_scores(monkeypatch):
    captured = {}

    def post(url, *, json, timeout):
        captured.update(url=url, json=json, timeout=timeout)
        return Response([{"index": 1, "score": 0.9}, {"index": 0, "score": 0.4}])

    monkeypatch.setattr(evaluation.requests, "post", post)
    chunks = [{"content": "eins"}, {"content": "zwei"}, {"content": "drei"}]
    scores = evaluation.tei_rerank("Frage", chunks, [0.2, 0.8, 0.5], "http://reranker:80", candidate_limit=2)

    assert captured["url"] == "http://reranker:80/rerank"
    assert captured["json"]["texts"] == ["zwei", "drei"]
    assert scores == [float("-inf"), 0.4, 0.9]


def test_tei_reranker_fails_closed_when_service_returns_no_results(monkeypatch):
    monkeypatch.setattr(evaluation.requests, "post", lambda *args, **kwargs: Response([]))
    with pytest.raises(RuntimeError, match="required_reranker_unavailable"):
        evaluation.tei_rerank("Frage", [{"content": "eins"}], [1.0], "http://reranker:80")