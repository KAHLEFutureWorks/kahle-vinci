import ast
import re
import unicodedata
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "stack" / "docker-compose.yml"
REGISTER = ROOT / "scripts" / "openwebui" / "register-kahle-workflow-tool.py"
MIDDLEWARE = ROOT / "stack" / "open-webui-overrides" / "open_webui" / "utils" / "middleware.py"
PROMPTS = [
    ROOT / "stack" / "open-webui-prompts" / "kahle-vinci-systemprompt.md",
    ROOT / "stack" / "open-webui-prompts" / "kahle-vinci-thinking-systemprompt.md",
]


def test_tool_router_keeps_document_comparisons_read_only_and_in_chat():
    compose = COMPOSE.read_text(encoding="utf-8")
    register = REGISTER.read_text(encoding="utf-8")

    assert "files_extract_text is the read-only tool" in compose
    assert "call files_extract_text once with all relevant file_paths" in compose
    assert "Never call file_to_md_save, file_to_docx_save, bundle_to_md_save or another *_save tool" in compose

    assert "files_extract_text is the read-only tool" in register
    assert "call files_extract_text once with all relevant file_paths" in register
    assert "Never call file_to_md_save, file_to_docx_save, bundle_to_md_save or another *_save tool" in register


def test_tool_router_uses_read_only_extraction_for_document_analysis():
    compose = COMPOSE.read_text(encoding="utf-8")
    register = REGISTER.read_text(encoding="utf-8")

    assert "files_extract_text" in compose
    assert "files_extract_text" in register
    assert "read-only" in compose.lower()
    assert "read-only" in register.lower()


def test_model_prompts_separate_read_compare_edit_and_convert_intents():
    for prompt_path in PROMPTS:
        prompt = prompt_path.read_text(encoding="utf-8")
        assert "files_extract_text" in prompt
        assert "read-only" in prompt.lower()
        assert "Vergleich" in prompt
        assert "*_save" in prompt
        assert "neutral" in prompt.lower()
        assert "KAHLE-Sicht" in prompt
        assert "truncated" in prompt


def load_comparison_guard():
    source = MIDDLEWARE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    selected = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"_ascii_fold", "_kahle_document_comparison_block_reason"}
    ]
    namespace = {"re": re, "unicodedata": unicodedata}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(MIDDLEWARE), "exec"), namespace)
    return namespace["_kahle_document_comparison_block_reason"]


def test_comparison_guard_allows_reading_and_explicit_editing_but_blocks_comparison_saves():
    guard = load_comparison_guard()

    assert guard("files_extract_text", "Vergleiche bitte beide Dokumente") == ""
    assert guard("docx_replace_one_save", "Bitte bearbeite diese Änderung im Vertrag") == ""
    assert "DATEIVERGLEICH_TOOLCALL_BLOCKIERT" in guard(
        "file_to_md_save", "Was wurde in der Richtlinie überarbeitet?"
    )
    assert "DATEIVERGLEICH_TOOLCALL_BLOCKIERT" in guard(
        "docx_replace_one_save", "Vergleiche die alte und neue Vertragsversion"
    )


def test_central_guard_blocks_all_save_tools_for_document_comparisons():
    middleware = MIDDLEWARE.read_text(encoding="utf-8")

    assert "def _kahle_document_comparison_block_reason" in middleware
    assert "name.endswith('_save')" in middleware
    assert "'docx_'" in middleware
    assert "'file_'" in middleware
    assert "'vergleich'" in middleware
    assert "'was wurde geaendert'" in middleware
    assert "'aenderung'" not in middleware
    assert "DATEIVERGLEICH_TOOLCALL_BLOCKIERT" in middleware
    assert "Verwende keine weiteren *_save-Tools" in middleware
    assert "Rufe stattdessen files_extract_text" in middleware


def test_guard_runs_before_classic_and_native_direct_tool_execution():
    middleware = MIDDLEWARE.read_text(encoding="utf-8")

    classic_start = middleware.index("async def chat_completion_tools_handler")
    classic_guard = middleware.index("document_comparison_validation_error =", classic_start)
    classic_direct = middleware.index("tool_result = await event_caller", classic_guard)
    assert classic_guard < classic_direct

    native_start = middleware.index("while len(tool_calls) > 0")
    native_guard = middleware.index("document_comparison_block_reason =", native_start)
    native_direct = middleware.index("tool_result = await event_caller", native_guard)
    assert native_guard < native_direct


def test_explicit_file_conversion_remains_available_without_comparison_intent():
    compose = COMPOSE.read_text(encoding="utf-8")

    assert "explicit conversion of PDF/DOCX/TXT/MD/XLSX/CSV -> downloadable markdown" in compose
    assert "Use an *_save tool only when the user explicitly requests" in compose


if __name__ == "__main__":
    test_tool_router_keeps_document_comparisons_read_only_and_in_chat()
    test_tool_router_uses_read_only_extraction_for_document_analysis()
    test_model_prompts_separate_read_compare_edit_and_convert_intents()
    test_comparison_guard_allows_reading_and_explicit_editing_but_blocks_comparison_saves()
    test_central_guard_blocks_all_save_tools_for_document_comparisons()
    test_guard_runs_before_classic_and_native_direct_tool_execution()
    test_explicit_file_conversion_remains_available_without_comparison_intent()
    print("document comparison routing contract tests passed")
