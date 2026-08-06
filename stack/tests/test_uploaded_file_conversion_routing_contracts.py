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


def routing_sources() -> list[str]:
    return [
        COMPOSE.read_text(encoding="utf-8"),
        REGISTER.read_text(encoding="utf-8"),
        *(path.read_text(encoding="utf-8") for path in PROMPTS),
    ]


def test_uploaded_word_to_markdown_routes_only_to_markdown_save_tool():
    for source in routing_sources():
        lowered = source.lower()
        assert "word/docx -> markdown: file_to_md_save" in lowered
        assert "never use file_to_docx_save for a markdown request" in lowered


def test_uploaded_word_to_pdf_bypasses_research_workflow():
    for source in routing_sources():
        lowered = source.lower()
        assert "word/docx -> pdf: docx_to_pdf_save" in lowered
        assert "uploaded-file conversion takes precedence over kahle_workflow" in lowered
        assert "do not research, summarize, rewrite or enrich the document" in lowered


def test_workflow_is_reserved_for_new_generated_documents_not_attached_conversion():
    register = REGISTER.read_text(encoding="utf-8").lower()
    compose = COMPOSE.read_text(encoding="utf-8").lower()

    for source in (register, compose):
        assert "kahle_workflow is only for a newly generated document" in source
        assert "not for converting an attached file" in source


def load_conversion_guard():
    source = MIDDLEWARE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    selected = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"_ascii_fold", "_kahle_uploaded_conversion_block_reason"}
    ]
    namespace = {"re": re, "unicodedata": unicodedata}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(MIDDLEWARE), "exec"), namespace)
    return namespace["_kahle_uploaded_conversion_block_reason"]


def test_central_guard_blocks_wrong_conversion_tools_and_allows_correct_ones():
    guard = load_conversion_guard()

    markdown_request = "Bitte gib mir die Word im Anhang als Markdown aus"
    assert "DATEIKONVERTIERUNG_TOOLCALL_BLOCKIERT" in guard("file_to_docx_save", markdown_request)
    assert guard("file_to_md_save", markdown_request) == ""

    pdf_request = "Bitte wandle die angehängte Word unverändert in eine PDF um"
    assert "DATEIKONVERTIERUNG_TOOLCALL_BLOCKIERT" in guard("kahle_workflow_execute", pdf_request)
    assert guard("docx_to_pdf_save", pdf_request) == ""

    research_request = "Recherchiere intern zum Thema KI-Compliance und erstelle daraus eine PDF"
    assert guard("kahle_workflow_execute", research_request) == ""

if __name__ == "__main__":
    test_uploaded_word_to_markdown_routes_only_to_markdown_save_tool()
    test_uploaded_word_to_pdf_bypasses_research_workflow()
    test_workflow_is_reserved_for_new_generated_documents_not_attached_conversion()
    print("uploaded file conversion routing contract tests passed")
