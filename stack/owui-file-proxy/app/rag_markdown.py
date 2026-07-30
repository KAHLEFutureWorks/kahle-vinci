from __future__ import annotations

import re
from datetime import date


_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\r?\n.*?\r?\n---[ \t]*(?:\r?\n|$)", re.DOTALL)
_H1_RE = re.compile(r"(?m)^#\s+(.+?)\s*$")


def _one_year_later(value: date) -> date:
    try:
        return value.replace(year=value.year + 1)
    except ValueError:
        return value.replace(year=value.year + 1, month=2, day=28)


def _display_title(content: str, requested_title: str, document_id: str) -> str:
    candidate = (requested_title or "").strip()
    if candidate and candidate.casefold() not in {"konvertiert", "masterkontext", "dokument"}:
        return candidate
    match = _H1_RE.search(content or "")
    if match:
        return match.group(1).strip()
    stem = re.sub(r"\.md$", "", document_id, flags=re.IGNORECASE)
    return re.sub(r"[_-]+", " ", stem).strip() or "Dokument"


def _yaml_scalar(value: str) -> str:
    normalized = " ".join((value or "").replace("\r", " ").replace("\n", " ").split())
    if (
        normalized
        and not re.search(r"[:#\[\]{},&*!|>'\"%@`]", normalized)
        and not normalized.startswith(("-", "?", " "))
        and normalized.casefold() not in {"null", "true", "false", "~"}
    ):
        return normalized
    return "'" + normalized.replace("'", "''") + "'"


def ensure_rag_frontmatter(
    content: str,
    *,
    title: str,
    document_id: str,
    today: date,
) -> str:
    body = _FRONTMATTER_RE.sub("", (content or "").lstrip("\ufeff")).lstrip()
    resolved_title = _display_title(body, title, document_id)
    valid_until = _one_year_later(today).isoformat()
    header = "\n".join(
        (
            "---",
            f"title: {_yaml_scalar(resolved_title)}",
            f"document_id: {_yaml_scalar(document_id)}",
            "owner:",
            "status: active",
            f"valid_until: {valid_until}",
            "notify_before_days: 14",
            "rag_index: true",
            "---",
        )
    )
    return f"{header}\n\n{body.rstrip()}\n"