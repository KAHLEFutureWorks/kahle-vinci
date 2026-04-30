#!/usr/bin/env python3
"""Static checks for the versioned n8n workflow exports."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


IONOS_BASE_URL = "https://openai.inference.de-txl.ionos.com/v1"
CHAT_MODEL = "mistralai/Mistral-Small-24B-Instruct"
EMBEDDING_MODEL = "BAAI/bge-m3"

FORBIDDEN_PATTERNS = (
    re.compile(r"ollama:11434", re.IGNORECASE),
    re.compile(r"lmChatOllama", re.IGNORECASE),
    re.compile(r"embeddingsOllama", re.IGNORECASE),
    re.compile(r"embeddinggemma", re.IGNORECASE),
)


def load_workflows(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("workflow export must be a JSON array")
    return data


def iter_nodes(workflows: list[dict[str, Any]]):
    for workflow in workflows:
        for node in workflow.get("nodes") or []:
            if isinstance(node, dict):
                yield workflow, node


def check_connections(workflows: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    for workflow in workflows:
        name = workflow.get("name", "<unnamed>")
        connections = workflow.get("connections") or {}
        if not isinstance(connections, dict):
            failures.append(f"{name}: connections must be an object")
            continue
        for source, groups in connections.items():
            if not isinstance(groups, dict):
                failures.append(f"{name}/{source}: connection groups must be an object")
                continue
            for output_type, outputs in groups.items():
                if not isinstance(outputs, list):
                    failures.append(f"{name}/{source}/{output_type}: outputs must be an array")
                    continue
                for index, output_connections in enumerate(outputs):
                    if not isinstance(output_connections, list):
                        failures.append(
                            f"{name}/{source}/{output_type}[{index}]: must be an array of connection objects"
                        )
    return failures


def get_header_params(node: dict[str, Any]) -> Any:
    params = node.get("parameters") or {}
    header_params = params.get("headerParameters") or {}
    return header_params.get("parameters")


def check_ionos_http_nodes(workflows: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    for workflow, node in iter_nodes(workflows):
        params = node.get("parameters") or {}
        url = str(params.get("url") or "")
        if IONOS_BASE_URL not in url:
            continue

        header_params = get_header_params(node)
        if not isinstance(header_params, list):
            failures.append(f"{workflow.get('name')}/{node.get('name')}: headerParameters.parameters must be a list")
            continue

        auth_values = [
            str(item.get("value") or "")
            for item in header_params
            if isinstance(item, dict) and str(item.get("name") or "").lower() == "authorization"
        ]
        if not any("Bearer" in value and "$env.IONOS_API_KEY" in value for value in auth_values):
            failures.append(f"{workflow.get('name')}/{node.get('name')}: missing IONOS bearer Authorization header")
    return failures


def check_langchain_openai_nodes(workflows: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    for workflow, node in iter_nodes(workflows):
        node_type = str(node.get("type") or "")
        if "lmChatOpenAi" not in node_type and "embeddingsOpenAi" not in node_type:
            continue

        name = f"{workflow.get('name')}/{node.get('name')}"
        params = node.get("parameters") or {}
        options = params.get("options") or {}
        credentials = node.get("credentials") or {}

        if not isinstance(options, dict) or options.get("baseURL") != IONOS_BASE_URL:
            failures.append(f"{name}: missing IONOS options.baseURL")
        if "openAiApi" not in credentials:
            failures.append(f"{name}: missing openAiApi credentials reference")

        model = params.get("model")
        if "embeddingsOpenAi" in node_type and model != EMBEDDING_MODEL:
            failures.append(f"{name}: embedding model must be {EMBEDDING_MODEL}")
        if "lmChatOpenAi" in node_type and model not in {CHAT_MODEL, None}:
            failures.append(f"{name}: unexpected chat model {model!r}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Static checks for n8n workflow exports")
    parser.add_argument("--workflow-file", default="n8n/all-workflows.json")
    args = parser.parse_args()

    path = Path(args.workflow_file)
    if not path.exists():
        print(f"ERROR: workflow file not found: {path}", file=sys.stderr)
        return 2

    text = path.read_text(encoding="utf-8")
    failures = [
        f"forbidden legacy pattern present: {pattern.pattern}"
        for pattern in FORBIDDEN_PATTERNS
        if pattern.search(text)
    ]

    try:
        workflows = load_workflows(path)
    except Exception as exc:
        print(f"ERROR: could not parse workflow file: {exc}", file=sys.stderr)
        return 2

    failures.extend(check_connections(workflows))
    failures.extend(check_ionos_http_nodes(workflows))
    failures.extend(check_langchain_openai_nodes(workflows))

    if failures:
        print("n8n workflow static check failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("n8n workflow static check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
