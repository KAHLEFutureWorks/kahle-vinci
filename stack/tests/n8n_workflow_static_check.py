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

        name = f"{workflow.get('name')}/{node.get('name')}"
        credentials = node.get("credentials") or {}
        if params.get("authentication") != "predefinedCredentialType":
            failures.append(f"{name}: must use predefinedCredentialType auth")
        if params.get("nodeCredentialType") != "openAiApi":
            failures.append(f"{name}: must use openAiApi credentials")
        if "openAiApi" not in credentials:
            failures.append(f"{name}: missing openAiApi credentials reference")
        if "$env.IONOS_API_KEY" in json.dumps(params):
            failures.append(f"{name}: must not read IONOS_API_KEY via node env expression")
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


def check_conditions_shape(workflows: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    for workflow, node in iter_nodes(workflows):
        node_type = node.get("type")
        params = node.get("parameters") or {}

        if node_type == "n8n-nodes-base.if":
            conditions = (params.get("conditions") or {}).get("conditions")
            if not isinstance(conditions, list):
                failures.append(f"{workflow.get('name')}/{node.get('name')}: conditions.conditions must be a list")

        if node_type == "n8n-nodes-base.switch":
            rules = params.get("rules") or {}
            values = rules.get("values") or []
            for index, rule in enumerate(values):
                conditions = (rule.get("conditions") or {}).get("conditions")
                if not isinstance(conditions, list):
                    failures.append(
                        f"{workflow.get('name')}/{node.get('name')} rule {index}: "
                        "conditions.conditions must be a list"
                    )
    return failures


def find_custom_regex(workflows: list[dict[str, Any]], workflow_name: str, node_name: str, regex_name: str) -> str | None:
    for workflow, node in iter_nodes(workflows):
        if workflow.get("name") != workflow_name or node.get("name") != node_name:
            continue
        regexes = (
            ((node.get("parameters") or {}).get("guardrails") or {})
            .get("customRegex", {})
            .get("regex", [])
        )
        for item in regexes:
            if isinstance(item, dict) and item.get("name") == regex_name:
                value = item.get("value")
                return str(value) if value is not None else None
    return None


def check_safe_websearch_input_gate_regex(workflows: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    pattern = find_custom_regex(
        workflows,
        workflow_name="Hybrid-Safe Websearcher",
        node_name="Input Gate",
        regex_name="LICENSE_PLATE_DE_GOV",
    )
    if not pattern:
        return ["Hybrid-Safe Websearcher/Input Gate: missing LICENSE_PLATE_DE_GOV regex"]

    compiled = re.compile(pattern)
    false_positive = "Bitte suche Nachrichten vom 04.05.2026"
    if compiled.search(false_positive):
        failures.append("Hybrid-Safe Websearcher/Input Gate: LICENSE_PLATE_DE_GOV must not match dates like 04.05.2026")

    for valid_plate in ("BD 1234", "BP-AB 123", "POL 12345", "0-1234"):
        if not compiled.search(valid_plate):
            failures.append(
                "Hybrid-Safe Websearcher/Input Gate: "
                f"LICENSE_PLATE_DE_GOV should still match {valid_plate!r}"
            )

    return failures


def check_safe_websearch_research_context_quality(workflows: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    workflow = next((wf for wf in workflows if wf.get("name") == "Hybrid-Safe Websearcher"), None)
    if not workflow:
        return ["Hybrid-Safe Websearcher: workflow missing"]

    nodes = workflow.get("nodes") or []
    content_node = next((node for node in nodes if node.get("name") == "Build Rich Research Context"), None)
    if not content_node:
        failures.append("Hybrid-Safe Websearcher: missing Build Rich Research Context node")
        return failures

    code = str((content_node.get("parameters") or {}).get("jsCode") or "")
    required_terms = ("fetchTopPages", "extractArticleText", "researchContext", "keyFindings")
    for term in required_terms:
        if term not in code:
            failures.append(f"Hybrid-Safe Websearcher/Build Rich Research Context: missing {term}")
    if "this.helpers.httpRequest" not in code:
        failures.append(
            "Hybrid-Safe Websearcher/Build Rich Research Context: "
            "must use n8n's this.helpers.httpRequest for page fetches"
        )
    if "AbortController" in code:
        failures.append(
            "Hybrid-Safe Websearcher/Build Rich Research Context: "
            "must not use AbortController because n8n Code node task runners do not expose it"
        )
    if "fetch(" in code:
        failures.append(
            "Hybrid-Safe Websearcher/Build Rich Research Context: "
            "must not use global fetch because n8n Code node task runners do not expose it"
        )

    connections = workflow.get("connections") or {}
    searx_targets = [
        target.get("node")
        for group in ((connections.get("SearXNG Search") or {}).get("main") or [])
        for target in group
        if isinstance(target, dict)
    ]
    if "Build Rich Research Context" not in searx_targets:
        failures.append("Hybrid-Safe Websearcher: SearXNG Search must feed Build Rich Research Context")

    context_targets = [
        target.get("node")
        for group in ((connections.get("Build Rich Research Context") or {}).get("main") or [])
        for target in group
        if isinstance(target, dict)
    ]
    if "Pick Summary1" not in context_targets:
        failures.append("Hybrid-Safe Websearcher: Build Rich Research Context must feed Pick Summary1")

    return failures


def check_safe_websearch_output_gate_pii_shape(workflows: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    workflow = next((wf for wf in workflows if wf.get("name") == "Hybrid-Safe Websearcher"), None)
    if not workflow:
        return ["Hybrid-Safe Websearcher: workflow missing"]

    nodes = workflow.get("nodes") or []
    output_gate = next((node for node in nodes if node.get("name") == "Fast Output Gate"), None)
    if not output_gate:
        return ["Hybrid-Safe Websearcher: missing Fast Output Gate node"]

    code = str((output_gate.get("parameters") or {}).get("jsCode") or "")
    if r"\b(?:19|20)\d{2}\b" not in code:
        failures.append(
            "Hybrid-Safe Websearcher/Fast Output Gate: "
            "phone PII detector must ignore year/date-like numeric runs"
        )
    if "for (const phone of phones)" not in code:
        failures.append(
            "Hybrid-Safe Websearcher/Fast Output Gate: "
            "phone redaction must redact validated phone candidates only"
        )
    return failures


def check_safe_websearch_policy_specific_comparison(workflows: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    workflow = next((wf for wf in workflows if wf.get("name") == "Hybrid-Safe Websearcher"), None)
    if not workflow:
        return ["Hybrid-Safe Websearcher: workflow missing"]

    nodes = workflow.get("nodes") or []
    policy = next((node for node in nodes if node.get("name") == "Policy Decision"), None)
    if not policy:
        return ["Hybrid-Safe Websearcher: missing Policy Decision node"]

    code = str((policy.get("parameters") or {}).get("jsCode") or "")
    if "vagueGenericReference" not in code:
        failures.append(
            "Hybrid-Safe Websearcher/Policy Decision: "
            "specific comparison questions must not be treated as vague only because they contain words like 'etwas' or 'Infos'"
        )
    if "VAGUE_MARKERS.test(searchQuery) && GENERIC_NOUN.test(searchQuery)) ||" in code:
        failures.append(
            "Hybrid-Safe Websearcher/Policy Decision: "
            "vague marker + generic noun rule must include a low-content guard"
        )
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
    failures.extend(check_conditions_shape(workflows))
    failures.extend(check_safe_websearch_input_gate_regex(workflows))
    failures.extend(check_safe_websearch_research_context_quality(workflows))
    failures.extend(check_safe_websearch_output_gate_pii_shape(workflows))
    failures.extend(check_safe_websearch_policy_specific_comparison(workflows))

    if failures:
        print("n8n workflow static check failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("n8n workflow static check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
