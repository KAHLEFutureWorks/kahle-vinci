#!/usr/bin/env python3
"""Connectivity check for the IONOS OpenAI-compatible API."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Any
from urllib import error, request


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def http_json(method: str, url: str, api_key: str, payload: dict[str, Any] | None = None, timeout: int = 60) -> tuple[int, Any]:
    data = None
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = request.Request(url=url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.getcode(), json.loads(raw) if raw else {}
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            body = {"error": "non-json response", "status": exc.code}
        return exc.code, body


def compact_error(body: Any) -> str:
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            message = err.get("message") or err.get("type") or err.get("code")
            if message:
                return str(message)
        if isinstance(err, str):
            return err
        detail = body.get("detail")
        if detail:
            return str(detail)
    return "request failed"


def check_models(base_url: str, api_key: str, timeout: int) -> CheckResult:
    status, body = http_json("GET", f"{base_url}/models", api_key, timeout=timeout)
    if status != 200:
        return CheckResult("models", False, f"HTTP {status}: {compact_error(body)}")
    count = len(body.get("data", [])) if isinstance(body, dict) else 0
    return CheckResult("models", True, f"HTTP 200, models listed: {count}")


def check_chat(base_url: str, api_key: str, model: str, timeout: int) -> CheckResult:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Answer with exactly: ok"},
            {"role": "user", "content": "Connectivity check. Reply with ok."},
        ],
        "temperature": 0,
        "max_tokens": 8,
    }
    status, body = http_json("POST", f"{base_url}/chat/completions", api_key, payload, timeout=timeout)
    if status != 200:
        return CheckResult(f"chat:{model}", False, f"HTTP {status}: {compact_error(body)}")
    try:
        content = str(body["choices"][0]["message"]["content"]).strip()
    except Exception:
        content = ""
    if not content:
        return CheckResult(f"chat:{model}", False, "HTTP 200 but no message content")
    return CheckResult(f"chat:{model}", True, "HTTP 200, response received")


def check_embeddings(base_url: str, api_key: str, model: str, timeout: int) -> CheckResult:
    payload = {
        "model": model,
        "input": "IONOS embedding connectivity check",
    }
    status, body = http_json("POST", f"{base_url}/embeddings", api_key, payload, timeout=timeout)
    if status != 200:
        return CheckResult(f"embeddings:{model}", False, f"HTTP {status}: {compact_error(body)}")
    try:
        vector = body["data"][0]["embedding"]
    except Exception:
        vector = []
    if not isinstance(vector, list) or not vector:
        return CheckResult(f"embeddings:{model}", False, "HTTP 200 but no embedding vector")
    return CheckResult(f"embeddings:{model}", True, f"HTTP 200, dimensions: {len(vector)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check IONOS OpenAI-compatible model hub connectivity")
    parser.add_argument("--base-url", default="https://openai.inference.de-txl.ionos.com/v1")
    parser.add_argument("--api-key-env", default="IONOS_API_KEY")
    parser.add_argument("--chat-model", default="mistralai/Mistral-Small-24B-Instruct")
    parser.add_argument("--reasoning-model", default="openai/gpt-oss-120b")
    parser.add_argument("--embedding-model", default="BAAI/bge-m3")
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()

    api_key = os.environ.get(args.api_key_env, "")
    if not api_key:
        print(f"ERROR: API key environment variable is not set: {args.api_key_env}", file=sys.stderr)
        return 2

    base_url = args.base_url.rstrip("/")
    checks = [
        check_models(base_url, api_key, args.timeout),
        check_chat(base_url, api_key, args.chat_model, args.timeout),
        check_chat(base_url, api_key, args.reasoning_model, args.timeout),
        check_embeddings(base_url, api_key, args.embedding_model, args.timeout),
    ]

    failures = 0
    for result in checks:
        state = "OK" if result.ok else "FAIL"
        print(f"{state}: {result.name}: {result.detail}")
        if not result.ok:
            failures += 1

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
