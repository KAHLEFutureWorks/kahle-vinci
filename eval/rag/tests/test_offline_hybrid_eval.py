import pytest

import offline_hybrid_eval as evaluation


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_reranker_uses_fused_top_candidates_and_maps_scores(monkeypatch):
    captured = {}

    def post(url, *, headers, json, timeout):
        captured.update(url=url, headers=headers, json=json, timeout=timeout)
        return Response({"results": [{"index": 1, "relevance_score": 0.9},
                                     {"index": 0, "relevance_score": 0.4}]})

    monkeypatch.setattr(evaluation.requests, "post", post)
    chunks = [{"content": "eins"}, {"content": "zwei"}, {"content": "drei"}]
    scores = evaluation.rerank(
        "Frage", chunks, [0.2, 0.8, 0.5],
        "https://openai.inference.de-txl.ionos.com/v1", "token", "Qwen/Qwen3-VL-Reranker-8B",
        candidate_limit=2,
    )

    # Dieselbe Route und dasselbe Format wie IonosReranker in der Laufzeit.
    assert captured["url"] == "https://openai.inference.de-txl.ionos.com/v1/rerank"
    assert captured["headers"]["Authorization"] == "Bearer token"
    assert captured["json"]["documents"] == ["zwei", "drei"]
    assert captured["json"]["model"] == "Qwen/Qwen3-VL-Reranker-8B"
    assert scores == [float("-inf"), 0.4, 0.9]


def test_reranker_fails_closed_when_service_returns_no_results(monkeypatch):
    monkeypatch.setattr(evaluation.requests, "post", lambda *args, **kwargs: Response({"results": []}))
    with pytest.raises(RuntimeError, match="required_reranker_unavailable"):
        evaluation.rerank("Frage", [{"content": "eins"}], [1.0],
                          "https://openai.inference.de-txl.ionos.com/v1", "token", "modell")
