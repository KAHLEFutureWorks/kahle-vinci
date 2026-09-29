"""Run the harness routing corpus through OpenWebUI for each Vinci model.

Specialized Verification: requires a running local stack, working IONOS models
and an OpenWebUI bearer token (the JWT session token) in the environment.
Results contain no questions, answers or personal data.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from _repo_paths import ensure_repo_paths

ensure_repo_paths()

from harness_eval import (  # noqa: E402
    SCHEMA_VERSION,
    RoutingCase,
    actual_knowledge_tools,
    load_cases,
    routing_outcome,
    score_answer,
    summarize_answers,
    summarize_routing,
)
from run_runtime_eval import OpenWebUIRuntimeClient  # noqa: E402

DEFAULT_MODELS = ("kahle-vinci", "kahle-vinci-thinking", "kahle-vinci-max-thinking")
DEFAULT_CASES = Path(__file__).with_name("routing_cases.yml")


class HarnessRuntimeClient(OpenWebUIRuntimeClient):
    def model_info(self) -> dict[str, Any]:
        response = self.session.get(f"{self.base_url}/api/models", timeout=30)
        response.raise_for_status()
        for model in response.json().get("data") or ():
            if isinstance(model, dict) and model.get("id") == self.model:
                return model
        raise RuntimeError(f"Modell nicht gefunden: {self.model}")

    def ask_messages(
        self, messages: list[dict[str, str]], tool_ids: list[str]
    ) -> tuple[dict[str, Any], str]:
        user_message_id = str(uuid4())
        assistant_message_id = str(uuid4())
        body = {
            "model": self.model,
            "id": assistant_message_id,
            "parent_id": None,
            "session_id": str(uuid4()),
            "user_message": {
                "id": user_message_id,
                "parentId": None,
                "childrenIds": [assistant_message_id],
                "role": "user",
                "content": messages[-1]["content"],
                "timestamp": int(time.time()),
            },
            "messages": [dict(message) for message in messages],
            "tool_ids": list(tool_ids),
            "stream": True,
        }
        message, state = self._start_and_wait(body, assistant_message_id, None)
        return message, state.chat_id


def model_tool_ids(model: dict[str, Any]) -> list[str]:
    meta = (model.get("info") or {}).get("meta") or {}
    return [str(tool) for tool in meta.get("toolIds") or () if str(tool)]


def base_model_id(model: dict[str, Any]) -> str:
    return str((model.get("info") or {}).get("base_model_id") or "")


def _base_row(model: str, case: RoutingCase) -> dict[str, Any]:
    return {
        "model": model,
        "case_id": case.case_id,
        "category": case.category,
        "expected_tools": sorted(case.expected_tools),
        "findings": list(case.findings),
    }


def run_case(
    client: HarnessRuntimeClient, case: RoutingCase, tool_ids: list[str]
) -> tuple[dict[str, Any], str]:
    started = time.monotonic()
    message, chat_id = client.ask_messages(case.messages(), tool_ids)
    wall_ms = round((time.monotonic() - started) * 1000)
    actual = sorted(actual_knowledge_tools(message))
    row = {
        **_base_row(client.model, case),
        "actual_tools": actual,
        "outcome": routing_outcome(case.expected_tools, actual),
        "wall_ms": wall_ms,
        **score_answer(case, message),
    }
    return row, chat_id


def error_row(model: str, case: RoutingCase, error: BaseException) -> dict[str, Any]:
    return {
        **_base_row(model, case),
        "actual_tools": [],
        "outcome": "error",
        "error": type(error).__name__,
    }


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:3004")
    parser.add_argument("--models", default=",".join(DEFAULT_MODELS))
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output-dir", type=Path, default=Path("eval/harness/results"))
    parser.add_argument("--api-key-env", default="OPENWEBUI_API_KEY")
    parser.add_argument("--category", default="")
    parser.add_argument("--max-cases", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    parser.add_argument("--keep-chats", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        raise SystemExit(f"Fehlender API-Schlüssel in {args.api_key_env}")
    cases = load_cases(args.cases)
    if args.category:
        cases = [case for case in cases if case.category == args.category]
    if args.max_cases:
        cases = cases[: args.max_cases]
    models = [model.strip() for model in args.models.split(",") if model.strip()]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    rows_path = args.output_dir / f"harness-runtime-eval-{stamp}.jsonl"
    summary_path = args.output_dir / f"harness-runtime-eval-{stamp}.json"
    rows: list[dict[str, Any]] = []
    model_meta: dict[str, Any] = {}

    with rows_path.open("w", encoding="utf-8") as output:
        for model_id in models:
            client = HarnessRuntimeClient(
                args.base_url, api_key, model_id, args.timeout, args.poll_seconds
            )
            info = client.model_info()
            tool_ids = model_tool_ids(info)
            model_meta[model_id] = {"base_model_id": base_model_id(info), "tool_ids": tool_ids}
            for case in cases:
                chat_id = ""
                try:
                    row, chat_id = run_case(client, case, tool_ids)
                except Exception as error:  # one failed case must not stop the matrix
                    row = error_row(model_id, case, error)
                rows.append(row)
                output.write(json.dumps(row, ensure_ascii=False) + "\n")
                output.flush()
                if chat_id and not args.keep_chats:
                    try:
                        client.delete_chat(chat_id)
                    except Exception:
                        pass
                print(f"{model_id} {case.case_id}: {row['outcome']}")

    report = {
        "schema_version": SCHEMA_VERSION,
        "mode": "runtime",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "base_url": args.base_url,
        "models": model_meta,
        "case_count": len(cases),
        "routing": summarize_routing(rows),
        "answers": summarize_answers([row for row in rows if row["outcome"] != "error"]),
    }
    summary_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for model_id, summary in report["routing"].items():
        print(f"{model_id}: Routing {summary['accuracy']:.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
