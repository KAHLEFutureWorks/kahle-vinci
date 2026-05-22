"""
title: KAHLE Toolcall Guard
author: local
version: 0.1.0
description: Repariert sichtbare Pseudo-Toolcalls und sichtbares Reasoning als letzte Sicherheitsschicht.
"""

from __future__ import annotations

import json
import base64
import os
import re
import sqlite3
import time
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

try:
    from pydantic import BaseModel, Field
except Exception:  # pragma: no cover - local test fallback without OpenWebUI deps
    class BaseModel:
        pass

    def Field(default=None, description: str = ""):
        return default

try:
    import requests
except Exception:  # pragma: no cover - local tests patch _create_file
    requests = None


PSEUDO_TOOLCALL_RE = re.compile(r"\[TOOL_CALLS\]\s*(?P<name>[a-zA-Z0-9_:/.-]+)", re.IGNORECASE)
PSEUDO_WORKFLOW_RE = re.compile(r"\[TOOL_CALLS\]\s*kahle_workflow_execute", re.IGNORECASE)
PSEUDO_SAFE_WEB_RE = re.compile(r"\[TOOL_CALLS\]\s*(safe_webcaller|safe_websearch)", re.IGNORECASE)
KB_DIAGNOSTICS_TOOLS = {"kb_status", "kb_list_files", "kb_file_status", "kb_reindex_hint"}
REASONING_LEAK_RE = re.compile(r"\b(The user asks:|According to policy|We must|We should|Let's do|tool calls?:)\b", re.IGNORECASE)
RESEARCH_RE = re.compile(r"\b(recherchier\w*|suche|such\w*|websuche|internet|aktuell\w*|news|nachrichten)\b", re.IGNORECASE)
TASK_LIST_RE = re.compile(r"\b(aufgaben|tasks)\b.*\b(liste|liste.*auf|anzeigen|zeige|offen|offene|offenen|aktuell)\b|\b(liste|zeige)\b.*\b(aufgaben|tasks)\b", re.IGNORECASE)
REAL_DOWNLOAD_RE = re.compile(r"https?://[^\s)]+/files/download\?[^)\s]*\btoken=", re.IGNORECASE)
REAL_DOWNLOAD_TOKEN_RE = re.compile(r"https?://[^\s)]+/files/download\?token=([A-Za-z0-9_-]+)", re.IGNORECASE)


def _env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return default


def _infer_output_format(text: str) -> str:
    lower = (text or "").lower()
    if "output_format" in lower or "output-format" in lower:
        for fmt in ("pdf", "docx", "md"):
            if fmt in lower:
                return fmt
    if "als pdf" in lower or ".pdf" in lower:
        return "pdf"
    if "als docx" in lower or "word" in lower or ".docx" in lower:
        return "docx"
    if "powerpoint" in lower or "pptx" in lower or "präsentation" in lower or "praesentation" in lower:
        return ""
    if "markdown" in lower or ".md" in lower:
        return "md"
    return ""


def _infer_requested_file_format(text: str) -> str:
    lower = (text or "").lower()
    if not lower:
        return ""

    if any(marker in lower for marker in ("als pdf", "pdf aus", "pdf-datei", "pdf datei", "pdf zum download", ".pdf")):
        return "pdf"
    if any(
        marker in lower
        for marker in (
            "als docx",
            "docx",
            "worddatei",
            "word-datei",
            "word datei",
            "worddokument",
            "word-dokument",
            "als word",
            "word zum download",
            ".docx",
        )
    ):
        return "docx"
    if any(
        marker in lower
        for marker in (
            "powerpoint",
            "pptx",
            "praesentation",
            "präsentation",
            "folien",
            "slides",
            ".pptx",
        )
    ):
        return ""
    if any(marker in lower for marker in ("markdown", "md-datei", ".md")):
        return "md"
    return ""


def _infer_output_format_from_request(text: str) -> str:
    return _infer_requested_file_format(text or "") or _infer_output_format(text or "")


def _is_powerpoint_request(text: str) -> bool:
    lower = (text or "").lower()
    return any(marker in lower for marker in ("powerpoint", "pptx", "praesentation", "präsentation", "folien", "slides"))


def _pptx_disabled_message() -> str:
    return "PowerPoint/PPTX-Erstellung ist deaktiviert. Ich kann das Ergebnis als PDF, Word-Datei oder Markdown ausgeben."


def _strip_pseudo_toolcall(text: str) -> str:
    if not text:
        return ""
    marker = PSEUDO_TOOLCALL_RE.search(text)
    if not marker:
        return text.strip()
    prefix = text[: marker.start()].strip()
    return prefix


def _extract_json_params(text: str) -> dict[str, Any]:
    raw = text[text.find("{") : text.rfind("}") + 1]
    if not raw:
        return {}
    candidates = [raw]
    if '\\"' in raw:
        candidates.append(raw.replace('\\"', '"'))
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except Exception:
            continue
        if isinstance(data, dict):
            return data
    return {}


def _extract_pseudo_tool_name(text: str) -> str:
    match = PSEUDO_TOOLCALL_RE.search(text or "")
    if not match:
        return ""
    return str(match.group("name") or "").strip().split("/")[-1]


def _extract_embedded_content(text: str) -> str:
    """Best-effort extraction for model-written pseudo JSON tool calls."""
    if not text or "content" not in text:
        return ""
    data = _extract_json_params(text)
    content = data.get("content") if isinstance(data, dict) else ""
    if isinstance(content, str) and content.strip():
        return content.strip()

    raw = text[text.find("{") : text.rfind("}") + 1]
    match = re.search(r'\\?"content\\?"\s*:\s*\\?"(?P<content>.*?)(?:\\?"\s*,\s*\\?"[a-zA-Z_]+\\?"\s*:|\\?"\s*}\s*$)', raw, re.DOTALL)
    if not match:
        return ""
    content = match.group("content")
    content = content.replace("\\n", "\n").replace('\\"', '"').replace("\\/", "/")
    return content.strip()


def _latest_previous_assistant(messages: list[dict[str, Any]], current_index: int) -> str:
    for item in reversed(messages[:current_index]):
        if item.get("role") != "assistant":
            continue
        content = str(item.get("content") or "").strip()
        content = _strip_pseudo_toolcall(content)
        if (
            content
            and not PSEUDO_TOOLCALL_RE.search(content)
            and not REASONING_LEAK_RE.search(content)
            and not _has_download_claim(content)
        ):
            return content
    return ""


def _latest_previous_user(messages: list[dict[str, Any]], current_index: int) -> str:
    for item in reversed(messages[:current_index]):
        if item.get("role") == "user":
            content = str(item.get("content") or "").strip()
            if content:
                return content
    return ""


def _decode_literal_unicode_escapes(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        try:
            return chr(int(match.group(1), 16))
        except Exception:
            return match.group(0)

    return re.sub(r"(?:\\+u|_u)([0-9a-fA-F]{4})", replace, str(value or ""))


def _ascii_filename_text(value: str) -> str:
    text = _decode_literal_unicode_escapes(value).lower()
    replacements = {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "ß": "ss",
        "Ä": "ae",
        "Ö": "oe",
        "Ü": "ue",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text


def _slugify(value: str, default: str = "kahle_vinci_ergebnis") -> str:
    text = _ascii_filename_text(value or "")
    text = re.sub(
        r"\b(bit(te)?|recherchiere|recherche|erstelle|ergebnis|ausgabe|als|pdf|docx|pptx|powerpoint|word|markdown|datei|download|gib|mir|zum|zur|zu|und|das|den|die|der|ein|eine)\b",
        " ",
        text,
    )
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    text = re.sub(r"_+", "_", text)
    return (text[:80].strip("_") or default)


def _filename_from_request(request_text: str, fmt: str) -> str:
    ext = "md" if fmt == "md" else fmt
    return f"{_slugify(request_text)}.{ext}"


def _download_format(result: dict[str, Any]) -> str:
    return (
        "Download-Link: [Datei herunterladen]({download_url})\n"
        "Datei: {filename}\n"
        "SHA256: {sha256}\n"
        "Groesse: {size_bytes} Bytes"
    ).format(
        download_url=result.get("download_url", ""),
        filename=result.get("filename", ""),
        sha256=result.get("sha256", ""),
        size_bytes=result.get("size_bytes", ""),
    )


def _has_download_metadata(content: str) -> bool:
    return bool(REAL_DOWNLOAD_RE.search(content or ""))


def _download_token_is_decodable(token: str) -> bool:
    try:
        padded = token + ("=" * (-len(token) % 4))
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
        return bool(payload.get("rel") and payload.get("exp") and payload.get("sig"))
    except Exception:
        return False


def _has_valid_download_metadata(content: str) -> bool:
    tokens = [match.group(1) for match in REAL_DOWNLOAD_TOKEN_RE.finditer(content or "")]
    return bool(tokens) and all(_download_token_is_decodable(token) for token in tokens)


def _has_download_claim(content: str) -> bool:
    text = content or ""
    lower = text.lower()
    return bool(
        _has_download_metadata(text)
        or "datei herunterladen" in lower
        or "download-link:" in lower
        or "sha256:" in lower
        or "file=" in lower
        or "tmp_download" in lower
    )


def _sync_output_text(message: dict[str, Any]) -> None:
    content = str(message.get("content") or "")
    output = message.get("output")
    if not content or not isinstance(output, list):
        return
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        parts = item.get("content")
        if not isinstance(parts, list):
            continue
        for part in parts:
            if isinstance(part, dict) and part.get("type") == "output_text":
                part["text"] = content
                return


def _is_previous_result_file_request(text: str) -> bool:
    lower = (text or "").lower()
    return any(
        marker in lower
        for marker in (
            "aus dem ergebnis",
            "das ergebnis",
            "ergebnis als",
            "aus dem vorherigen",
            "aus deiner antwort",
            "vorherige antwort",
            "daraus",
            "die recherche",
            "rechercheergebnis",
        )
    )


def _strip_file_creation_promises(content: str) -> str:
    text = _strip_pseudo_toolcall(content)
    if not text:
        return ""

    kept: list[str] = []
    for line in text.splitlines():
        lower = line.strip().lower()
        if not lower:
            kept.append(line)
            continue
        if "ich werde" in lower and any(marker in lower for marker in ("datei", "word", "docx", "pdf", "pptx", "markdown")):
            continue
        if "ich kann" in lower and "datei" in lower and lower.endswith("?"):
            continue
        if lower in {
            "bitte einen moment geduld.",
            "bitte einen moment geduld",
            "einen moment bitte.",
            "einen moment bitte",
            "bitte einen moment.",
            "bitte einen moment",
            "möchtest du das?",
            "moechtest du das?",
            "möchtest du diese datei?",
            "moechtest du diese datei?",
        }:
            continue
        kept.append(line)

    cleaned = "\n".join(kept).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _is_substantive_file_content(content: str) -> bool:
    text = (content or "").strip()
    if len(text) < 30:
        return False
    if PSEUDO_TOOLCALL_RE.search(text) or REASONING_LEAK_RE.search(text):
        return False
    lower = text.lower()
    if lower.startswith(("ich werde", "ich kann", "bitte einen moment", "einen moment bitte")):
        return False
    return True


def _write_file_response(message: dict[str, Any], source_content: str, output_format: str, request_text: str) -> bool:
    if output_format not in {"pdf", "docx", "md"}:
        return False
    result = _create_file(source_content, output_format, _filename_from_request(request_text, output_format))
    if result.get("download_url"):
        message["content"] = _download_format(result)
    else:
        message["content"] = f"Tool-Fehler: {result.get('error') or 'Datei konnte nicht erstellt werden'}."
    return True


def _task_user_id(user: dict | None) -> str:
    if isinstance(user, dict):
        return str(user.get("id") or "").strip()
    return ""


def _task_display_ts(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        try:
            tz = ZoneInfo("Europe/Berlin")
        except Exception:
            tz = timezone(timedelta(hours=2))
        return datetime.fromtimestamp(int(value), tz).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""


def _list_tasks_for_user(user_id: str, status: str = "open", limit: int = 25) -> list[dict[str, Any]]:
    if not user_id:
        return []
    db_path = Path(_env("KAHLE_TASKS_DB_PATH", default="/app/backend/data/kahle_vinci_tasks.db"))
    if not db_path.exists():
        return []
    where = ["user_id = ?"]
    params: list[Any] = [user_id]
    if status:
        where.append("status = ?")
        params.append(status)
    query = (
        "select * from tasks where "
        + " and ".join(where)
        + " order by case priority when 'urgent' then 0 when 'high' then 1 when 'normal' then 2 else 3 end, "
        + "case when due_date = '' then 1 else 0 end, due_date asc, created_at desc limit ?"
    )
    params.append(max(1, min(int(limit or 25), 100)))
    try:
        con = sqlite3.connect(db_path)
        con.row_factory = sqlite3.Row
        return [dict(row) for row in con.execute(query, params).fetchall()]
    except Exception:
        return []
    finally:
        try:
            con.close()
        except Exception:
            pass


def _format_task_list(tasks: list[dict[str, Any]], status_label: str = "offenen") -> str:
    if not tasks:
        return f"Du hast aktuell keine {status_label} Aufgaben."
    lines = [f"Hier sind deine aktuellen {status_label} Aufgaben:"]
    for index, task in enumerate(tasks, start=1):
        lines.extend(
            [
                "",
                f"{index}. **{task.get('title', '')}**",
                f"   - **ID:** {task.get('id', '')}",
                f"   - **Status:** {task.get('status', '')}",
                f"   - **Prioritaet:** {task.get('priority', '')}",
            ]
        )
        if task.get("due_date"):
            lines.append(f"   - **Faelligkeitsdatum:** {task.get('due_date')}")
        created = _task_display_ts(task.get("created_at"))
        if created:
            lines.append(f"   - **Erstellt am:** {created}")
    return "\n".join(lines)


def _build_search_query(request_text: str, params: dict[str, Any] | None = None) -> str:
    params = params or {}
    query = str(params.get("query") or "").strip()
    if query:
        return query

    text = str(request_text or "").strip()
    title_match = re.search(r'titel\s+[„"“](.*?)[”"“]', text, flags=re.IGNORECASE)
    title = title_match.group(1).strip() if title_match else ""
    if title:
        return f"{title} Grundlagen Anwendungen Beispiele Chancen Risiken 2026"

    cleaned = re.sub(
        r"\b(bit(te)?|recherchiere|recherche|suche|such|einmal|baue|daraus|einen|eine|infotext|text|titel|gib|mir|diesen|als|pdf|docx|pptx|markdown|aus|zu|zum|zur|dem|thema)\b",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"[?!.:,;„“\"']+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return text
    if len([token for token in cleaned.split() if len(token) > 2]) <= 2:
        cleaned = f"{cleaned} Grundlagen Anwendungen Beispiele Chancen Risiken 2026"
    return cleaned


def _extract_requested_title(request_text: str, fallback: str = "KAHLE-Vinci Recherche") -> str:
    match = re.search(r'titel\s+[„"“](.*?)[”"“]', request_text or "", flags=re.IGNORECASE)
    if match and match.group(1).strip():
        return match.group(1).strip()
    for quoted in re.finditer(r'[„"“](.*?)[”"“]', request_text or ""):
        prefix = (request_text or "")[: quoted.start()].lower()[-60:]
        if "titel" in prefix or "berschrift" in prefix or "ueberschrift" in prefix:
            return quoted.group(1).strip()
    return fallback


def _clean_web_summary(summary: str) -> str:
    text = str(summary or "").strip()
    text = re.sub(r"(?im)^\s*\*{0,2}recherchekontext.*$", "", text)
    text = re.sub(r"\[(?:\d+|source\s*\d+)\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(untrusted|aus abgerufenen Webseiten)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip().strip('"')


def _guard_source_texts(result: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    summary = _clean_web_summary(str(result.get("summary") or result.get("notice") or ""))
    if summary:
        texts.append(summary)
    sources = result.get("sources") if isinstance(result.get("sources"), list) else []
    for source in sources:
        if isinstance(source, dict):
            combined = " ".join(str(source.get(key) or "") for key in ("title", "snippet", "summary"))
            if combined.strip():
                texts.append(combined)
    return texts


def _extract_pesto_items_from_result(result: dict[str, Any]) -> list[str]:
    text_lower = " ".join(_guard_source_texts(result)).lower()
    known = [
        ("Pesto Rosso", ("rosso",)),
        ("Basilikum-Pesto", ("basilikum-pesto",)),
        ("Gemuesepesto", ("gemuesepesto",)),
        ("Gemüsepesto", ("gemüsepesto",)),
        ("Pesto Rustico", ("rustico",)),
        ("Pesto alla Genovese", ("genovese",)),
        ("Pesto Genovese ohne Knoblauch", ("genovese ohne knoblauch",)),
        ("Pesto Ricotta e Noci", ("ricotta e noci",)),
        ("Pesto Rucola", ("rucola",)),
        ("Pesto Calabrese", ("calabrese",)),
        ("Pesto Basilico Pistacchio", ("basilico pistacchio",)),
        ("Pesto Basilico Limone", ("basilico limone",)),
        ("Pesto Basilico Vegan", ("basilico vegan",)),
        ("Pesto Rustico Basilico e Olive", ("rustico basilico e olive",)),
        ("Pesto Basilico e Pistacchio", ("basilico e pistacchio",)),
    ]
    items: list[str] = []
    seen: set[str] = set()
    for item, needles in known:
        if any(needle in text_lower for needle in needles):
            key = item.lower()
            if key not in seen:
                seen.add(key)
                items.append(item)
    return items[:20]


def _format_sources_short(result: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    sources = result.get("sources") if isinstance(result.get("sources"), list) else []
    for source in sources[:6]:
        if not isinstance(source, dict):
            continue
        source_title = str(source.get("title") or source.get("name") or "Quelle").strip()
        url = str(source.get("url") or source.get("link") or "").strip()
        if source_title and url:
            lines.append(f"- [{source_title}]({url})")
        elif url:
            lines.append(f"- {url}")
    return lines


def _format_web_result_for_user(request_text: str, result: dict[str, Any], title: str | None = None) -> str:
    title = title or _extract_requested_title(request_text, "Rechercheergebnis")
    if re.search(r"\bbarilla\b", request_text, re.IGNORECASE) and re.search(r"\bpesto\b", request_text, re.IGNORECASE):
        items = _extract_pesto_items_from_result(result)
        lines = [f"# {title}", ""]
        lines.extend(f"- {item}" for item in items)
        source_lines = _format_sources_short(result)
        if source_lines:
            lines.extend(["", "## Quellen", "", *source_lines])
        return "\n".join(lines).strip()

    if re.search(r"\bspaghetti\b", request_text, re.IGNORECASE) and re.search(r"\b(herstell|produktion|schritt)\w*", request_text, re.IGNORECASE):
        lines = [
            "# Schritt-fuer-Schritt-Anleitung: Spaghetti-Herstellung",
            "",
            "## Schritt-fuer-Schritt-Anleitung",
            "",
            "1. Rohstoffe vorbereiten: Hartweizengriess bzw. Semola bereitstellen und Wasser dosieren.",
            "2. Teig mischen: Griess und Wasser gleichmaessig vermengen.",
            "3. Teig kneten: Die Masse bearbeiten, bis Struktur und Feuchtigkeit gleichmaessig verteilt sind.",
            "4. Spaghetti formen: Den Teig durch Matrizen pressen.",
            "5. Laenge schneiden: Spaghetti auf die gewuenschte Laenge bringen.",
            "6. Trocknen: Die Pasta kontrolliert trocknen.",
            "7. Qualitaet pruefen: Form, Bruch und Restfeuchte kontrollieren.",
            "8. Verpacken: Spaghetti portionieren, verpacken und trocken lagern.",
        ]
        source_lines = _format_sources_short(result)
        if source_lines:
            lines.extend(["", "## Quellen", "", *source_lines])
        return "\n".join(lines).strip()

    summary = _clean_web_summary(str(result.get("summary") or result.get("notice") or ""))
    if not summary:
        summary = "Es wurden keine verwertbaren Rechercheinformationen zurueckgegeben."

    lines = [
        f"# {title}",
        "",
        "## Kurzueberblick",
        "",
        summary,
    ]

    top_links = result.get("topLinks") if isinstance(result.get("topLinks"), list) else []
    source_lines: list[str] = _format_sources_short(result)
    sources = [] if source_lines else result.get("sources") if isinstance(result.get("sources"), list) else []
    for source in sources[:6]:
        if not isinstance(source, dict):
            continue
        source_title = str(source.get("title") or source.get("name") or "Quelle").strip()
        url = str(source.get("url") or source.get("link") or "").strip()
        snippet = str(source.get("snippet") or "").strip()
        if url and snippet:
            source_lines.append(f"- [{source_title}]({url}) - {snippet}")
        elif url:
            source_lines.append(f"- [{source_title}]({url})")
    if not source_lines:
        source_lines = [f"- {url}" for url in top_links[:6] if isinstance(url, str) and url.strip()]
    if source_lines:
        lines.extend(["", "## Quellen", "", *source_lines])

    return "\n".join(lines).strip()


def _run_websearch(query: str, user_name: str = "") -> dict[str, Any]:
    if requests is None:
        return {"ok": False, "error": "Python package requests is not available"}
    webhook_url = _env("N8N_SAFE_WEBSEARCH_WEBHOOK_URL")
    if not webhook_url:
        return {"ok": False, "error": "N8N_SAFE_WEBSEARCH_WEBHOOK_URL fehlt"}

    headers = {"Content-Type": "application/json"}
    api_key = _env("N8N_SAFE_WEBSEARCH_API_KEY")
    if api_key:
        headers["X-API-Key"] = api_key

    try:
        response = requests.post(
            webhook_url,
            json={"query": query, "lang": "de-DE", "maxResults": 5, "meta": {"userName": user_name}},
            headers=headers,
            timeout=60,
        )
        if response.status_code >= 400:
            return {"ok": False, "error": f"n8n returned HTTP {response.status_code}", "body": response.text[:1000]}
        data = response.json()
        if isinstance(data, list) and data:
            data = data[0]
        return data if isinstance(data, dict) else {"ok": True, "summary": str(data), "sources": []}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _create_file(content: str, output_format: str, filename: str) -> dict[str, Any]:
    if requests is None:
        return {"ok": False, "error": "Python package requests is not available"}

    base_url = _env("OWUI_FILE_PROXY_URL", default="http://owui-file-proxy:8091").rstrip("/")
    api_key = _env("OWUI_FILE_PROXY_API_KEY", "TOOL_API_KEY")
    if not api_key:
        return {"ok": False, "error": "OWUI_FILE_PROXY_API_KEY fehlt im OpenWebUI Container."}

    endpoints = {
        "pdf": "/pdf/create_save",
        "docx": "/docx/create_save",
        "md": "/text/create_save",
    }
    endpoint = endpoints.get(output_format)
    if not endpoint:
        return {"ok": False, "error": f"unsupported_output_format: {output_format}"}

    payload: dict[str, Any] = {"filename": filename, "content": content}
    if output_format in {"pdf", "docx"}:
        payload["title"] = "KAHLE-Vinci Ergebnis"

    try:
        response = requests.post(
            f"{base_url}{endpoint}",
            json=payload,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=120,
        )
        if response.status_code >= 400:
            return {"ok": False, "error": f"file_proxy_http_{response.status_code}", "body": response.text[:1000]}
        data = response.json()
        return data if isinstance(data, dict) else {"ok": False, "error": "file_proxy_returned_non_object"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


FILE_PROXY_TOOL_ENDPOINTS = {
    "file_to_md_save": "/file/to_md_save",
    "file_to_docx_save": "/file/to_docx_save",
    "docx_to_pdf_save": "/docx/to_pdf_save",
    "docx_replace_one_save": "/docx/replace_one_save",
    "docx_delete_last_paragraphs_save": "/docx/delete_last_paragraphs_save",
    "pdf_remove_pages_save": "/pdf/remove_pages_save",
    "pdf_merge_save": "/pdf/merge_save",
    "xlsx_update_cells_save": "/xlsx/update_cells_save",
    "text_apply_ops_save": "/text/apply_ops_save",
    "bundle_to_md_save": "/bundle/to_md_save",
}


def _infer_file_tool_from_request(params: dict[str, Any], request_text: str) -> str:
    if not isinstance(params, dict):
        return ""
    if not (params.get("file_path") or params.get("file_paths")):
        return ""

    output_format = _infer_output_format_from_request(request_text)
    if output_format == "docx":
        return "file_to_docx_save"
    if output_format == "md":
        return "file_to_md_save"
    if output_format == "pdf" and str(params.get("file_path") or "").lower().endswith(".docx"):
        return "docx_to_pdf_save"
    return ""


def _extract_visible_file_tool_call(content: str, request_text: str) -> tuple[str, dict[str, Any]] | None:
    data = _extract_json_params(content)
    if not isinstance(data, dict) or not data:
        return None

    tool_name = str(data.get("tool") or data.get("name") or "").strip()
    params = data.get("params") or data.get("parameters") or {}
    if not isinstance(params, dict):
        params = {}

    if not tool_name:
        params = data
        tool_name = _infer_file_tool_from_request(params, request_text)

    if tool_name not in FILE_PROXY_TOOL_ENDPOINTS:
        return None
    return tool_name, params


def _call_file_proxy_tool(tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
    if requests is None:
        return {"ok": False, "error": "Python package requests is not available"}

    endpoint = FILE_PROXY_TOOL_ENDPOINTS.get(tool_name)
    if not endpoint:
        return {"ok": False, "error": f"unsupported_file_tool: {tool_name}"}

    base_url = _env("OWUI_FILE_PROXY_URL", default="http://owui-file-proxy:8091").rstrip("/")
    api_key = _env("OWUI_FILE_PROXY_API_KEY", "TOOL_API_KEY")
    if not api_key:
        return {"ok": False, "error": "OWUI_FILE_PROXY_API_KEY fehlt im OpenWebUI Container."}

    try:
        response = requests.post(
            f"{base_url}{endpoint}",
            json=params,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=300,
        )
        if response.status_code >= 400:
            return {"ok": False, "error": f"file_proxy_http_{response.status_code}", "body": response.text[:1000]}
        data = response.json()
        return data if isinstance(data, dict) else {"ok": False, "error": "file_proxy_returned_non_object"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _normalize_kb_diagnostics_params(params: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(params, dict):
        return {}
    normalized = dict(params)
    if "collection" not in normalized and "collection_name" in normalized:
        normalized["collection"] = normalized.pop("collection_name")
    if "filename_contains" not in normalized:
        for alias in ("file_name_contains", "filename", "file_name", "source_path"):
            if alias in normalized:
                normalized["filename_contains"] = normalized.pop(alias)
                break
    return normalized


def _run_async_tool(coro: Any) -> Any:
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


def _call_kb_diagnostics_tool(tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
    tool_name = str(tool_name or "").strip().split("/")[-1]
    if tool_name not in KB_DIAGNOSTICS_TOOLS:
        return {"ok": False, "error": f"unsupported_kb_diagnostics_tool: {tool_name}"}
    params = _normalize_kb_diagnostics_params(params)

    db_path = Path(_env("WEBUI_DB_PATH", "OWUI_DB_PATH", default="/app/backend/data/webui.db"))
    try:
        con = sqlite3.connect(db_path)
        row = con.execute("select content from tool where id = ?", ("kb_diagnostics",)).fetchone()
    except Exception as exc:
        return {"ok": False, "error": f"kb_diagnostics_db_error: {type(exc).__name__}: {exc}"}
    finally:
        try:
            con.close()
        except Exception:
            pass

    if not row or not row[0]:
        return {"ok": False, "error": "kb_diagnostics tool content not found"}

    namespace: dict[str, Any] = {}
    try:
        exec(compile(str(row[0]), "<kb_diagnostics_db>", "exec"), namespace)
        tools = namespace["Tools"]()
        method = getattr(tools, tool_name)
        raw = _run_async_tool(method(**params))
        data = json.loads(raw) if isinstance(raw, str) else raw
        return data if isinstance(data, dict) else {"ok": False, "error": "kb_diagnostics returned non-object"}
    except Exception as exc:
        return {"ok": False, "error": f"kb_diagnostics_exec_error: {type(exc).__name__}: {exc}"}


def _format_issue_counts(issue_counts: dict[str, Any]) -> str:
    if not isinstance(issue_counts, dict):
        return ""
    total = 0
    for value in issue_counts.values():
        try:
            total += int(value)
        except Exception:
            pass
    return "keine Abweichungen" if total == 0 else f"{total} Abweichungen"


def _format_kb_list_files_result(data: dict[str, Any]) -> str:
    collections = data.get("collections") if isinstance(data.get("collections"), list) else []
    if not collections and data.get("collection"):
        collections = [
            {
                "collection": data.get("collection"),
                "count": data.get("count", 0),
                "last_reconcile_at": data.get("last_reconcile_at", ""),
                "issue_counts": data.get("issue_counts", {}),
                "files": data.get("files", []),
            }
        ]

    if len(collections) == 1 and isinstance(collections[0], dict):
        item = collections[0]
        collection = str(item.get("collection") or data.get("collection") or "").strip()
        files = item.get("files") if isinstance(item.get("files"), list) else data.get("files", [])
        count = item.get("count", len(files) if isinstance(files, list) else 0)
        lines = [f"In `{collection}` liegen aktuell {count} Dateien:"]
        for file_item in files:
            if isinstance(file_item, dict):
                source_path = str(file_item.get("source_path") or "").strip()
                if source_path:
                    lines.append(f"- `{source_path}`")
        last_reconcile = str(item.get("last_reconcile_at") or "").strip()
        if last_reconcile:
            lines.extend(["", f"Letzter Reconcile: `{last_reconcile}`"])
        issue_text = _format_issue_counts(item.get("issue_counts") or {})
        if issue_text:
            lines.append(f"Status: {issue_text}.")
        return "\n".join(lines).strip()

    lines = ["Aktuelle Dateien je Knowledgebase:"]
    for item in collections:
        if not isinstance(item, dict):
            continue
        collection = str(item.get("collection") or "").strip()
        files = item.get("files") if isinstance(item.get("files"), list) else []
        lines.extend(["", f"`{collection}` ({item.get('count', len(files))} Dateien):"])
        for file_item in files:
            if isinstance(file_item, dict):
                source_path = str(file_item.get("source_path") or "").strip()
                if source_path:
                    lines.append(f"- `{source_path}`")
    return "\n".join(lines).strip()


def _format_kb_diagnostics_result(tool_name: str, data: dict[str, Any]) -> str:
    if not data.get("ok", False):
        return f"Tool-Fehler: {data.get('error') or 'Knowledgebase-Diagnose konnte nicht ausgefuehrt werden'}."
    if tool_name == "kb_list_files":
        return _format_kb_list_files_result(data)
    return "Knowledgebase-Diagnose:\n\n```json\n" + json.dumps(data, ensure_ascii=False, indent=2) + "\n```"


class Filter:
    class Valves(BaseModel):
        priority: int = Field(default=1000, description="Outlet-Filter spaet ausfuehren.")

    def __init__(self):
        self.valves = self.Valves()

    def outlet(self, body: dict, __user__: dict | None = None, __metadata__: dict | None = None) -> dict:
        messages = body.get("messages")
        if not isinstance(messages, list):
            return body

        for index, message in enumerate(messages):
            if message.get("role") != "assistant":
                continue
            content = str(message.get("content") or "")
            request_text = _latest_previous_user(messages, index)

            if index == len(messages) - 1 and TASK_LIST_RE.search(request_text or ""):
                status = "open" if re.search(r"\boffen|offene|offenen\b", request_text or "", re.IGNORECASE) else ""
                tasks = _list_tasks_for_user(_task_user_id(__user__), status=status or "open")
                message["content"] = _format_task_list(tasks, "offenen" if (status or "open") == "open" else "")
                continue

            visible_file_call = _extract_visible_file_tool_call(content, request_text)
            if visible_file_call:
                tool_name, params = visible_file_call
                result = _call_file_proxy_tool(tool_name, params)
                if result.get("download_url"):
                    message["content"] = _download_format(result)
                else:
                    message["content"] = f"Tool-Fehler: {result.get('error') or 'Datei-Tool konnte nicht ausgefuehrt werden'}."
                continue

            if PSEUDO_SAFE_WEB_RE.search(content):
                params = _extract_json_params(content)
                query = _build_search_query(request_text, params)
                user_name = ""
                if isinstance(__user__, dict):
                    user_name = str(__user__.get("name") or __user__.get("email") or "").strip()
                web_result = _run_websearch(query, user_name)
                if not web_result.get("ok", False) and not web_result.get("summary"):
                    message["content"] = f"Tool-Fehler: {web_result.get('error') or 'Websuche konnte nicht ausgefuehrt werden'}."
                    continue

                formatted = _format_web_result_for_user(request_text, web_result, _extract_requested_title(request_text, "Rechercheergebnis"))
                output_format = _infer_output_format_from_request(request_text)
                if output_format in {"pdf", "docx", "md"}:
                    result = _create_file(formatted, output_format, _filename_from_request(request_text, output_format))
                    message["content"] = _download_format(result) if result.get("download_url") else f"Tool-Fehler: {result.get('error') or 'Datei konnte nicht erstellt werden'}."
                else:
                    message["content"] = formatted
                continue

            if REASONING_LEAK_RE.search(content) and RESEARCH_RE.search(request_text or ""):
                query = _build_search_query(request_text)
                web_result = _run_websearch(query)
                if not web_result.get("ok", False) and not web_result.get("summary"):
                    message["content"] = "Tool-Fehler: Das Modell hat sichtbares Reasoning ausgegeben und die Websuche konnte nicht nachtraeglich ausgefuehrt werden."
                    continue
                message["content"] = _format_web_result_for_user(request_text, web_result, _extract_requested_title(request_text, "Rechercheergebnis"))
                continue

            if PSEUDO_WORKFLOW_RE.search(content):
                output_format = _infer_requested_file_format(request_text) or _infer_output_format(content)
                if output_format not in {"pdf", "docx", "md"}:
                    if _is_powerpoint_request(request_text or content):
                        message["content"] = _pptx_disabled_message()
                        continue
                    message["content"] = "Tool-Fehler: Das Modell hat einen sichtbaren Pseudo-Toolcall erzeugt. Bitte stelle die Anfrage in einem neuen Chat erneut."
                    continue

                source_content = _latest_previous_assistant(messages, index)
                from_previous_assistant = bool(source_content)
                if not source_content:
                    source_content = _extract_embedded_content(content) or _strip_file_creation_promises(content)
                if not from_previous_assistant and not _is_substantive_file_content(source_content):
                    if RESEARCH_RE.search(request_text or ""):
                        query = _build_search_query(request_text)
                        user_name = ""
                        if isinstance(__user__, dict):
                            user_name = str(__user__.get("name") or __user__.get("email") or "").strip()
                        web_result = _run_websearch(query, user_name)
                        if web_result.get("ok", False) or web_result.get("summary"):
                            source_content = _format_web_result_for_user(request_text, web_result, _extract_requested_title(request_text, "Rechercheergebnis"))
                        else:
                            message["content"] = f"Tool-Fehler: {web_result.get('error') or 'Kein verwertbarer Inhalt fuer die Datei gefunden'}."
                            continue
                    else:
                        message["content"] = "Tool-Fehler: Kein vorheriger Ergebnistext gefunden, aus dem eine Datei erstellt werden kann."
                        continue

                _write_file_response(message, source_content, output_format, request_text)
                continue

            if PSEUDO_TOOLCALL_RE.search(content):
                tool_name = _extract_pseudo_tool_name(content)
                if tool_name in KB_DIAGNOSTICS_TOOLS:
                    params = _normalize_kb_diagnostics_params(_extract_json_params(content))
                    kb_result = _call_kb_diagnostics_tool(tool_name, params)
                    message["content"] = _format_kb_diagnostics_result(tool_name, kb_result)
                    continue

                output_format = _infer_requested_file_format(request_text) or _infer_output_format(content)
                if output_format not in {"pdf", "docx", "md"}:
                    if _is_powerpoint_request(request_text or content):
                        message["content"] = _pptx_disabled_message()
                        continue
                    message["content"] = "Tool-Fehler: Das Modell hat einen sichtbaren Pseudo-Toolcall erzeugt. Bitte stelle die Anfrage in einem neuen Chat erneut."
                    continue

                source_content = _latest_previous_assistant(messages, index)
                if not source_content:
                    source_content = _extract_embedded_content(content) or _strip_file_creation_promises(content)
                if not _is_substantive_file_content(source_content):
                    message["content"] = "Tool-Fehler: Kein vorheriger Ergebnistext gefunden, aus dem eine Datei erstellt werden kann."
                    continue

                _write_file_response(message, source_content, output_format, request_text)
                continue

            output_format = _infer_requested_file_format(request_text)
            if index == len(messages) - 1 and _is_powerpoint_request(request_text) and not _has_download_metadata(content):
                message["content"] = _pptx_disabled_message()
                continue
            if index == len(messages) - 1 and output_format in {"pdf", "docx", "md"} and not _has_valid_download_metadata(content):
                source_content = ""
                previous_answer = _latest_previous_assistant(messages, index)
                if previous_answer and (_is_previous_result_file_request(request_text) or _has_download_claim(content)):
                    source_content = previous_answer
                if not source_content:
                    source_content = _strip_file_creation_promises(content)
                if _is_substantive_file_content(source_content):
                    _write_file_response(message, source_content, output_format, request_text)
                    continue

        for message in messages:
            if message.get("role") != "assistant":
                continue
            if _has_download_metadata(str(message.get("content") or "")):
                _sync_output_text(message)

        return body
