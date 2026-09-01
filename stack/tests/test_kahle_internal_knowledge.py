from __future__ import annotations

import ast
import asyncio
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest


STACK_ROOT = Path(__file__).resolve().parents[1]
OVERRIDES_ROOT = STACK_ROOT / "open-webui-overrides"
MODULE = OVERRIDES_ROOT / "open_webui" / "utils" / "kahle_internal_knowledge.py"
MIDDLEWARE = OVERRIDES_ROOT / "open_webui" / "utils" / "middleware.py"


def load_internal_knowledge():
    sys.path.insert(0, str(OVERRIDES_ROOT))
    try:
        spec = importlib.util.spec_from_file_location(
            f"kahle_internal_knowledge_{id(object())}", MODULE
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(OVERRIDES_ROOT))


def request() -> SimpleNamespace:
    return SimpleNamespace()


def user(*, user_id: str = "user-1", role: str = "user") -> SimpleNamespace:
    return SimpleNamespace(id=user_id, role=role)


def vinci(model_id: str = "kahle-vinci-thinking") -> dict[str, str]:
    return {"id": model_id, "name": model_id.replace("-", " ").title()}


class FakePersonioClient:
    def __init__(self, result: Any = None, *, started=None, release=None) -> None:
        self.result = result if result is not None else {"status": "not_found"}
        self.calls: list[tuple[str, str, str, str, str]] = []
        self.started = started
        self.release = release

    async def search(
        self,
        query: str,
        intent: str,
        user_id: str,
        user_role: str,
        *,
        candidate_query: str = "",
    ) -> Any:
        self.calls.append((query, intent, user_id, user_role, candidate_query))
        if self.started is not None:
            self.started.set()
        if self.release is not None:
            await self.release.wait()
        return self.result


@pytest.mark.parametrize(
    "model",
    (
        {"id": "vinci-2-clone-clone-clone", "name": "KAHLE-Vinci"},
        {"id": "kahle-vinci-thinking", "name": "KAHLE-Vinci-Thinking"},
        {"id": "kahle-vinci-max-thinking", "name": "KAHLE-Vinci-Max-Thinking"},
        {"id": "kahle-vinci-future", "name": "KAHLE-Vinci-Future"},
    ),
)
@pytest.mark.parametrize("role", ("user", "admin"))
def test_general_vinci_models_receive_request_bound_personio_tool(model, role):
    internal = load_internal_knowledge()

    tools, session = internal.bind_internal_knowledge_tools(
        tools={}, request=request(), user=user(role=role), model=model, messages=[]
    )

    assert set(tools) == {"personio_directory"}
    assert set(tools["personio_directory"]) == {
        "spec",
        "callable",
        "type",
        "direct",
    }
    assert tools["personio_directory"]["type"] == "kahle_internal"
    assert tools["personio_directory"]["direct"] is False
    assert callable(tools["personio_directory"]["callable"])
    assert session.called_tools() == ()


@pytest.mark.parametrize(
    ("model", "role"),
    (
        ({"id": "kahle-vinci-admin", "name": "KAHLE-Vinci Admin"}, "admin"),
        ({"id": "kahle-email-vinci", "name": "Mailer-Vinci"}, "user"),
        ({"id": "vendor-model", "name": "Unrelated"}, "user"),
        (vinci(), "pending"),
        (vinci(), "employee"),
        (vinci(), ""),
    ),
)
def test_personio_tool_is_hidden_from_admin_model_unrelated_models_and_other_roles(
    model, role
):
    internal = load_internal_knowledge()
    existing = {"other": {"spec": {"name": "other"}}}

    tools, session = internal.bind_internal_knowledge_tools(
        tools=existing,
        request=request(),
        user=user(role=role),
        model=model,
        messages=[],
    )

    assert "personio_directory" not in tools
    assert tools["other"] is existing["other"]
    assert session.called_tools() == ()


def test_personio_schema_exposes_only_the_natural_query(monkeypatch):
    internal = load_internal_knowledge()
    client = FakePersonioClient()
    monkeypatch.setattr(internal, "PersonioDirectoryClient", lambda: client)

    tools, _ = internal.bind_internal_knowledge_tools(
        tools={}, request=request(), user=user(), model=vinci(), messages=[]
    )

    spec = tools["personio_directory"]["spec"]
    assert spec["name"] == "personio_directory"
    parameters = spec["parameters"]
    assert parameters["type"] == "object"
    assert set(parameters["properties"]) == {"query"}
    assert parameters["properties"]["query"]["type"] == "string"
    assert isinstance(parameters["properties"]["query"]["description"], str)
    assert parameters["required"] == ["query"]
    assert parameters["additionalProperties"] is False
    serialized = str(spec).casefold()
    for private_name in (
        "api_key",
        "secret",
        "intent",
        "candidate_query",
        "permission",
        "user_id",
        "user_role",
        "role",
    ):
        assert private_name not in serialized


def test_bound_personio_callable_uses_auto_and_authenticated_identity(monkeypatch):
    internal = load_internal_knowledge()
    result = {"status": "not_found", "claims": [], "sources": []}
    client = FakePersonioClient(result)
    monkeypatch.setattr(internal, "PersonioDirectoryClient", lambda: client)
    query = "Serviceassistenzen Neustadt"

    tools, session = internal.bind_internal_knowledge_tools(
        tools={},
        request=request(),
        user=user(user_id="authenticated-1", role="admin"),
        model=vinci(),
        messages=[{"role": "user", "content": query}],
    )
    actual = asyncio.run(tools["personio_directory"]["callable"](query=query))

    assert actual is result
    assert client.calls == [(query, "auto", "authenticated-1", "admin", "")]
    assert session.called_tools() == ("personio_directory",)


def test_existing_rag_callable_is_wrapped_and_its_permission_filtered_result_recorded():
    internal = load_internal_knowledge()
    calls = []
    result = "KAHLE_RAG_RESULT\nFOUND: false\nSOURCES_JSON: []"

    async def rag_chat(*, query: str) -> str:
        calls.append(query)
        return result

    original_tool = {
        "spec": {
            "name": "rag_chat",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
        },
        "callable": rag_chat,
        "type": "tool",
        "direct": False,
        "tool_id": "rag-tool",
    }

    tools, session = internal.bind_internal_knowledge_tools(
        tools={"rag_chat": original_tool},
        request=request(),
        user=user(),
        model=vinci(),
        messages=[],
    )
    actual = asyncio.run(tools["rag_chat"]["callable"](query="Interne Richtlinie"))

    assert actual == result
    assert calls == ["Interne Richtlinie"]
    assert tools["rag_chat"]["spec"] is original_tool["spec"]
    assert tools["rag_chat"]["type"] == "tool"
    assert tools["rag_chat"]["direct"] is False
    assert tools["rag_chat"]["tool_id"] == "rag-tool"
    assert tools["rag_chat"]["callable"] is not rag_chat
    assert original_tool["callable"] is rag_chat
    assert session.called_tools() == ("rag_chat",)


def test_concurrent_bound_sessions_do_not_share_results(monkeypatch):
    internal = load_internal_knowledge()
    release = asyncio.Event()
    clients = [
        FakePersonioClient({"request": "one"}, started=asyncio.Event(), release=release),
        FakePersonioClient({"request": "two"}, started=asyncio.Event(), release=release),
    ]
    remaining = clients.copy()
    monkeypatch.setattr(internal, "PersonioDirectoryClient", lambda: remaining.pop(0))

    tools_one, session_one = internal.bind_internal_knowledge_tools(
        tools={}, request=request(), user=user(user_id="one"), model=vinci(), messages=[]
    )
    tools_two, session_two = internal.bind_internal_knowledge_tools(
        tools={}, request=request(), user=user(user_id="two"), model=vinci(), messages=[]
    )

    async def run_concurrently():
        first = asyncio.create_task(
            tools_one["personio_directory"]["callable"](query="Query one")
        )
        second = asyncio.create_task(
            tools_two["personio_directory"]["callable"](query="Query two")
        )
        await asyncio.gather(*(client.started.wait() for client in clients))
        release.set()
        return await asyncio.gather(first, second)

    assert asyncio.run(run_concurrently()) == [{"request": "one"}, {"request": "two"}]
    assert clients[0].calls == [("Query one", "auto", "one", "user", "")]
    assert clients[1].calls == [("Query two", "auto", "two", "user", "")]
    assert session_one.called_tools() == ("personio_directory",)
    assert session_two.called_tools() == ("personio_directory",)
    session_one.record("rag_chat", "first-request-only")
    assert session_one.called_tools() == ("personio_directory", "rag_chat")
    assert session_two.called_tools() == ("personio_directory",)


@pytest.mark.parametrize(
    "query",
    (
        "Wer ist seine Führungskraft?",
        "Wer ist ihre Führungskraft?",
        "Wer ist deren Führungskraft?",
        "Wer ist dessen Führungskraft?",
        "Wer ist die Führungskraft?",
        "Ist er die Führungskraft?",
        "Ist sie die Führungskraft?",
    ),
)
def test_controlled_supervisor_followups_receive_only_the_previous_user_query(
    monkeypatch, query
):
    internal = load_internal_knowledge()
    client = FakePersonioClient()
    monkeypatch.setattr(internal, "PersonioDirectoryClient", lambda: client)
    prior = "Wie erreiche ich Erika Beispiel?"
    messages = [
        {"role": "user", "content": prior},
        {"role": "assistant", "content": "Synthetische Antwort."},
        {"role": "user", "content": query},
    ]

    tools, _ = internal.bind_internal_knowledge_tools(
        tools={}, request=request(), user=user(), model=vinci(), messages=messages
    )
    asyncio.run(tools["personio_directory"]["callable"](query=query))

    assert client.calls == [(query, "auto", "user-1", "user", prior)]


def test_new_explicit_full_name_replaces_supervisor_candidate(monkeypatch):
    internal = load_internal_knowledge()
    client = FakePersonioClient()
    monkeypatch.setattr(internal, "PersonioDirectoryClient", lambda: client)
    query = "Wer ist die Führungskraft von Max Muster?"

    tools, _ = internal.bind_internal_knowledge_tools(
        tools={},
        request=request(),
        user=user(),
        model=vinci(),
        messages=[
            {"role": "user", "content": "Wie erreiche ich Erika Beispiel?"},
            {"role": "user", "content": query},
        ],
    )
    asyncio.run(tools["personio_directory"]["callable"](query=query))

    assert client.calls == [(query, "auto", "user-1", "user", "")]


def test_referential_non_supervisor_query_never_inherits_candidate(monkeypatch):
    internal = load_internal_knowledge()
    client = FakePersonioClient()
    monkeypatch.setattr(internal, "PersonioDirectoryClient", lambda: client)
    query = "Wie erreiche ich sie?"

    tools, _ = internal.bind_internal_knowledge_tools(
        tools={},
        request=request(),
        user=user(),
        model=vinci(),
        messages=[
            {"role": "user", "content": "Wie erreiche ich Erika Beispiel?"},
            {"role": "user", "content": query},
        ],
    )
    asyncio.run(tools["personio_directory"]["callable"](query=query))

    assert client.calls == [(query, "auto", "user-1", "user", "")]


def test_middleware_binds_after_resolution_and_before_model_serialization():
    tree = ast.parse(MIDDLEWARE.read_text(encoding="utf-8"))
    process = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "process_chat_payload"
    )
    calls = [
        node
        for node in ast.walk(process)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    bind_line = next(
        node.lineno
        for node in calls
        if node.func.id == "bind_internal_knowledge_tools"
    )
    resolved_lines = [
        node.lineno
        for node in calls
        if node.func.id in {"get_tools", "get_terminal_tools", "get_builtin_tools"}
        and node.lineno < bind_line
    ]
    serialized_lines = [
        node.lineno
        for node in ast.walk(process)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Subscript)
            and isinstance(target.value, ast.Name)
            and target.value.id == "form_data"
            and isinstance(target.slice, ast.Constant)
            and target.slice.value == "tools"
            for target in node.targets
        )
        and node.lineno > bind_line
    ]

    assert resolved_lines
    assert serialized_lines
    assert max(resolved_lines) < bind_line < min(serialized_lines)
