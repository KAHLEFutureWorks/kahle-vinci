"""Import paths for the harness evaluation, independent of the working directory."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_RELATIVE_PATHS = (
    "eval/harness",
    "eval/rag",
    "stack/open-webui-tools",
    "stack/open-webui-overrides/open_webui/utils",
)


def ensure_repo_paths() -> None:
    for relative in reversed(_RELATIVE_PATHS):
        path = str(REPO_ROOT / relative)
        if path not in sys.path:
            sys.path.insert(0, path)
