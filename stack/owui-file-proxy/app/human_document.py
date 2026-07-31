from __future__ import annotations

import re


_PAGE_RE = re.compile(r"^<!--\s*Seite\s+(\d+)\s*-->$", re.IGNORECASE)
_FILE_HEADING_RE = re.compile(r"^#{1,6}\s+Datei:\s+", re.IGNORECASE)
_GENERIC_TITLES = {"konvertiert", "dokument", "masterkontext"}
_CALLOUT_RE = re.compile(r"^(hinweis|achtung|wichtig|warnung)\s*:", re.IGNORECASE)


def infer_human_title(content: str, requested_title: str, fallback_stem: str) -> str:
    requested = (requested_title or "").strip()
    if requested and requested.casefold() not in _GENERIC_TITLES:
        return requested
    for raw in (content or "").splitlines():
        line = raw.strip()
        if not line or line.startswith(("<!--", "```")) or _FILE_HEADING_RE.match(line):
            continue
        line = re.sub(r"^#{1,6}\s+", "", line).strip()
        if line.casefold() in _GENERIC_TITLES or re.fullmatch(r"Stand\s+\d{1,2}\.\d{1,2}\.\d{4}", line, re.IGNORECASE):
            continue
        if 8 <= len(line) <= 180:
            return line
    stem = re.sub(r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}_", "", fallback_stem, flags=re.IGNORECASE)
    stem = re.sub(r"\s*\(\d+\)\s*$", "", stem)
    return re.sub(r"[_-]+", " ", stem).strip() or "Dokument"


def prepare_human_markdown(content: str, *, title: str) -> str:
    output: list[str] = []
    page_number = 0
    first_on_page = False
    in_code = False

    for raw in (content or "").splitlines():
        stripped = raw.strip()
        page_match = _PAGE_RE.match(stripped)
        if page_match and not in_code:
            page_number = int(page_match.group(1))
            first_on_page = True
            if output and output[-1] != "":
                output.append("")
            continue
        if stripped.startswith("```"):
            in_code = not in_code
            output.append(raw.rstrip())
            continue
        if in_code:
            output.append(raw.rstrip())
            continue
        if _FILE_HEADING_RE.match(stripped):
            continue
        heading_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading_match and heading_match.group(2).strip().casefold() in _GENERIC_TITLES:
            continue
        if first_on_page and stripped:
            first_on_page = False
            plain = re.sub(r"^#{1,6}\s+", "", stripped).strip()
            if page_number == 1 and plain.casefold() == title.casefold():
                continue
            if page_number > 1 and not stripped.startswith(("#", ">", "|")) and len(stripped) <= 180:
                output.append(f"## {stripped}")
                continue
        if _CALLOUT_RE.match(stripped):
            output.append(f"> {stripped}")
        else:
            output.append(raw.rstrip())

    cleaned = "\n".join(output)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned + "\n"
