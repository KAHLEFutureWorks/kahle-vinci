from __future__ import annotations

import argparse
import re
from pathlib import Path


ENV_SUFFIX_BLOCK = """WEBUI_NAME = os.getenv('WEBUI_NAME', 'Open WebUI')
if WEBUI_NAME != 'Open WebUI':
    WEBUI_NAME += ' (Open WebUI)'"""
ENV_NO_SUFFIX_BLOCK = """WEBUI_NAME = os.getenv('WEBUI_NAME', 'Open WebUI')"""


def patch_index(index_path: Path) -> None:
    text = index_path.read_text(encoding="utf-8")
    text, svg_count = re.subn(
        r"\s*<link\s+rel=\"icon\"\s+type=\"image/svg\+xml\"\s+href=\"/static/favicon\.svg\"\s+crossorigin=\"use-credentials\"\s*/>",
        "",
        text,
        count=1,
    )
    if svg_count != 1:
        raise RuntimeError("SVG favicon link not found in OpenWebUI index")

    old_shortcut = (
        '<link rel="shortcut icon" href="/static/favicon.ico" '
        'crossorigin="use-credentials" />'
    )
    new_shortcut = (
        '<link rel="shortcut icon" type="image/png" href="/static/favicon.png" '
        'crossorigin="use-credentials" />'
    )
    if old_shortcut not in text:
        raise RuntimeError("shortcut favicon link not found in OpenWebUI index")
    text = text.replace(old_shortcut, new_shortcut, 1)
    index_path.write_text(text, encoding="utf-8")


def patch_env(env_path: Path) -> None:
    text = env_path.read_text(encoding="utf-8")
    if ENV_SUFFIX_BLOCK not in text:
        raise RuntimeError("WEBUI_NAME suffix block not found in OpenWebUI environment")
    env_path.write_text(
        text.replace(ENV_SUFFIX_BLOCK, ENV_NO_SUFFIX_BLOCK, 1),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--env", type=Path, required=True)
    args = parser.parse_args()
    patch_index(args.index)
    patch_env(args.env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
