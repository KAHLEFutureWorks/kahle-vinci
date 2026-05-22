from __future__ import annotations

import argparse
from pathlib import Path


SCRIPT_TAG = '\t\t<script src="/static/kahle/kahle-branding.js" defer crossorigin="use-credentials"></script>'
CUSTOM_CSS_LINK = '\t\t<link rel="stylesheet" href="/static/kahle/kahle-branding.css" crossorigin="use-credentials" />'

ENV_SUFFIX_BLOCK = """WEBUI_NAME = os.environ.get('WEBUI_NAME', 'Open WebUI')
if WEBUI_NAME != 'Open WebUI':
    WEBUI_NAME += ' (Open WebUI)'"""

ENV_NO_SUFFIX_BLOCK = """WEBUI_NAME = os.environ.get('WEBUI_NAME', 'Open WebUI')"""


def patch_index(index_path: Path) -> None:
    text = index_path.read_text(encoding="utf-8")

    if "/static/kahle/kahle-branding.css" not in text:
        marker = '\t\t<link rel="stylesheet" href="/static/custom.css" crossorigin="use-credentials" />'
        if marker not in text:
            raise RuntimeError(f"custom.css marker not found in {index_path}")
        text = text.replace(marker, f"{marker}\n{CUSTOM_CSS_LINK}", 1)

    if "/static/kahle/kahle-branding.js" not in text:
        marker = '\t\t<script src="/static/loader.js" defer crossorigin="use-credentials"></script>'
        if marker not in text:
            raise RuntimeError(f"loader.js marker not found in {index_path}")
        text = text.replace(marker, f"{marker}\n{SCRIPT_TAG}", 1)

    index_path.write_text(text, encoding="utf-8")


def patch_env(env_path: Path) -> None:
    text = env_path.read_text(encoding="utf-8")
    if ENV_SUFFIX_BLOCK in text:
        text = text.replace(ENV_SUFFIX_BLOCK, ENV_NO_SUFFIX_BLOCK, 1)
    elif ENV_NO_SUFFIX_BLOCK not in text:
        raise RuntimeError(f"WEBUI_NAME assignment not found in {env_path}")
    env_path.write_text(text, encoding="utf-8")


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
