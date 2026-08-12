"""Measure the real Document Worker conversion gate on a local file corpus."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import requests


MOJIBAKE = ("Ã", "Â", "â€", "�")
ALLOWED = {".pdf", ".docx", ".xlsx", ".pptx", ".txt", ".md"}


def evaluate(path: Path, base_url: str, api_key: str, timeout: int) -> dict:
    started = time.monotonic()
    result = {"path": path.as_posix(), "bytes": path.stat().st_size}
    try:
        with path.open("rb") as handle:
            response = requests.post(
                f"{base_url.rstrip('/')}/bundle/to_md",
                headers={"X-API-Key": api_key},
                files={"files": (path.name, handle, "application/octet-stream")},
                data={"title": path.stem, "mode": "raw"}, timeout=timeout,
            )
        response.raise_for_status()
        markdown = response.content.decode("utf-8", errors="strict").strip()
        issues = []
        if len(markdown) < 20:
            issues.append("conversion_output_too_short")
        if any(marker in markdown for marker in MOJIBAKE):
            issues.append("character_encoding_corrupted")
        result.update(ok=not issues, markdown_chars=len(markdown), issues=issues)
    except Exception as exc:
        result.update(ok=False, markdown_chars=0, issues=[type(exc).__name__])
    result["seconds"] = round(time.monotonic() - started, 3)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--base-url", default="http://document-worker:8090")
    parser.add_argument("--api-key-env", default="DOC_WORKER_API_KEY")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--output")
    args = parser.parse_args()
    api_key = os.getenv(args.api_key_env, "")
    if not api_key:
        parser.error(f"{args.api_key_env} is required")
    files = [path for raw in args.paths for path in Path().glob(raw)
             if path.is_file() and path.suffix.lower() in ALLOWED and path.stat().st_size <= 10 * 1024 * 1024]
    if not files:
        parser.error("no supported files up to 10 MB matched")
    rows = [evaluate(path, args.base_url, api_key, args.timeout) for path in sorted(set(files))]
    success = sum(bool(row["ok"]) for row in rows)
    report = {
        "files": len(rows), "successful": success,
        "success_rate_percent": round(success / len(rows) * 100, 2),
        "within_five_minutes": sum(row["seconds"] <= 300 for row in rows),
        "max_seconds": max(row["seconds"] for row in rows), "results": rows,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        target = Path(args.output); target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["success_rate_percent"] >= 95 and report["within_five_minutes"] == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
