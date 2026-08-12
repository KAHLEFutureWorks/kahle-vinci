from run_runtime_eval import ConversationState, OpenWebUIRuntimeClient, normalize_sources


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class Session:
    def __init__(self):
        self.headers = {}
        self.posts = []
        self.deleted = []

    def post(self, url, json, timeout):
        self.posts.append((url, json, timeout))
        return Response({"status": True, "chat_id": "chat-1", "task_ids": ["task-1"]})

    def get(self, url, timeout):
        assistant_id = self.posts[-1][1]["id"]
        return Response({"chat": {"history": {"messages": {assistant_id: {
            "role": "assistant", "done": True, "content": "Belegt", "output": []
        }}}}})

    def delete(self, url, timeout):
        self.deleted.append(url)
        return Response({"status": True})


def test_runtime_client_uses_persisted_browser_workflow_and_followup_parent():
    session = Session()
    client = OpenWebUIRuntimeClient("http://example", "secret", "vinci", poll_seconds=0, session=session)
    item = {"knowledgebase": "kb", "question": "Erste Frage?", "expected_topic": "Thema"}
    _, first = client.ask(item)
    _, second = client.ask({**item, "question": "Und dann?"}, first)

    assert first.chat_id == second.chat_id == "chat-1"
    assert session.posts[0][1]["parent_id"] is None
    assert session.posts[1][1]["chat_id"] == "chat-1"
    assert session.posts[1][1]["parent_id"] == first.assistant_message_id
    assert session.posts[0][1]["tool_ids"] == ["rag_chat"]


def test_sources_are_normalized_for_acceptance_scorer():
    sources = normalize_sources({"sources": [{
        "source": {"name": "Policy"},
        "metadata": {"source_url": "/wissen/api/portal/sources/version-1"},
    }]})

    assert sources[0]["name"] == "Policy"
    assert sources[0]["source_url"] == "/wissen/api/portal/sources/version-1"


def test_sources_are_extracted_from_canonical_rag_tool_output():
    message = {"output": [{
        "type": "function_call_output",
        "output": [{
            "type": "input_text",
            "text": (
                'KAHLE_RAG_RESULT\nFOUND: true\nSOURCES_JSON: '
                '[{"title":"Policy","version_id":"v1","source_url":"/wissen/api/portal/sources/v1"}]\n'
                'FEEDBACK_LINK: [Wissensfehler melden](...)'
            ),
        }],
    }]}

    assert normalize_sources(message) == [{
        "title": "Policy",
        "version_id": "v1",
        "source_url": "/wissen/api/portal/sources/v1",
        "name": "Policy",
    }]
