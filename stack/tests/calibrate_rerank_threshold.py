#!/usr/bin/env python3
"""Inspect IONOS rerank scores for unique parents in the active Qdrant alias."""
from __future__ import annotations

import argparse
import os

import requests


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    parser.add_argument("--alias", default="vinci_knowledge")
    parser.add_argument("--ionos-url", default="https://openai.inference.de-txl.ionos.com/v1")
    parser.add_argument("--model", default="Qwen/Qwen3-VL-Reranker-8B")
    args = parser.parse_args()
    api_key = os.environ.get("IONOS_API_TOKEN") or os.environ.get("IONOS_API_KEY")
    if not api_key:
        raise SystemExit("IONOS_API_TOKEN or IONOS_API_KEY is required")

    aliases = requests.get(f"{args.qdrant_url}/aliases", timeout=30).json()["result"]["aliases"]
    collection = next(item["collection_name"] for item in aliases if item["alias_name"] == args.alias)
    payload = requests.post(
        f"{args.qdrant_url}/collections/{collection}/points/scroll",
        json={"limit": 10_000, "with_payload": True, "with_vector": False},
        timeout=30,
    ).json()["result"]["points"]
    parents = {}
    for point in payload:
        row = point["payload"]
        parents.setdefault(row["parent_id"], row)
    rows = list(parents.values())
    response = requests.post(
        f"{args.ionos_url.rstrip('/')}/rerank",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": args.model,
            "query": args.query,
            "documents": [row["parent_content"] for row in rows],
            "top_n": len(rows),
        },
        timeout=120,
    )
    response.raise_for_status()
    for result in response.json().get("results", []):
        row = rows[int(result["index"])]
        score = float(result.get("relevance_score", result.get("score", 0)))
        print(f"{score:.6f}\t{' > '.join(row.get('heading_path') or [])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
