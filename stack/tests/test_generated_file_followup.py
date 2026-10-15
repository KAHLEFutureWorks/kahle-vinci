"""Follow-up file tools on a file Vinci generated earlier in the same chat.

Generated files land under OWUI_OUTPUT_SUBDIR with a timestamp prefix and are
not chat attachments. A follow-up such as "Wandle die eben erstellte PDF in
Markdown um" used to pass the visible filename, which matched every earlier
generated file of that name across all chats (HTTP 400
ambiguous_filename_use_exact_relative_path).
"""

import importlib.util
import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LINKS = ROOT / "owui-file-proxy" / "app" / "generated_links.py"
PROXY = ROOT / "owui-file-proxy" / "app" / "main.py"
HARNESS = ROOT / "open-webui-overrides" / "open_webui" / "utils" / "kahle_knowledge_harness.py"
MIDDLEWARE = ROOT / "open-webui-overrides" / "open_webui" / "utils" / "middleware.py"

DOWNLOAD_ID = "0123456789abcdef0123456789abcdef"
OTHER_ID = "fedcba9876543210fedcba9876543210"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_manifest(root: Path, download_id: str, rel: str, exp: int) -> None:
    links = root / ".download-links"
    links.mkdir(parents=True, exist_ok=True)
    (links / f"{download_id}.json").write_text(
        json.dumps({"rel": rel, "exp": exp, "filename": Path(rel).name}), encoding="utf-8"
    )


# --- owui-file-proxy: a download link names exactly one generated file -------


def test_download_id_is_read_from_the_links_the_proxy_hands_out():
    links = load("generated_links", LINKS)
    read = links.download_id_from_file_path

    assert read(f"http://localhost:8091/files/d/{DOWNLOAD_ID}") == DOWNLOAD_ID
    assert read(f"https://vinci.kahle.de/files/d/{DOWNLOAD_ID}/") == DOWNLOAD_ID
    assert read(f"/files/d/{DOWNLOAD_ID}") == DOWNLOAD_ID
    assert read(f"files/d/{DOWNLOAD_ID}?x=1") == DOWNLOAD_ID
    assert read("wer_ist_fuer_garantieabwicklung_zustaendig.pdf") is None
    assert read("edited/20261015_112250_f7c4a168_bericht.pdf") is None
    assert read("http://localhost:8091/files/d/not-a-download-id") is None
    assert read(None) is None


def test_download_link_resolves_to_its_generated_file(tmp_path):
    links = load("generated_links", LINKS)
    rel = "edited/20261015_113228_f49c942f_bericht.pdf"
    write_manifest(tmp_path, DOWNLOAD_ID, rel, int(time.time()) + 600)

    assert links.generated_rel_path(tmp_path, DOWNLOAD_ID, "edited") == rel


@pytest.mark.parametrize(
    ("rel", "exp_offset", "code"),
    [
        ("edited/20261015_113228_f49c942f_bericht.pdf", -1, "generated_file_link_expired"),
        ("3f2a1b4c-0000-4000-8000-000000000000_fremde_datei.pdf", 600, "generated_file_link_not_found"),
        ("edited/../secret.pdf", 600, "generated_file_link_not_found"),
    ],
)
def test_download_link_refuses_expired_or_non_generated_targets(tmp_path, rel, exp_offset, code):
    links = load("generated_links", LINKS)
    write_manifest(tmp_path, DOWNLOAD_ID, rel, int(time.time()) + exp_offset)

    with pytest.raises(links.GeneratedLinkError) as excinfo:
        links.generated_rel_path(tmp_path, DOWNLOAD_ID, "edited")
    assert excinfo.value.code == code


def test_unknown_download_link_is_not_found(tmp_path):
    links = load("generated_links", LINKS)

    with pytest.raises(links.GeneratedLinkError) as excinfo:
        links.generated_rel_path(tmp_path, OTHER_ID, "edited")
    assert excinfo.value.code == "generated_file_link_not_found"


def test_resolve_path_accepts_a_download_link_before_the_filename_search():
    source = PROXY.read_text(encoding="utf-8")
    resolve = source[source.index("def _resolve_path("):source.index("def _read_file(")]

    assert "download_id_from_file_path(" in resolve
    assert "generated_rel_path(" in resolve
    # The link is checked before the bare filename search in this chat's files.
    assert resolve.index("download_id_from_file_path(") < resolve.index("hits = [h for h in chat_files if h.name == raw]")
    # Type, root and existence checks still apply to the linked file.
    assert resolve.index("generated_rel_path(") < resolve.index("_ensure_within_upload_root(resolved)")


# --- Open WebUI: map a bare filename to the file generated in this chat ------


def tool_result(payload: dict) -> dict:
    return {"type": "function_call_output", "output": [{"type": "input_text", "text": json.dumps(payload)}]}


def test_generated_files_are_collected_from_tool_results_latest_last():
    harness = load("kahle_harness_generated_files", HARNESS)
    first = f"http://localhost:8091/files/d/{OTHER_ID}"
    latest = f"http://localhost:8091/files/d/{DOWNLOAD_ID}"
    messages = [
        {"role": "user", "content": "Erstelle mir aus dem Ergebnis eine PDF"},
        {"role": "assistant", "content": "Die PDF ist fertig.", "output": [
            {"type": "function_call", "name": "kahle_workflow_execute", "arguments": "{}"},
            tool_result({"download_url": first, "filename": "Bericht.pdf", "size_bytes": 10}),
        ]},
        {"role": "assistant", "content": "Neue Fassung.", "output": [
            tool_result({"workflow": "kahle_workflow_execute",
                         "generated_file": {"download_url": latest, "filename": "Bericht.pdf"}}),
        ]},
        {"role": "assistant", "content": [{"type": "text", "text": "kein Link"}]},
    ]

    assert harness.generated_file_links(messages) == [("Bericht.pdf", first), ("Bericht.pdf", latest)]


def test_generated_files_are_read_from_answer_links_without_stored_tool_results():
    harness = load("kahle_harness_generated_files", HARNESS)
    link = f"http://localhost:8091/files/d/{DOWNLOAD_ID}"
    messages = [
        {"role": "assistant", "content": f"Hier ist deine PDF: [Bericht.pdf]({link})"},
        {"role": "assistant", "content": f"[hier herunterladen]({link})"},
    ]

    assert harness.generated_file_links(messages) == [("Bericht.pdf", link)]


def test_generated_files_ignore_foreign_or_older_link_formats():
    harness = load("kahle_harness_generated_files", HARNESS)
    messages = [
        {"role": "assistant", "output": [tool_result({"download_url": "https://example.com/report.pdf",
                                                      "filename": "report.pdf"})]},
        {"role": "assistant", "output": [tool_result({"download_url": "/files/download?token=abc",
                                                      "filename": "alt.pdf"})]},
        {"role": "assistant", "output": [{"type": "function_call_output", "output": "kein JSON"}]},
        "kaputt",
    ]

    assert harness.generated_file_links(messages) == []


def test_generated_files_are_read_from_openai_tool_messages():
    # Native function calling turns stored output items into role "tool" messages.
    harness = load("kahle_harness_generated_files", HARNESS)
    link = f"http://localhost:8091/files/d/{DOWNLOAD_ID}"
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "function": {"name": "x"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": json.dumps({"download_url": link, "filename": "Bericht.pdf"})},
    ]

    assert harness.generated_file_links(messages) == [("Bericht.pdf", link)]


def test_bare_filenames_map_to_the_latest_generated_link_and_nothing_else():
    harness = load("kahle_harness_generated_files", HARNESS)
    first = f"http://localhost:8091/files/d/{OTHER_ID}"
    latest = f"http://localhost:8091/files/d/{DOWNLOAD_ID}"
    generated = [("Bericht.pdf", first), ("Bericht.pdf", latest), ("Liste.xlsx", first)]
    mapped = harness.map_generated_file_params

    assert mapped({"file_path": "Bericht.pdf", "title": "x"}, generated) == {"file_path": latest, "title": "x"}
    assert mapped({"file_path": "bericht.PDF"}, generated) == {"file_path": latest}
    assert mapped({"file_paths": ["Bericht.pdf", "Andere.pdf"]}, generated) == {"file_paths": [latest, "Andere.pdf"]}
    # Exact paths, links and unknown names stay as the model sent them.
    for value in ("edited/20261015_113228_f49c942f_Bericht.pdf", first, "Andere.pdf"):
        assert mapped({"file_path": value}, generated) == {"file_path": value}
    # An attached upload of the same name keeps the existing attachment behaviour.
    assert mapped({"file_path": "Bericht.pdf"}, generated, attached_names=["Bericht.pdf"]) == {"file_path": "Bericht.pdf"}
    assert mapped({"file_path": "Bericht.pdf"}, []) == {"file_path": "Bericht.pdf"}


def test_middleware_maps_bare_filenames_in_both_tool_paths_after_attachments():
    source = MIDDLEWARE.read_text(encoding="utf-8")
    normalize = source[source.index("def _normalize_file_params("):source.index("def _infer_generated_file_output_format(")]

    # Prompt-based tool calling: attachments keep priority, then this chat's generated files.
    assert normalize.index("_match_exact_from_attached(raw)") < normalize.index("generated_file_link_for(raw, generated_files)")
    assert source.count("_normalize_file_params(") == source.count("generated_files=generated_files") + 1

    # Native function calling (the Vinci models) runs the tool in the streaming handler.
    native = source[source.index("async def streaming_chat_response_handler("):]
    native = native[native.index("allowed_params = spec.get('parameters', {}).get('properties', {}).keys()"):]
    native = native[:native.index("tool_result = await tool_function(**tool_function_params)")]
    assert "map_generated_file_params(" in native
    assert native.index("map_generated_file_params(") < native.index("document_comparison_block_reason = (")
    assert "attached_names=" in native
