"""Resolve the proxy's own download links back to the generated file they name.

A generated file is saved under OWUI_OUTPUT_SUBDIR with a timestamp prefix and
is not a chat attachment. Its download link (/files/d/<id>) is the only exact
reference the chat holds, so file tools accept it as file_path.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

_DOWNLOAD_LINK = re.compile(r"(?:^|/)files/d/([0-9a-f]{32})/?$")


class GeneratedLinkError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def download_id_from_file_path(value: object) -> str | None:
    raw = str(value or "").strip().split("#", 1)[0].split("?", 1)[0]
    match = _DOWNLOAD_LINK.search(raw)
    return match.group(1) if match else None


def generated_rel_path(upload_root: Path, download_id: str, output_subdir: str, now: int | None = None) -> str:
    """Relative path of the generated file behind a download link."""
    manifest_path = upload_root / ".download-links" / f"{download_id}.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        exp = int(manifest.get("exp"))
        rel = str(manifest.get("rel") or "").replace("\\", "/").lstrip("/")
    except Exception:
        raise GeneratedLinkError("generated_file_link_not_found")

    if exp < int(time.time() if now is None else now):
        raise GeneratedLinkError("generated_file_link_expired")

    prefix = output_subdir.strip("/") + "/"
    # Only files the proxy generated itself, never uploads or paths outside the output folder.
    if not rel.startswith(prefix) or any(p in ("", ".", "..") for p in rel[len(prefix):].split("/")):
        raise GeneratedLinkError("generated_file_link_not_found")
    return rel
