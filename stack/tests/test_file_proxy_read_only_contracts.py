from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROXY = ROOT / "stack" / "owui-file-proxy" / "app" / "main.py"
SMOKE = ROOT / "stack" / "tests" / "smoke_file_proxy.py"


def endpoint_source() -> str:
    source = PROXY.read_text(encoding="utf-8")
    start = source.index('def files_extract_text(')
    end = source.index("# Generic single-file -> Markdown", start)
    return source[start:end]


def test_read_only_tool_has_a_small_explicit_interface():
    source = PROXY.read_text(encoding="utf-8")

    assert 'class FilesExtractTextRequest(BaseModel)' in source
    assert 'min_length=1' in source
    assert 'max_length=5' in source
    assert 'max_chars_per_file' in source
    assert 'MAX_EXTRACTED_TEXT_CHARS_TOTAL' in source
    assert 'ge=1000' in source
    assert 'le=100000' in source
    assert '@app.post("/files/extract_text", operation_id="files_extract_text")' in source


def test_read_only_tool_uses_existing_worker_extraction_without_saving():
    endpoint = endpoint_source()

    assert 'f"{DOC_WORKER_URL}/bundle/extract_text"' in endpoint
    assert 'require_exact=True' in endpoint
    assert '(".docx", ".pdf", ".xlsx", ".txt", ".md", ".csv")' in endpoint
    assert '"operation": "read_only_text_extraction"' in endpoint
    assert '"truncated":' in endpoint
    assert '"returned_chars": total_returned_chars' in endpoint
    assert '"truncated": any(item["truncated"] for item in results)' in endpoint
    assert '_save_bytes(' not in endpoint
    assert 'download_url' not in endpoint


def test_public_smoke_contract_expects_text_not_a_download():
    smoke = SMOKE.read_text(encoding="utf-8")

    assert '"/files/extract_text"' in smoke
    assert 'files_extract_text reads multiple uploaded files' in smoke
    assert '"download_url" not in b_read' in smoke


if __name__ == "__main__":
    test_read_only_tool_has_a_small_explicit_interface()
    test_read_only_tool_uses_existing_worker_extraction_without_saving()
    test_public_smoke_contract_expects_text_not_a_download()
    print("file proxy read-only contract tests passed")