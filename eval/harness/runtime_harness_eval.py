"""Run the harness routing corpus through OpenWebUI for each Vinci model.

Specialized Verification: requires a running local stack, working IONOS models
and an OpenWebUI bearer token (the JWT session token) in the environment.
Results contain no questions, answers or personal data.
"""

from __future__ import annotations

import time
from typing import Any
from uuid import uuid4

from _repo_paths import ensure_repo_paths

ensure_repo_paths()

from harness_eval import (  # noqa: E402
    RoutingCase,
    actual_knowledge_tools,
    routing_outcome,
    score_answer,
)
from run_runtime_eval import OpenWebUIRuntimeClient  # noqa: E402

DEFAULT_MODELS = ("kahle-vinci", "kahle-vinci-thinking", "kahle-vinci-max-thinking")


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
