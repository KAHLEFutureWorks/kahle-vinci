"""Request-local binding for KAHLE's approved internal knowledge tools."""

from __future__ import annotations

import inspect
import re
import unicodedata
from typing import Any

from open_webui.utils.kahle_knowledge_harness import (
    HarnessDecision,
    build_result_driven_decision,
)
from open_webui.utils.personio_directory_client import PersonioDirectoryClient


__all__ = [
    "KnowledgeEvidenceSession",
    "bind_internal_knowledge_tools",
    "upsert_answer_contract_message",
]

_INTERNAL_TOOL_NAMES = frozenset({"personio_directory", "rag_chat"})
_ALLOWED_ROLES = frozenset({"user", "admin"})
_FULL_NAME_AFTER_RELATION = re.compile(
    r"\b(?:von|fur)\s+(?:[\w.'-]+\s+){1,3}[\w.'-]+\b"
)
_POSSESSIVE_FULL_NAME = re.compile(
    r"\b(?:[A-ZÄÖÜ][\w.'-]*\s+){1,3}[A-ZÄÖÜ][\w.'-]*s?\s+"
    r"(?:Führungskraft|Vorgesetzte(?:r|n)?)\b"
)
_SUPERVISOR_RELATION = re.compile(r"\b(?:fuhrungskraft|vorgesetzt\w*|chef|chefin)\b")
_SUPERVISOR_REFERENCE = re.compile(
    r"\b(?:seine|ihre|deren|dessen|die\s+fuhrungskraft|er|sie)\b"
)
_SUPERVISOR_REFERENCE_ONLY_WORDS = frozenset(
    {
        "bitte", "davon", "denen", "deren", "dessen", "die", "du", "er",
        "fuhrungskraft", "ihnen", "ihre", "ist", "kannst", "mir", "nennen",
        "seine", "sie", "vorgesetzte", "vorgesetzten", "wer",
    }
)


def _value(obj: Any, name: str) -> str:
    if isinstance(obj, dict):
        value = obj.get(name)
    else:
        value = getattr(obj, name, None)
    return str(value or "").strip()


def _fold(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    return "".join(character for character in text if not unicodedata.combining(character))


def _is_general_vinci_model(model: dict[str, Any]) -> bool:
    identifiers = {
        _fold(model.get("id")).replace("_", "-"),
        _fold(model.get("name")).replace("_", "-"),
    }
    return any(
        value == "kahle-vinci"
        or (
            value.startswith("kahle-vinci-")
            and not value.startswith("kahle-vinci-admin")
        )
        for value in identifiers
    ) or "vinci-2-clone-clone-clone" in identifiers


def _supervisor_candidate_query(
    messages: list[dict[str, Any]], query: str
) -> str:
    """Scope prior context to controlled referential supervisor follow-ups."""
    current = str(query or "").strip()
    folded = _fold(current)
    if not _SUPERVISOR_RELATION.search(folded):
        return ""
    if _FULL_NAME_AFTER_RELATION.search(folded) or _POSSESSIVE_FULL_NAME.search(current):
        return ""
    if not _SUPERVISOR_REFERENCE.search(folded):
        return ""
    remaining_words = {
        word for word in re.findall(r"[a-z0-9]+", folded)
        if word not in _SUPERVISOR_REFERENCE_ONLY_WORDS
    }
    if remaining_words:
        # An explicitly named area/location belongs to the current question.
        # Only genuinely referential prompts may inherit an earlier subject.
        return ""

    prior_user_messages = [
        str(message.get("content") or "").strip()
        for message in messages
        if isinstance(message, dict) and message.get("role") == "user"
    ]
    for candidate in reversed(prior_user_messages):
        if candidate and candidate != current:
            return candidate
    return ""


class KnowledgeEvidenceSession:
    """Collect internal tool results for exactly one chat request."""

    def __init__(
        self, *, model: dict[str, Any] | None = None, messages: list[dict[str, Any]] | None = None
    ) -> None:
        self._model_id = str((model or {}).get("id") or "")
        self._messages = list(messages or [])
        self._calls: list[str] = []
        self._results: dict[str, Any] = {}

    def record(self, tool_name: str, result: Any) -> None:
        name = str(tool_name or "")
        if name not in _INTERNAL_TOOL_NAMES:
            return
        self._calls.append(name)
        self._results[name] = result

    def called_tools(self) -> tuple[str, ...]:
        return tuple(self._calls)

    def build_decision(
        self, *, query: str, permission_scope: dict[str, Any]
    ) -> HarnessDecision | None:
        """Build a decision only from results recorded in this request."""
        return build_result_driven_decision(
            called_tools=self.called_tools(),
            query=query,
            messages=self._messages,
            model_id=self._model_id,
            permission_scope=permission_scope,
            rag_result=str(self._results.get("rag_chat") or ""),
            personio_result=self._results.get("personio_directory"),
        )


def upsert_answer_contract_message(
    messages: list[dict[str, Any]], decision: HarnessDecision | None
) -> list[dict[str, Any]]:
    """Insert one replaceable AnswerContract system message."""
    if decision is None:
        return list(messages or [])

    marker = "KAHLE_KNOWLEDGE_ANSWER_CONTRACT\n"
    updated = [
        message
        for message in list(messages or [])
        if not (
            isinstance(message, dict)
            and message.get("role") == "system"
            and str(message.get("content") or "").startswith(marker)
        )
    ]
    insert_at = 0
    while (
        insert_at < len(updated)
        and isinstance(updated[insert_at], dict)
        and updated[insert_at].get("role") == "system"
    ):
        insert_at += 1
    updated.insert(
        insert_at,
        {"role": "system", "content": decision.answer_prompt()},
    )
    return updated


def _personio_tool(
    *,
    client: PersonioDirectoryClient,
    session: KnowledgeEvidenceSession,
    messages: list[dict[str, Any]],
    user_id: str,
    user_role: str,
) -> dict[str, Any]:
    async def search(*, query: str) -> Any:
        result = await client.search(
            query,
            "auto",
            user_id,
            user_role,
            candidate_query=_supervisor_candidate_query(messages, query),
        )
        session.record("personio_directory", result)
        return result

    return {
        "spec": {
            "name": "personio_directory",
            "description": (
                "Search the current KAHLE employee directory for people, positions, "
                "teams, departments, locations, onboarding, and supervisors."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The unchanged natural-language directory question.",
                    }
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
        "callable": search,
        "type": "kahle_internal",
        "direct": False,
    }


def _recording_rag_tool(
    tool: dict[str, Any], session: KnowledgeEvidenceSession
) -> dict[str, Any]:
    original = tool.get("callable")
    if not callable(original):
        return tool

    async def call_and_record(**kwargs: Any) -> Any:
        result = original(**kwargs)
        if inspect.isawaitable(result):
            result = await result
        session.record("rag_chat", result)
        return result

    return {**tool, "callable": call_and_record}


def bind_internal_knowledge_tools(
    *,
    tools: dict[str, Any],
    request: Any,
    user: Any,
    model: dict[str, Any],
    messages: list[dict[str, Any]],
) -> tuple[dict[str, Any], KnowledgeEvidenceSession]:
    """Bind safe internal tools and a fresh evidence session to one request."""
    del request
    bound_tools = dict(tools or {})
    bound_tools.pop("personio_directory", None)
    session = KnowledgeEvidenceSession(model=model, messages=messages)
    user_id = _value(user, "id")
    user_role = _value(user, "role")
    if (
        not user_id
        or user_role not in _ALLOWED_ROLES
        or not _is_general_vinci_model(model)
    ):
        return bound_tools, session

    rag_tool = bound_tools.get("rag_chat")
    if isinstance(rag_tool, dict):
        bound_tools["rag_chat"] = _recording_rag_tool(rag_tool, session)
    bound_tools["personio_directory"] = _personio_tool(
        client=PersonioDirectoryClient(),
        session=session,
        messages=messages,
        user_id=user_id,
        user_role=user_role,
    )
    return bound_tools, session
