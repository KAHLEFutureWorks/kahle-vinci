#!/usr/bin/env python3
"""Static contracts for Open WebUI override compatibility."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OVERRIDES = ROOT / "open-webui-overrides" / "open_webui" / "utils"
MIDDLEWARE = OVERRIDES / "middleware.py"
MISC = OVERRIDES / "misc.py"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_middleware_keeps_open_webui_09_public_import_contract():
    src = read(MIDDLEWARE)

    assert "async def build_chat_response_context(request, form_data, user, model, metadata, tasks, events):" in src
    assert "async def process_chat_payload(request, form_data, user, metadata, model):" in src
    assert "async def process_chat_response(response, ctx):" in src


def test_middleware_keeps_kahle_file_tool_routing_contract():
    src = read(MIDDLEWARE)

    assert "def _normalize_file_params(" in src
    assert "def _extract_file_saved_payload(" in src
    assert "def _infer_fallback_tool_calls(" in src
    assert "def _infer_generated_file_output_format(" in src
    assert "def _looks_like_previous_result_file_request(" in src
    assert "def _stream_safe_output(" in src
    assert "'kahle_workflow_execute'" in src
    assert "def _looks_like_internal_rag_request(" in src
    assert "'rag_chat'" in src
    assert "recovery" in src
    assert "gutschein" in src
    assert "attached_file_names=attached_file_names" in src
    assert "await Chats.get_messages_map_by_chat_id(chat_id)" in src
    assert "async def _evict_stale_local_tool_cache(" in src
    assert "async def _remember_loaded_local_tool_contents(" in src
    assert "await _evict_stale_local_tool_cache(request, tool_ids)" in src
    assert "await _remember_loaded_local_tool_contents(request, tool_ids)" in src
    assert "from open_webui.models.tools import Tools as ToolModels" in src


def test_middleware_honors_upload_embedding_bypass_contract():
    src = read(MIDDLEWARE)

    assert "def _env_flag(" in src
    assert "BYPASS_EMBEDDING_AND_RETRIEVAL" in src
    assert "file_context_enabled = False" in src


def test_misc_keeps_attachment_and_metadata_contracts():
    src = read(MISC)

    assert "Attached files in this message" in src
    assert "def sanitize_metadata(metadata: dict) -> dict:" in src
    assert "def convert_output_to_messages(output: list, raw: bool = False) -> list[dict]:" in src
    assert "def set_last_user_message_content(content: str, messages: list[dict]) -> list[dict]:" in src
    assert "def merge_system_messages(messages: list[dict]) -> list[dict]:" in src
    assert "def strip_empty_content_blocks(messages: list[dict]) -> list[dict]:" in src
    assert "async def cleanup_response(" in src
    assert "async def stream_wrapper(response, session, content_handler=None):" in src


if __name__ == "__main__":
    test_middleware_keeps_open_webui_09_public_import_contract()
    test_middleware_keeps_kahle_file_tool_routing_contract()
    test_middleware_honors_upload_embedding_bypass_contract()
    test_misc_keeps_attachment_and_metadata_contracts()
    print("open webui override contract tests passed")
