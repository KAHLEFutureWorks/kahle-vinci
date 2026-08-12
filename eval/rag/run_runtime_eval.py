#!/usr/bin/env python3
"""Run the RAG acceptance set through OpenWebUI's real persisted-chat workflow.

Unlike the OpenAI-compatible direct endpoint, the browser workflow executes
tools in a background task and persists the final answer, tool output and
sources on the assistant message.  This runner follows that same path.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import requests
import yaml


NO_SOURCE_ANSWER = "Dazu habe ich keine verlässliche freigegebene Information."


def load_questions(path: Path) -> list[dict[str, Any]]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
    result: list[dict[str, Any]] = []
    for knowledgebase, items in payload.get("knowledgebases", {}).items():
        for item in items:
            result.append({"knowledgebase": knowledgebase, **item})
    return result


def build_prompt(item: dict[str, Any]) -> str:
    return (
        "Suche in der Knowledgebase und beantworte die Frage nur anhand freigegebener Quellen. "
        "Wenn sie nicht belegt ist, sage kurz, dass die Information in den Quellen fehlt.\n\n"
        f"Frage: {item['question']}"
    )


def normalize_sources(message: dict[str, Any]) -> list[dict[str, Any]]:
    sources = list(message.get("sources") or [])
    for item in message.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "function_call_output":
            continue
        for part in item.get("output") or []:
            text = part.get("text", "") if isinstance(part, dict) else ""
            match = re.search(r"SOURCES_JSON:\s*(\[.*?\])\s*(?:\n|$)", text, re.DOTALL)
            if match:
                try:
                    decoded = json.loads(match.group(1))
                    if isinstance(decoded, list):
                        sources.extend(decoded)
                except json.JSONDecodeError:
                    pass
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for source in sources:
        if not isinstance(source, dict):
            continue
        metadata = source.get("metadata") or {}
        nested = source.get("source") or {}
        url = (
            source.get("source_url")
            or source.get("url")
            or metadata.get("source_url")
            or metadata.get("url")
            or nested.get("source_url")
            or nested.get("url")
        )
        name = (
            source.get("name")
            or metadata.get("name")
            or metadata.get("source")
            or nested.get("name")
            or nested.get("id")
        )
        row = {**source, "name": name or source.get("title") or "", "source_url": url or ""}
        key = (str(row.get("version_id") or ""), str(row["source_url"]))
        if key not in seen:
            seen.add(key)
            normalized.append(row)
    return normalized


def extract_tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    calls = []
    for item in message.get("output") or []:
        if isinstance(item, dict) and item.get("type") == "function_call":
            calls.append(item)
    return calls


@dataclass
class ConversationState:
    chat_id: str
    assistant_message_id: str


class OpenWebUIRuntimeClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: int = 180,
        poll_seconds: float = 1.0,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.poll_seconds = poll_seconds
        self.session = session or requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {api_key}"})

    def ask(self, item: dict[str, Any], state: ConversationState | None = None) -> tuple[dict, ConversationState]:
        prompt = build_prompt(item)
        user_message_id = str(uuid4())
        assistant_message_id = str(uuid4())
        parent_id = state.assistant_message_id if state else None
        user_message = {
            "id": user_message_id,
            "parentId": parent_id,
            "childrenIds": [assistant_message_id],
            "role": "user",
            "content": prompt,
            "timestamp": int(time.time()),
        }
        body: dict[str, Any] = {
            "model": self.model,
            "id": assistant_message_id,
            "parent_id": parent_id,
            "session_id": str(uuid4()),
            "user_message": user_message,
            "messages": [
                {"role": "system", "content": "Du bist ein vorsichtiger deutschsprachiger RAG-Evaluationsassistent."},
                {"role": "user", "content": prompt},
            ],
            "tool_ids": ["rag_chat"],
            "stream": True,
        }
        if state:
            body["chat_id"] = state.chat_id

        started = self.session.post(
            f"{self.base_url}/api/chat/completions", json=body, timeout=self.timeout_seconds
        )
        started.raise_for_status()
        task = started.json()
        chat_id = str(task.get("chat_id") or (state.chat_id if state else ""))
        if not task.get("status") or not chat_id:
            raise RuntimeError(f"OpenWebUI did not start the chat task: {task}")

        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            try:
                chat_response = self.session.get(
                    f"{self.base_url}/api/v1/chats/{chat_id}", timeout=min(30, self.timeout_seconds)
                )
            except requests.Timeout:
                time.sleep(self.poll_seconds)
                continue
            chat_response.raise_for_status()
            chat = chat_response.json().get("chat") or {}
            messages = ((chat.get("history") or {}).get("messages") or {})
            message = messages.get(assistant_message_id)
            if message and message.get("error"):
                raise RuntimeError(f"OpenWebUI chat task failed: {message['error']}")
            if message and message.get("done") is True:
                return message, ConversationState(chat_id, assistant_message_id)
            time.sleep(self.poll_seconds)
        raise TimeoutError(f"OpenWebUI chat task did not finish within {self.timeout_seconds}s")

    def delete_chat(self, chat_id: str) -> None:
        response = self.session.delete(f"{self.base_url}/api/v1/chats/{chat_id}", timeout=30)
        response.raise_for_status()


def run(args: argparse.Namespace) -> Path:
    api_key = args.api_key or os.environ.get(args.api_key_env)
    if not api_key:
        raise SystemExit(f"Missing API key; use --api-key or {args.api_key_env}")
    questions = load_questions(args.questions)
    if args.adhoc_question:
        questions = [{
            "knowledgebase": "runtime-check",
            "question": args.adhoc_question,
            "expected_topic": "Ad-hoc-Laufzeitprüfung",
            "must_have_terms": [],
        }]
    if args.question_contains:
        needle = args.question_contains.casefold()
        questions = [item for item in questions if needle in str(item.get("question", "")).casefold()]
        if not questions:
            raise SystemExit(f"No question contains: {args.question_contains}")
    if args.max_questions:
        questions = questions[: args.max_questions]
    client = OpenWebUIRuntimeClient(
        args.base_url, api_key, args.model, args.timeout, args.poll_seconds
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    output_path = args.output_dir / f"rag-runtime-eval-{stamp}.jsonl"
    conversations: dict[str, ConversationState] = {}
    created_chat_ids: set[str] = set()

    try:
        with output_path.open("w", encoding="utf-8") as output:
            for index, item in enumerate(questions, 1):
                conversation = str(item.get("conversation") or "")
                state = conversations.get(conversation) if conversation else None
                started = time.monotonic()
                record: dict[str, Any] = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "knowledgebase": item["knowledgebase"],
                    "question": item["question"],
                    "expected_topic": item.get("expected_topic", ""),
                    "conversation": conversation,
                    "must_have_terms": item.get("must_have_terms", []),
                }
                try:
                    message, new_state = client.ask(item, state)
                    created_chat_ids.add(new_state.chat_id)
                    if conversation:
                        conversations[conversation] = new_state
                    record.update(
                        status="ok",
                        answer=str(message.get("content") or ""),
                        sources=normalize_sources(message),
                        tool_calls=extract_tool_calls(message),
                        error="",
                    )
                except Exception as exc:
                    record.update(status="error", answer="", sources=[], tool_calls=[], error=str(exc))
                record["elapsed_ms"] = round((time.monotonic() - started) * 1000)
                output.write(json.dumps(record, ensure_ascii=False) + "\n")
                output.flush()
                print(f"[{index}/{len(questions)}] {record['status']}: {item['question']}")
    finally:
        if not args.keep_chats:
            for chat_id in created_chat_ids:
                try:
                    client.delete_chat(chat_id)
                except Exception as exc:
                    print(f"Warning: could not delete temporary chat {chat_id}: {exc}")
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:3001")
    parser.add_argument("--model", default="vinci-2-clone-clone-clone")
    parser.add_argument("--questions", type=Path, default=Path("eval/rag/questions.yml"))
    parser.add_argument("--output-dir", type=Path, default=Path("eval/rag/results"))
    parser.add_argument("--api-key")
    parser.add_argument("--api-key-env", default="OPENWEBUI_API_KEY")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    parser.add_argument("--max-questions", type=int, default=0)
    parser.add_argument("--question-contains", default="")
    parser.add_argument("--adhoc-question", default="")
    parser.add_argument("--keep-chats", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    path = run(parse_args())
    print(path)
