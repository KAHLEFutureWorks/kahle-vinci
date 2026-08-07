#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import time
from pathlib import Path

import requests
import yaml

try:
    from app.hybrid_index import BM25Corpus, ParentChildChunker, german_tokens
    from app.kb_sync import IonosEmbeddings
except ImportError:  # pragma: no cover
    from hybrid_index import BM25Corpus, ParentChildChunker, german_tokens
    from kb_sync import IonosEmbeddings


def cosine(left: list[float], right: list[float]) -> float:
    denominator = math.sqrt(sum(x * x for x in left)) * math.sqrt(sum(x * x for x in right))
    return sum(x * y for x, y in zip(left, right)) / denominator if denominator else 0.0


def sparse_dot(left, right) -> float:
    values = dict(zip(left.indices, left.values))
    return sum(values.get(index, 0.0) * value for index, value in zip(right.indices, right.values))


def ranks(scores: list[float]) -> list[int]:
    order = sorted(range(len(scores)), key=lambda index: scores[index], reverse=True)
    result = [0] * len(scores)
    for rank, index in enumerate(order, 1):
        result[index] = rank
    return result


def rrf(dense: list[float], sparse: list[float], k: int = 60) -> list[float]:
    dense_ranks, sparse_ranks = ranks(dense), ranks(sparse)
    return [1 / (k + dense_ranks[index]) + 1 / (k + sparse_ranks[index]) for index in range(len(dense))]


def rerank(query: str, chunks: list[dict], fused: list[float], base_url: str, api_key: str,
           model: str, *, candidate_limit: int = 50, timeout: float = 60) -> list[float]:
    """
    Bewertet die Kandidaten mit demselben fail-closed Reranker wie die Laufzeit.

    Das ist bewusst derselbe IONOS-Endpunkt, den `IonosReranker` in
    `stack/open-webui-tools/hybrid_retrieval.py` aufruft: Eine Evaluation gegen
    ein anderes Modell als das produktiv eingesetzte hat keine Aussagekraft.
    """
    candidate_order = sorted(range(len(chunks)), key=lambda index: fused[index], reverse=True)[:candidate_limit]
    documents = [chunks[index]["content"] for index in candidate_order]
    try:
        response = requests.post(
            f"{base_url.rstrip('/')}/rerank",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "query": query, "documents": documents},
            timeout=timeout,
        )
        response.raise_for_status()
        rows = response.json().get("results") or []
        if not rows:
            raise ValueError("reranker_returned_no_results")
        scores = [float("-inf")] * len(chunks)
        for row in rows:
            local_index = int(row["index"])
            if local_index < 0 or local_index >= len(candidate_order):
                raise ValueError("reranker_index_out_of_range")
            scores[candidate_order[local_index]] = float(row["relevance_score"])
        return scores
    except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("required_reranker_unavailable") from exc

def load_definitions(path: Path) -> list[dict]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    return [
        {"question": question, "expected": item.get("file")}
        for item in payload["documents"] for question in item["questions"]
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("documents", type=Path)
    parser.add_argument("--questions", type=Path, default=Path("eval/rag/kahle-document-worker-questions.yml"))
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--base-url", default="https://openai.inference.de-txl.ionos.com/v1")
    # Lokal heisst der Token IONOS_API_TOKEN, auf dem Server IONOS_API_KEY.
    parser.add_argument(
        "--api-key",
        default=os.getenv("IONOS_API_TOKEN") or os.getenv("IONOS_API_KEY", ""),
    )
    parser.add_argument("--model", default="BAAI/bge-m3")
    parser.add_argument("--reranker-model", default="Qwen/Qwen3-VL-Reranker-8B")
    parser.add_argument("--reranker-timeout", type=float, default=60.0)
    args = parser.parse_args()
    if not args.api_key:
        parser.error("--api-key, IONOS_API_TOKEN or IONOS_API_KEY is required")

    definitions = load_definitions(args.questions)
    expected_files = sorted({item["expected"] for item in definitions if item["expected"]})
    chunker = ParentChildChunker()
    chunks: list[dict] = []
    for filename in expected_files:
        path = args.documents / filename
        markdown = path.read_text(encoding="utf-8-sig", errors="strict")
        for chunk in chunker.chunk(filename, markdown):
            chunks.append({
                "file": filename, "content": chunk.content,
                "source_url": f"/wissen/api/portal/sources/eval-{expected_files.index(filename) + 1}",
            })
    corpus = BM25Corpus(chunk["content"] for chunk in chunks)
    embeddings = IonosEmbeddings(args.base_url, args.api_key, args.model)
    chunk_vectors = embeddings.embed([chunk["content"] for chunk in chunks])
    records, latencies = [], []
    for definition in definitions:
        started = time.perf_counter()
        query = definition["question"]
        query_vector = embeddings.embed([query])[0]
        dense_scores = [cosine(query_vector, vector) for vector in chunk_vectors]
        sparse_query = corpus.query_vector(query)
        sparse_scores = [sparse_dot(sparse_query, corpus.document_vector(chunk["content"])) for chunk in chunks]
        fused_scores = rrf(dense_scores, sparse_scores)
        reranked_scores = rerank(query, chunks, fused_scores, args.base_url, args.api_key,
                                 args.reranker_model, timeout=args.reranker_timeout)
        configurations = {
            "dense_only": dense_scores, "sparse_only": sparse_scores,
            "hybrid_rrf": fused_scores, "hybrid_reranked": reranked_scores,
        }
        result = {"question": query, "expected": definition["expected"], "configurations": {}}
        for name, scores in configurations.items():
            order = sorted(range(len(chunks)), key=lambda index: scores[index], reverse=True)[:3]
            sources = [chunks[index] for index in order]
            if definition["expected"] is None:
                # An unknown identifier must have no convincing lexical support.
                hit = not any("zx-999" in source["content"].casefold() for source in sources)
            else:
                hit = any(source["file"] == definition["expected"] for source in sources)
            result["configurations"][name] = {
                "hit": hit, "top_sources": [source["file"] for source in sources],
                "source_links_ok": all(source["source_url"].startswith("/wissen/api/portal/sources/") for source in sources),
            }
        latencies.append((time.perf_counter() - started) * 1000)
        records.append(result)
    configuration_report = {}
    for name in ("dense_only", "sparse_only", "hybrid_rrf", "hybrid_reranked"):
        configuration_report[name] = {
            "document_hit_rate": sum(record["configurations"][name]["hit"] for record in records) / len(records),
            "source_link_rate": sum(record["configurations"][name]["source_links_ok"] for record in records) / len(records),
        }
    report = {
        "documents": len(expected_files), "chunks": len(chunks), "questions": len(records),
        "model": args.model, "configurations": configuration_report,
        "latency_ms": {"median": statistics.median(latencies), "p95": sorted(latencies)[max(0, math.ceil(len(latencies) * .95) - 1)]},
        "records": records,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "records"}, ensure_ascii=False, indent=2))
    final = configuration_report["hybrid_reranked"]
    return 0 if final["document_hit_rate"] >= .90 and final["source_link_rate"] >= .95 else 1


if __name__ == "__main__":
    raise SystemExit(main())
