#!/usr/bin/env python3
import argparse
import json
import sys
from urllib import error, parse, request


def http_json(method: str, url: str, payload: dict | None = None, timeout: int = 120):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = request.Request(url=url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            text = raw.decode("utf-8", errors="replace")
            body = json.loads(text) if text else {}
            return resp.getcode(), body
    except error.HTTPError as e:
        text = e.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(text) if text else {}
        except Exception:
            body = {"raw": text}
        return e.code, body


def http_status(url: str, timeout: int = 120) -> int:
    req = request.Request(url=url, method="GET")
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            _ = resp.read(1)
            return resp.getcode()
    except error.HTTPError as e:
        return e.code


def rewrite_host(url: str, base_url: str) -> str:
    pu = parse.urlsplit(url)
    pb = parse.urlsplit(base_url)
    return parse.urlunsplit((pb.scheme, pb.netloc, pu.path, pu.query, pu.fragment))


def get_detail(body: dict) -> str:
    if not isinstance(body, dict):
        return str(body)
    d = body.get("detail")
    if isinstance(d, (str, int, float)):
        return str(d)
    return json.dumps(body, ensure_ascii=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke tests for OWUI file proxy")
    parser.add_argument("--base-url", default="http://127.0.0.1:8091")
    parser.add_argument("--docx-file", required=True)
    parser.add_argument("--pdf-file-a", required=True)
    parser.add_argument("--pdf-file-b", required=True)
    parser.add_argument("--txt-file", required=True)
    parser.add_argument("--xlsx-file", default="")
    parser.add_argument("--xlsx-sheet", default="")
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    failures: list[str] = []
    notes: list[str] = []

    def expect(cond: bool, msg: str):
        if cond:
            notes.append(f"OK: {msg}")
        else:
            failures.append(msg)

    status, health = http_json("GET", f"{base}/health")
    expect(status == 200 and health.get("ok") is True, "health endpoint")

    status, spec = http_json("GET", f"{base}/openapi.json")
    expect(status == 200, "openapi reachable")
    if status == 200:
        paths = set((spec.get("paths") or {}).keys())
        expected = {
            "/docx/replace_one_save",
            "/docx/delete_last_paragraphs_save",
            "/text/apply_ops_save",
            "/xlsx/update_cells_save",
            "/docx/to_pdf_save",
            "/file/to_md_save",
            "/pdf/remove_pages_save",
            "/pdf/merge_save",
            "/bundle/to_md_save",
        }
        expect(paths == expected, "openapi paths match save-only contract")

    def save_call(path: str, payload: dict, name: str):
        s, b = http_json("POST", f"{base}{path}", payload=payload, timeout=300)
        if s != 200:
            failures.append(f"{name}: expected 200, got {s}, detail={get_detail(b)}")
            return None
        must_keys = {"download_url", "filename", "sha256", "size_bytes"}
        missing = [k for k in must_keys if k not in b]
        if missing:
            failures.append(f"{name}: missing keys {missing}")
            return None
        notes.append(f"OK: {name}")
        return b

    r_docx_replace = save_call(
        "/docx/replace_one_save",
        {"from_text": "test", "to_text": "TEST", "file_path": args.docx_file},
        "docx_replace_one_save",
    )
    _ = save_call(
        "/docx/delete_last_paragraphs_save",
        {"file_path": args.docx_file, "n": 1},
        "docx_delete_last_paragraphs_save",
    )
    _ = save_call(
        "/text/apply_ops_save",
        {
            "file_path": args.txt_file,
            "ops": [{"op": "replace_all", "from": "Autohaus", "to": "KAHLE"}],
        },
        "text_apply_ops_save",
    )
    r_pdf_remove = save_call(
        "/pdf/remove_pages_save",
        {"file_path": args.pdf_file_a, "remove_pages": [1]},
        "pdf_remove_pages_save",
    )
    _ = save_call(
        "/pdf/merge_save",
        {"file_paths": [args.pdf_file_a, args.pdf_file_b], "output_name": "smoke_merged.pdf"},
        "pdf_merge_save",
    )
    _ = save_call(
        "/bundle/to_md_save",
        {"title": "Smoke_Masterkontext", "file_paths": [args.docx_file, args.txt_file, args.pdf_file_a]},
        "bundle_to_md_save",
    )
    _ = save_call(
        "/docx/to_pdf_save",
        {"file_path": args.docx_file, "output_name": "smoke_docx_to_pdf.pdf"},
        "docx_to_pdf_save",
    )
    _ = save_call(
        "/file/to_md_save",
        {"file_path": args.pdf_file_a, "title": "Smoke PDF zu MD", "output_name": "smoke_pdf_to_md.md"},
        "file_to_md_save",
    )

    s_guard, b_guard = http_json(
        "POST",
        f"{base}/text/apply_ops_save",
        {
            "file_path": args.txt_file,
            "ops": [{"op": "delete_last_lines", "n": 9999}],
        },
    )
    expect(
        s_guard == 400 and "empty_output_blocked_set_allow_empty_output_true_to_override" in get_detail(b_guard),
        "text empty-output guardrail blocks by default",
    )

    s_guard2, b_guard2 = http_json(
        "POST",
        f"{base}/text/apply_ops_save",
        {
            "file_path": args.txt_file,
            "ops": [{"op": "delete_last_lines", "n": 9999}],
            "allow_empty_output": True,
        },
    )
    expect(s_guard2 == 200 and int(b_guard2.get("size_bytes", -1)) == 0, "text empty-output override works")

    if args.xlsx_file and args.xlsx_sheet:
        _ = save_call(
            "/xlsx/update_cells_save",
            {
                "file_path": args.xlsx_file,
                "updates": [{"sheet": args.xlsx_sheet, "cell": "A1", "value": "SMOKE_OK"}],
            },
            "xlsx_update_cells_save",
        )
    else:
        notes.append("SKIP: xlsx_update_cells_save (no --xlsx-file/--xlsx-sheet)")

    # Signed download checks
    dl_src = r_pdf_remove or r_docx_replace
    if dl_src:
        dl = rewrite_host(dl_src["download_url"], base)
        expect(http_status(dl) == 200, "signed download works")

        pu = parse.urlsplit(dl)
        q = parse.parse_qs(pu.query, keep_blank_values=True)
        sig = (q.get("sig") or [""])[0]
        if sig:
            bad_sig = ("0" if sig[-1] != "0" else "1")
            q["sig"] = [sig[:-1] + bad_sig]
            tampered = parse.urlunsplit((pu.scheme, pu.netloc, pu.path, parse.urlencode(q, doseq=True), pu.fragment))
            expect(http_status(tampered) == 401, "tampered signature rejected")
        else:
            failures.append("signed download check: missing sig")

        q_expired = parse.parse_qs(pu.query, keep_blank_values=True)
        q_expired["exp"] = ["1"]
        expired = parse.urlunsplit(
            (pu.scheme, pu.netloc, pu.path, parse.urlencode(q_expired, doseq=True), pu.fragment)
        )
        expect(http_status(expired) == 410, "expired link rejected")
    else:
        failures.append("signed download check skipped: no successful save result")

    print("=== SMOKE RESULTS ===")
    for n in notes:
        print(n)
    if failures:
        print("\n=== FAILURES ===")
        for f in failures:
            print(f"- {f}")
        return 1
    print("\nAll smoke checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
