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


def test_middleware_keeps_open_webui_0110_public_import_contract():
    src = read(MIDDLEWARE)

    assert "async def build_chat_response_context(request, form_data, user, model, metadata, tasks, events):" in src
    assert "async def process_chat_payload(request, form_data, user, metadata, model):" in src
    assert "async def process_chat_response(response, ctx):" in src
    assert "async def convert_url_images_to_base64(form_data, user=None):" in src
    assert "await get_image_base64_from_url(image_url, user=user)" in src
    assert "payload_tools = form_data.get('tools', None)  # snapshot before filters" in src
    assert "connection = await connect_mcp_server(" in src
    assert "form_data['tools'].extend(inlet_filter_tools)" in src
    assert "CHAT_RESPONSE_MAX_TOOL_CALL_ITERATIONS" in src
    assert "CHAT_RESPONSE_MAX_TOOL_CALL_RETRIES" not in src
    assert "'content': final_notice," in src
    assert "serialize_output(" not in src
    assert "FilterContext," in src
    assert src.count("filter_context=None,") == 2
    assert src.count("filter_context=filter_context,") == 3
    assert src.count("filter_context = FilterContext()") == 2


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
    assert "FINAL_NOTICE_PREFIX" in src
    assert "def _extract_final_notice(" in src
    assert "tool_calls.clear()" in src
    assert "Replace the live streamed message with the canonical outlet content" in src
    assert "'type': 'replace'" in src
    assert "deterministic_tool_calls = _infer_fallback_tool_calls({}, user_tool_request)" in src
    assert "Das interne KAHLE-Wissenswerkzeug wurde bereits erfolgreich ausgefuehrt" in src
    assert "Der angeforderte Datei-Workflow wurde bereits erfolgreich ausgefuehrt" in src
    assert "async def apply_source_context_to_messages(" in src
    assert "await rag_template(await Config.get('rag.template'), context, user_message)" in src
    assert "rag_content = await rag_template(" in src
    assert "metadata['kahle_direct_final_content']" in src
    assert "direct_final_content = str(metadata.get('kahle_direct_final_content') or '').strip()" in src
    assert "await response.body_iterator.aclose()" in src
    assert "def _extract_kahle_file_saved_payload(" in src
    assert "def _format_kahle_file_saved_content(" in src
    assert "file_saved_payload = _extract_kahle_file_saved_payload(tool_result)" in src
    assert "successful file result back through the model" in src


def test_middleware_honors_upload_embedding_bypass_contract():
    src = read(MIDDLEWARE)

    assert "def _env_flag(" in src
    assert "BYPASS_EMBEDDING_AND_RETRIEVAL" in src
    assert "file_context_enabled = False" in src


def test_misc_keeps_attachment_and_metadata_contracts():
    src = read(MISC)

    assert "Attached files in this message" in src
    assert "def sanitize_metadata(metadata: dict) -> dict:" in src
    assert "def convert_output_to_messages(" in src
    assert "def set_last_user_message_content(content: str, messages: list[dict]) -> list[dict]:" in src
    assert "def merge_system_messages(messages: list[dict]) -> list[dict]:" in src
    assert "def strip_empty_content_blocks(messages: list[dict]) -> list[dict]:" in src
    assert "async def cleanup_response(" in src
    assert "async def stream_wrapper(response, session, content_handler=None):" in src


if __name__ == "__main__":
    test_middleware_keeps_open_webui_0110_public_import_contract()
    test_middleware_keeps_kahle_file_tool_routing_contract()
    test_middleware_honors_upload_embedding_bypass_contract()
    test_misc_keeps_attachment_and_metadata_contracts()
    print("open webui override contract tests passed")
