import json

from harness_eval import RoutingCase
from runtime_harness_eval import (
    HarnessRuntimeClient,
    base_model_id,
    error_row,
    model_tool_ids,
    run_case,
)

MODEL = {
    "id": "kahle-vinci",
    "info": {"base_model_id": "mistralai/Mistral-Small-24B-Instruct", "meta": {"toolIds": ["rag_chat", "zeit"]}},
}


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class Session:
    def __init__(self, message_extra=None):
        self.headers = {}
        self.posts = []
        self.message_extra = message_extra or {}

    def post(self, url, json, timeout):
        self.posts.append((url, json))
        return Response({"status": True, "chat_id": "chat-1"})

    def get(self, url, timeout):
        if url.endswith("/api/models"):
            return Response({"data": [{"id": "other"}, MODEL]})
        assistant_id = self.posts[-1][1]["id"]
        message = {"role": "assistant", "done": True, "content": "Geheime Antwort [R1].", "output": [
            {"type": "function_call", "name": "rag_chat"},
        ], **self.message_extra}
        return Response({"chat": {"history": {"messages": {assistant_id: message}}}})


CASE = RoutingCase(
    case_id="followup_case",
    category="followup",
    question="Und in WPS?",
    expected_tools=frozenset({"rag_chat"}),
    history=({"role": "user", "content": "Wie ändere ich X?"}, {"role": "assistant", "content": "So [R1]."}),
)


def _client(session):
    return HarnessRuntimeClient("http://local", "key", "kahle-vinci", poll_seconds=0, session=session)


def test_model_metadata_helpers():
    assert model_tool_ids(MODEL) == ["rag_chat", "zeit"]
    assert base_model_id(MODEL) == "mistralai/Mistral-Small-24B-Instruct"
    assert model_tool_ids({"id": "x"}) == []


def test_model_info_selects_configured_model():
    assert _client(Session()).model_info()["id"] == "kahle-vinci"


def test_ask_messages_sends_full_history_without_system_override():
    session = Session()

    message, chat_id = _client(session).ask_messages(CASE.messages(), ["rag_chat"])

    url, body = session.posts[-1]
    assert url == "http://local/api/chat/completions"
    assert body["messages"] == CASE.messages()
    assert all(item["role"] != "system" for item in body["messages"])
    assert body["tool_ids"] == ["rag_chat"]
    assert body["user_message"]["content"] == "Und in WPS?"
    assert chat_id == "chat-1"
    assert message["done"] is True


def test_run_case_builds_privacy_safe_row():
    session = Session({"kahle_harness_metrics": {"latency_ms": 900}})

    row, chat_id = run_case(_client(session), CASE, ["rag_chat"])

    assert chat_id == "chat-1"
    assert row["model"] == "kahle-vinci"
    assert row["outcome"] == "correct"
    assert row["actual_tools"] == ["rag_chat"]
    assert row["latency_ms"] == 900
    assert isinstance(row["wall_ms"], int)
    serialized = json.dumps(row, ensure_ascii=False)
    assert "Geheime Antwort" not in serialized
    assert "Und in WPS" not in serialized


def test_error_row_keeps_only_error_type():
    row = error_row("kahle-vinci", CASE, RuntimeError("secret upstream detail"))

    assert row["outcome"] == "error"
    assert row["error"] == "RuntimeError"
    assert "secret" not in json.dumps(row)
