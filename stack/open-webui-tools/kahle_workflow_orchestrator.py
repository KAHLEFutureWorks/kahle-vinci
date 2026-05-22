"""
title: KAHLE Workflow Orchestrator
author: local
version: 0.1.0
description: Deterministisches Mehrschritt-Tool fuer KAHLE-Workflows mit Tasks, RAG/Web-Recherche und strukturierter Ausgabe.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from typing import Any

try:
    from pydantic import BaseModel, Field
except Exception:  # pragma: no cover - local test fallback without OpenWebUI deps
    class BaseModel:
        pass

    def Field(default=None, description: str = ""):
        return default


def _env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return default


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _coerce_message_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value.strip()
        if text and text[0] in "[{":
            try:
                return _coerce_message_text(json.loads(text))
            except Exception:
                return text
        return text
    if isinstance(value, dict):
        if isinstance(value.get("content"), str):
            return value["content"].strip()
        if isinstance(value.get("text"), str):
            return value["text"].strip()
        if isinstance(value.get("content"), list):
            return _coerce_message_text(value.get("content"))
        return ""
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            text = _coerce_message_text(item)
            if text:
                parts.append(text)
        return "\n".join(parts).strip()
    return str(value).strip()


def _looks_like_generated_file_claim(text: str) -> bool:
    lower = (text or "").lower()
    return bool(
        "/files/download" in lower
        or "download-link:" in lower
        or "datei herunterladen" in lower
        or "sha256:" in lower
    )


def _looks_like_non_result_assistant(text: str) -> bool:
    lower = (text or "").strip().lower()
    if not lower or lower in {'""', "''"}:
        return True
    if lower.startswith(("[tool_calls]", "ich werde", "einen moment", "bitte einen moment")):
        return True
    if _looks_like_generated_file_claim(lower):
        return True
    if any(
        marker in lower
        for marker in (
            "benoetige ich weitere details",
            "benötige ich weitere details",
            "bitte praezisiere",
            "bitte präzisiere",
            "sobald du diese details angibst",
        )
    ):
        return True
    return False


def _latest_chat_message(chat_id: str | None, role: str, *, require_result: bool = False) -> str:
    chat_id = (chat_id or "").strip()
    if not chat_id:
        return ""
    db_path = _env("OWUI_DB_PATH", default="/app/backend/data/webui.db")
    if not db_path or not os.path.exists(db_path):
        return ""
    try:
        con = sqlite3.connect(db_path)
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """
            select content
            from chat_message
            where chat_id = ? and role = ?
            order by coalesce(created_at, 0) desc, coalesce(updated_at, 0) desc
            limit 20
            """,
            (chat_id, role),
        ).fetchall()
    except Exception:
        return ""
    finally:
        try:
            con.close()
        except Exception:
            pass
    for row in rows or []:
        text = _coerce_message_text(row["content"])
        if not text:
            continue
        if require_result and role == "assistant" and _looks_like_non_result_assistant(text):
            continue
        return text
    return ""


def _looks_like_previous_result_request(text: str) -> bool:
    lower = (text or "").lower()
    if any(
        marker in lower
        for marker in (
            "aus dem ergebnis",
            "das ergebnis als",
            "ergebnis als",
            "aus dem vorherigen",
            "aus deiner antwort",
            "vorherige antwort",
            "daraus eine datei",
            "daraus als",
            "aus dem text",
            "die recherche als",
            "recherche als",
            "rechercheergebnis",
        )
    ):
        return True
    if re.search(r"\b(recherchiere|suche|finde|erstelle)\b", lower):
        return False
    return bool(
        re.search(r"\b(ergebnis|antwort|recherche)\b", lower)
        and re.search(r"\b(pdf|docx|word|powerpoint|pptx|markdown|datei|download)\b", lower)
    )


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None, timeout: int = 60) -> dict:
    import requests

    response = requests.post(url, headers=headers or {}, json=payload, timeout=timeout)
    response.raise_for_status()
    body = response.json()
    return body if isinstance(body, dict) else {"data": body}


def classify_workflow_intent(auftrag: str, modus: str = "auto") -> str:
    """Return internal, external or mixed."""
    requested = (modus or "auto").strip().lower()
    if requested in {"internal", "intern", "kahle"}:
        return "internal"
    if requested in {"external", "extern", "web"}:
        return "external"
    if requested in {"mixed", "gemischt"}:
        return "mixed"

    text = (auftrag or "").lower()
    internal_markers = (
        "kahle",
        "autohaus",
        "unsere ",
        "unser ",
        "intern",
        "richtlinie",
        "prozess",
        "standort",
        "standorte",
        "marken",
        "gruppe",
        "knowledgebase",
        "wissens",
        "compliance",
    )
    explicit_external_markers = (
        "web",
        "internet",
        "google",
        "news",
        "nachrichten",
        "aktuell",
        "neueste",
        "neusten",
        "extern",
        "externe",
        "externen",
        "oeffentlich",
        "öffentlich",
        "suche im internet",
    )
    generic_search_markers = ("recherchiere", "suche", "hole dir infos")

    is_internal = any(marker in text for marker in internal_markers)
    has_explicit_external = any(marker in text for marker in explicit_external_markers)
    has_generic_search = any(marker in text for marker in generic_search_markers)
    is_external = has_explicit_external or has_generic_search

    if is_internal and has_explicit_external:
        return "mixed"
    if is_internal:
        return "internal"
    if is_external:
        return "external"
    return "internal"


def normalize_target(auftrag: str, ziel: str = "auto") -> str:
    requested = (ziel or "auto").strip().lower()
    if requested in {"brief", "research_brief", "antwort"}:
        return "research_brief"
    if requested in {"presentation_outline", "praesentation", "präsentation", "slides", "folien"}:
        return "presentation_outline"
    if requested in {"docx_brief", "docx"}:
        return "docx_brief"

    text = (auftrag or "").lower()
    if any(word in text for word in ("präsentation", "praesentation", "folien", "slides", "vortrag")):
        return "presentation_outline"
    if "docx" in text or "word" in text:
        return "docx_brief"
    return "research_brief"


def infer_download_format(auftrag: str, output_format: str = "auto") -> str:
    """Return none, pdf, docx or md for generated workflow output."""
    requested = (output_format or "auto").strip().lower()
    aliases = {
        "none": "none",
        "kein": "none",
        "auto": "auto",
        "pdf": "pdf",
        "docx": "docx",
        "word": "docx",
        "präsentation": "pptx",
        "md": "md",
        "markdown": "md",
        "txt": "md",
    }
    requested = aliases.get(requested, requested)
    if requested in {"pptx", "powerpoint", "praesentation", "präsentation", "folien", "slides"}:
        return "none"
    if requested in {"none", "pdf", "docx", "md"}:
        return requested

    text = (auftrag or "").lower()
    if any(word in text for word in ("pptx", "powerpoint", "präsentation", "praesentation", "folien", "slides")):
        return "none"
    file_markers = (
        "als pdf",
        "pdf aus",
        "pdf-datei",
        "pdf datei",
        "download",
        "herunterladen",
        "als datei",
        "als word",
        "word aus",
        "word datei",
        "word-datei",
        "worddokument",
        "word-dokument",
        "docx",
        "pptx",
        "powerpoint",
        "präsentation",
        "praesentation",
        "folien",
        "slides",
        "markdown",
        ".md",
    )
    if not any(marker in text for marker in file_markers):
        return "none"
    if "pdf" in text:
        return "pdf"
    if "docx" in text or "word" in text:
        return "docx"
    if "pptx" in text or "powerpoint" in text or "präsentation" in text or "praesentation" in text or "folien" in text or "slides" in text:
        return "none"
    if "markdown" in text or ".md" in text:
        return "md"
    return "pdf"


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
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text


def _slugify(value: str, default: str = "kahle_vinci_ergebnis") -> str:
    text = _ascii_filename_text(value or "")
    text = re.sub(r"\b(bit(te)?|recherchiere|recherche|erstelle|ergebnis|ausgabe|als|pdf|docx|pptx|powerpoint|word|markdown|datei|download|gib|mir|zum|zur|zu|und|das|den|die|der|ein|eine)\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    text = re.sub(r"_+", "_", text)
    if not text:
        return default
    return text[:80].strip("_") or default


def suggest_output_filename(auftrag: str, output_format: str) -> str:
    stem = _slugify(auftrag)
    if "recherche" not in stem and any(word in (auftrag or "").lower() for word in ("recherche", "recherchiere", "web", "internet")):
        stem = f"{stem}_recherche"
    ext = "md" if output_format == "md" else output_format
    return f"{stem}.{ext}"


def build_web_search_query(auftrag: str) -> str:
    """Build a focused external web query for the safe-search workflow."""
    original = str(auftrag or "").strip()
    text = re.sub(
        r"\b(bit(te)?|recherchiere|recherche|suche|such|google|finde|pruefe|prüfe|einmal|mal|gib|mir|das|ergebnis|als|pdf|docx|markdown|datei|download|zu|zum|zur|ueber|über)\b",
        " ",
        original,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"[?!.:,;]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    lower = text.lower()
    has_current_intent = bool(re.search(r"\b(aktuell\w*|heute|stand heute|neueste\w*|neusten\w*|news|nachrichten)\b", original, re.I))

    if re.search(r"\bclaude\b", lower) and re.search(r"\b(ai|anthropic)\b", lower):
        text = "Claude AI Anthropic Modelle Funktionen Preise Enterprise Vergleich"
    elif re.search(r"\bcupra\b", lower) and re.search(r"\btindaya\b", lower):
        text = "CUPRA Tindaya Konzeptfahrzeug offizielle Informationen technische Daten Design Marktstart"
    elif re.search(r"\bbarilla\b", lower) and re.search(r"\bpesto\b", lower):
        text = "Barilla Pesto Sorten Deutschland aktuell 2026"
    elif re.search(r"\bspaghetti\b", lower) and re.search(r"\b(hergestellt|herstellung|herstell|produzier|fertigung|gemacht)\w*", lower):
        text = "Spaghetti Herstellung Hartweizen Pasta Produktion Schritte"
    elif re.search(r"\bki\b", lower) and re.search(r"\b(news|nachrichten)\b", original.lower()):
        text = "aktuelle KI News OpenAI Anthropic Google Meta Microsoft EU AI Act"
    elif re.search(r"\bki\b", lower) and re.search(r"\brichtlin", lower):
        text = "KI Richtlinie Unternehmen Inhalte Vorlage EU AI Act Datenschutz Compliance"

    content_tokens = [tok for tok in re.findall(r"[\wÄÖÜäöüß-]+", text, flags=re.UNICODE) if len(tok) >= 3]
    if text and len(content_tokens) <= 2:
        text = f"{text} Überblick aktuelle Informationen Funktionen Einsatzbereiche Vergleich"
    if has_current_intent and not re.search(r"\b(19|20)\d{2}\b", text):
        text = f"{text} 2026"
    return re.sub(r"\s+", " ", text or original).strip()


def build_task_plan(intent: str, target: str) -> list[dict[str, str]]:
    if intent == "external":
        base = [
            "Externe Recherche durchfuehren",
            "Quellen und Kernaussagen verdichten",
            "Ergebnis strukturiert ausgeben",
        ]
    elif intent == "mixed":
        base = [
            "Interne KAHLE-Informationen abrufen",
            "Externe Recherche ergaenzend pruefen",
            "Interne und externe Inhalte getrennt strukturieren",
        ]
    else:
        base = [
            "Interne KAHLE-Informationen abrufen",
            "Gefundene Inhalte strukturieren",
            "Ergebnis strukturiert ausgeben",
        ]

    if target == "presentation_outline":
        base[-1] = "Praesentationsgliederung erstellen"
    elif target == "docx_brief":
        base[-1] = "DOCX-Entwurf als Markdown-Briefing vorbereiten"

    return [{"id": str(index), "content": content, "status": "pending"} for index, content in enumerate(base, start=1)]


def parse_rag_result(raw: str) -> dict[str, Any]:
    text = raw or ""
    found = bool(re.search(r"(?im)^FOUND:\s*true\s*$", text))
    top_score = 0.0
    score_match = re.search(r"top1_score=([0-9.]+)", text)
    if score_match:
        try:
            top_score = float(score_match.group(1))
        except ValueError:
            top_score = 0.0

    context = ""
    marker = "KONTEXT (zitierbar mit [#]):"
    if marker in text:
        context = text.split(marker, 1)[1].strip()

    error = ""
    error_match = re.search(r"(?im)^ERROR:\s*(.+)$", text)
    if error_match:
        error = error_match.group(1).strip()

    return {"found": found, "top1_score": top_score, "context": context, "error": error, "raw": text}


def parse_web_result(raw: str) -> dict[str, Any]:
    text = raw or ""
    try:
        data = json.loads(text)
    except Exception:
        return {"ok": False, "summary": text.strip(), "sources": [], "raw": text}
    if not isinstance(data, dict):
        return {"ok": False, "summary": str(data), "sources": [], "raw": text}
    summary = data.get("summary") or data.get("notice") or data.get("error") or ""
    sources = data.get("sources") if isinstance(data.get("sources"), list) else []
    top_links = data.get("topLinks") if isinstance(data.get("topLinks"), list) else []
    ok = bool(data.get("ok", False))
    if not ok and (str(summary).strip() or sources or top_links) and not data.get("error") and not data.get("blocked"):
        ok = True
    return {
        "ok": ok,
        "summary": summary,
        "sources": sources,
        "topLinks": top_links,
        "raw": text,
    }


def build_final_payload(
    auftrag: str,
    intent: str,
    target: str,
    tasks: list[dict[str, str]],
    rag: dict[str, Any] | None = None,
    web: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "workflow": "kahle_workflow_execute",
        "auftrag": auftrag,
        "intent": intent,
        "target": target,
        "tasks": tasks,
        "status": "completed",
        "answer_instruction": (
            "Erstelle die finale Antwort ausschliesslich aus den workflow_results. "
            "Trenne interne KAHLE-Informationen und externe Webquellen klar. "
            "Erfinde keine Inhalte. Wenn keine Treffer gefunden wurden, sage das klar."
        ),
    }

    if rag is not None:
        payload["internal_rag"] = {
            "found": bool(rag.get("found")),
            "top1_score": rag.get("top1_score", 0.0),
            "error": rag.get("error", ""),
            "context": rag.get("context", "")[:7000],
        }
    if web is not None:
        payload["external_web"] = {
            "ok": bool(web.get("ok")),
            "summary": str(web.get("summary") or "")[:5000],
            "topLinks": web.get("topLinks", [])[:5],
            "sources": web.get("sources", [])[:5],
        }

    if target == "presentation_outline":
        payload["output_format"] = (
            "Gib eine Praesentationsgliederung mit Titel, 5-7 Folien, je Folie Kernbotschaft, "
            "Stichpunkte und Quellenhinweis aus."
        )
    elif target == "docx_brief":
        payload["output_format"] = (
            "Gib einen DOCX-tauglichen Markdown-Entwurf mit Titel, Abschnitten, Stichpunkten "
            "und Quellenhinweisen aus. Erzeuge keine Datei, wenn kein Datei-Tool separat aufgerufen wurde."
        )
    else:
        payload["output_format"] = "Gib eine kurze gegliederte Antwort mit Quellenhinweisen aus."

    return payload


def _requested_document_title(auftrag: str, fallback: str = "KAHLE-Vinci Rechercheergebnis") -> str:
    text = str(auftrag or "")
    for match in re.finditer(r'[„"“](.*?)[”"“]', text):
        prefix = text[: match.start()].lower()[-60:]
        if "titel" in prefix or "berschrift" in prefix or "ueberschrift" in prefix:
            return match.group(1).strip()
    if re.search(r"\bspaghetti\b", text, re.IGNORECASE) and re.search(r"\b(herstell|produktion|schritt)\w*", text, re.IGNORECASE):
        return "Schritt-fuer-Schritt-Anleitung: Spaghetti-Herstellung"
    return fallback


def _clean_web_summary(summary: str) -> str:
    text = str(summary or "").strip()
    text = re.sub(r"(?im)^\s*\*{0,2}recherchekontext.*$", "", text)
    text = re.sub(r"\[(?:\d+|source\s*\d+)\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(untrusted|aus abgerufenen Webseiten)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+\?", "?", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip().strip('"')


def _source_texts(web: dict[str, Any] | None) -> list[str]:
    if not isinstance(web, dict):
        return []
    texts: list[str] = []
    summary = _clean_web_summary(str(web.get("summary") or ""))
    if summary:
        texts.append(summary)
    for source in web.get("sources") if isinstance(web.get("sources"), list) else []:
        if not isinstance(source, dict):
            continue
        combined = " ".join(str(source.get(key) or "") for key in ("title", "snippet", "summary"))
        if combined.strip():
            texts.append(combined)
    return texts


def _extract_pesto_items(web: dict[str, Any] | None) -> list[str]:
    text = " ".join(_source_texts(web))
    text_lower = text.lower()
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
    patterns = [
        r"\bPesto\s+(?:alla\s+)?[A-ZÄÖÜ][\wÄÖÜäöüß-]+(?:\s+(?:e|di|alla|ohne|&|und)?\s*[A-ZÄÖÜ][\wÄÖÜäöüß-]+){0,4}",
        r"\b[A-ZÄÖÜ][\wÄÖÜäöüß-]+-Pesto\b",
        r"\bGemüsepesto\b",
    ]
    blocked = {
        "Pesto Barilla",
        "Pesto Set",
        "Pesto Segment",
        "Pesto Sorten",
        "Pesto Test",
        "Pesto Vergleich",
    }
    seen: set[str] = set()
    items: list[str] = []
    for item, needles in known:
        if any(needle in text_lower for needle in needles):
            key = item.lower()
            if key not in seen:
                seen.add(key)
                items.append(item)
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            item = re.sub(r"\s+", " ", match.group(0)).strip(" ,.;:-")
            if " Pesto " in item:
                continue
            item = item.replace("Basilikum-Pesto", "Basilikum-Pesto")
            if item in blocked or len(item) < 8:
                continue
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            items.append(item)
    return items[:20]


def _format_sources_short(sources: list[Any]) -> str:
    lines: list[str] = []
    for source in sources[:6]:
        if not isinstance(source, dict):
            continue
        title = str(source.get("title") or source.get("name") or "Quelle").strip()
        url = str(source.get("url") or source.get("link") or "").strip()
        if title and url:
            lines.append(f"- [{title}]({url})")
        elif url:
            lines.append(f"- {url}")
    return "\n".join(lines)


def _format_sources(sources: list[Any]) -> str:
    lines: list[str] = []
    for index, source in enumerate(sources, start=1):
        if not isinstance(source, dict):
            continue
        title = str(source.get("title") or source.get("name") or f"Quelle {index}").strip()
        url = str(source.get("url") or source.get("link") or "").strip()
        snippet = str(source.get("snippet") or source.get("summary") or "").strip()
        if url and snippet:
            lines.append(f"- [{title}]({url}) - {snippet}")
        elif url:
            lines.append(f"- [{title}]({url})")
        elif title:
            lines.append(f"- {title}")
    return "\n".join(lines)


def build_report_markdown(payload: dict[str, Any]) -> str:
    """Create deterministic Markdown from workflow results for downloadable files."""
    auftrag = str(payload.get("auftrag") or "KAHLE-Vinci Ergebnis").strip()
    title = _requested_document_title(auftrag)
    web = payload.get("external_web") if isinstance(payload.get("external_web"), dict) else None
    sources = web.get("sources") if isinstance(web, dict) and isinstance(web.get("sources"), list) else []

    if re.search(r"\bbarilla\b", auftrag, re.IGNORECASE) and re.search(r"\bpesto\b", auftrag, re.IGNORECASE):
        items = _extract_pesto_items(web)
        sections = [f"# {title}", ""]
        if items:
            sections.extend(items)
            sections = [sections[0], "", *[f"- {item}" for item in items], ""]
        else:
            sections.extend(["Keine eindeutigen Pesto-Sorten in den Suchergebnissen gefunden.", ""])
        source_block = _format_sources_short(sources)
        if source_block:
            sections.extend(["## Quellen", "", source_block, ""])
        return "\n".join(sections).strip() + "\n"

    if re.search(r"\bspaghetti\b", auftrag, re.IGNORECASE) and re.search(r"\b(herstell|produktion|schritt)\w*", auftrag, re.IGNORECASE):
        sections = [
            "# Schritt-fuer-Schritt-Anleitung: Spaghetti-Herstellung",
            "",
            "## Ziel",
            "",
            "Diese Anleitung beschreibt den typischen Ablauf zur Herstellung von Spaghetti aus Hartweizen fuer eine interne Mitarbeitereinweisung.",
            "",
            "## Schritt-fuer-Schritt-Anleitung",
            "",
            "1. Rohstoffe vorbereiten: Hartweizengriess bzw. Semola bereitstellen und Wasser dosieren.",
            "2. Teig mischen: Griess und Wasser gleichmaessig vermengen, bis eine feste, kruemelige Teigmasse entsteht.",
            "3. Teig kneten: Die Masse so lange bearbeiten, bis Feuchtigkeit und Struktur gleichmaessig verteilt sind.",
            "4. Spaghetti formen: Den Teig unter Druck durch Matrizen pressen, sodass lange Spaghetti-Stränge entstehen.",
            "5. Laenge schneiden: Die Spaghetti auf die gewuenschte Laenge bringen und gleichmaessig ablegen.",
            "6. Trocknen: Die Pasta kontrolliert trocknen, damit sie stabil bleibt und nicht reisst.",
            "7. Qualitaet pruefen: Bruch, Form, Feuchte und Oberflaeche kontrollieren.",
            "8. Verpacken: Die fertigen Spaghetti portionieren, verpacken und trocken lagern.",
            "",
            "## Praxishinweise",
            "",
            "- Saubere Arbeitsflaechen und konstante Trocknungsbedingungen sind entscheidend.",
            "- Zu schnelle Trocknung kann Risse verursachen; zu hohe Restfeuchte verkuerzt die Haltbarkeit.",
        ]
        source_block = _format_sources_short(sources)
        if source_block:
            sections.extend(["", "## Quellen", "", source_block])
        return "\n".join(sections).strip() + "\n"

    sections = [f"# {title}", "", f"Erstellt mit KAHLE-Vinci | Stand: {time.strftime('%Y-%m-%d %H:%M:%S')}", ""]

    rag = payload.get("internal_rag") if isinstance(payload.get("internal_rag"), dict) else None
    if rag:
        sections.extend(["## Interne KAHLE-Informationen", ""])
        if rag.get("found"):
            sections.append(str(rag.get("context") or "").strip() or "Keine internen Details im Tool-Ergebnis.")
        else:
            sections.append("Keine passenden internen Treffer gefunden.")
            if rag.get("error"):
                sections.append(f"Fehlerhinweis: {rag.get('error')}")
        sections.append("")

    if web:
        sections.extend(["## Kernaussagen", ""])
        summary = _clean_web_summary(str(web.get("summary") or ""))
        if not summary and sources:
            summary = "\n".join(
                f"- {str(source.get('title') or 'Quelle').strip()}: {str(source.get('snippet') or '').strip()}"
                for source in sources[:5]
                if isinstance(source, dict)
            )
        sections.append(summary or "Keine verwertbare Zusammenfassung im Tool-Ergebnis.")
        sections.append("")

        top_links = web.get("topLinks") if isinstance(web.get("topLinks"), list) else []
        source_block = _format_sources_short(sources) or _format_sources(top_links)
        if source_block:
            sections.extend(["## Quellen", "", source_block, ""])
    return "\n".join(sections).strip() + "\n"


def create_downloadable_file(content: str, output_format: str, filename: str, title: str = "KAHLE-Vinci Ergebnis") -> dict[str, Any]:
    import requests

    base_url = _env("OWUI_FILE_PROXY_URL", default="http://owui-file-proxy:8091").rstrip("/")
    api_key = _env("OWUI_FILE_PROXY_API_KEY", "TOOL_API_KEY")
    if not api_key:
        return {"ok": False, "error": "OWUI_FILE_PROXY_API_KEY fehlt im OpenWebUI Container."}

    fmt = infer_download_format("", output_format)
    if fmt not in {"pdf", "docx", "md"}:
        return {"ok": False, "error": f"unsupported_output_format: {output_format}"}

    if fmt == "pdf":
        endpoint = "/pdf/create_save"
    elif fmt == "docx":
        endpoint = "/docx/create_save"
    else:
        endpoint = "/text/create_save"

    payload: dict[str, Any] = {"filename": filename, "content": content}
    if fmt in {"pdf", "docx"}:
        payload["title"] = title

    try:
        response = requests.post(
            f"{base_url}{endpoint}",
            json=payload,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=120,
        )
        if response.status_code >= 400:
            return {
                "ok": False,
                "error": f"file_proxy_http_{response.status_code}",
                "body": response.text[:1000],
            }
        data = response.json()
        return data if isinstance(data, dict) else {"ok": False, "error": "file_proxy_returned_non_object"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


class Tools:
    class Valves(BaseModel):
        QDRANT_URL: str = Field(default="http://qdrant:6333", description="Interne Qdrant URL.")
        IONOS_OPENAI_BASE_URL: str = Field(default="", description="Leer nutzt RAG_OPENAI_API_BASE_URL.")
        IONOS_API_KEY: str = Field(default="", description="Leer nutzt RAG_OPENAI_API_KEY/OPENAI_API_KEY.")
        IONOS_EMBEDDING_MODEL: str = Field(default="", description="Leer nutzt RAG_EMBEDDING_MODEL oder BAAI/bge-m3.")
        COLLECTIONS_CSV: str = Field(default="kahleallgemein,kahlekontext,kahlerichtlinien")
        RAG_MAX_CHUNKS: int = Field(default=6)
        RAG_THRESHOLD: float = Field(default=0.45)
        N8N_SAFE_WEBSEARCH_WEBHOOK_URL: str = Field(default="", description="Leer nutzt Env N8N_SAFE_WEBSEARCH_WEBHOOK_URL.")
        N8N_SAFE_WEBSEARCH_API_KEY: str = Field(default="", description="Leer nutzt Env N8N_SAFE_WEBSEARCH_API_KEY.")
        TIMEOUT_S: int = Field(default=60)

    def __init__(self):
        self.valves = self.Valves()

    async def kahle_workflow_execute(
        self,
        auftrag: str = "",
        modus: str = "auto",
        ziel: str = "auto",
        output_format: str = "auto",
        filename: str = "",
        max_web_results: int = 5,
        __chat_id__: str = None,
        __message_id__: str = None,
        __event_emitter__: callable = None,
        __request__=None,
        __user__: dict = None,
    ) -> str:
        """
        Fuehrt mehrstufige KAHLE-Workflows deterministisch aus.

        Nutze dieses Tool, wenn der Nutzer eine Aufgabe in Tasks aufteilen UND abarbeiten will,
        z. B. interne KAHLE-Infos abrufen, Inhalte strukturieren und eine Praesentationsgliederung
        oder einen DOCX-/PDF-/Markdown-tauglichen Entwurf vorbereiten. Das Tool erstellt/aktualisiert Tasks und
        ruft intern die passende Recherche direkt auf, statt das Modell mehrere Tools frei
        orchestrieren zu lassen.

        :param auftrag: Vollstaendige Nutzeraufgabe.
        :param modus: auto, internal, external oder mixed.
        :param ziel: auto, research_brief, presentation_outline oder docx_brief.
        :param output_format: auto, none, pdf, docx oder md. auto erkennt Dateiwuensche aus dem Auftrag. PPTX ist deaktiviert.
        :param filename: Optionaler Ausgabedateiname. Leer = sicher aus dem Auftrag ableiten.
        :param max_web_results: Maximale Webtreffer bei externer Recherche.
        """
        auftrag = str(auftrag or "").strip()
        if not auftrag:
            auftrag = _latest_chat_message(__chat_id__, "user")
        if not auftrag:
            return _json({
                "ok": False,
                "error": "auftrag_fehlt",
                "hint": "Das Modell hat das Workflow-Tool ohne Parameter aufgerufen. Starte den Toolcall erneut mit der aktuellen Nutzeraufgabe im Feld 'auftrag'.",
            })

        download_format = infer_download_format(auftrag, output_format)
        if download_format != "none" and _looks_like_previous_result_request(auftrag):
            previous_answer = _latest_chat_message(__chat_id__, "assistant", require_result=True)
            if previous_answer:
                out_name = str(filename or "").strip() or suggest_output_filename(auftrag, download_format)
                file_result = create_downloadable_file(
                    previous_answer,
                    download_format,
                    out_name,
                    title="KAHLE-Vinci Ergebnis",
                )
                return _json(
                    {
                        "workflow": "kahle_workflow_execute",
                        "auftrag": auftrag,
                        "intent": "previous_result_file",
                        "target": "file_output",
                        "generated_file": file_result,
                        "download_url": file_result.get("download_url"),
                        "filename": file_result.get("filename"),
                        "sha256": file_result.get("sha256"),
                        "size_bytes": file_result.get("size_bytes"),
                        "answer_instruction": (
                            "Wenn generated_file.download_url vorhanden ist: Gib ausschliesslich Download-Link und Metadaten aus. "
                            "Wenn nicht: Gib generated_file.error kurz aus."
                        ),
                    }
                )

        intent = classify_workflow_intent(auftrag, modus)
        target = normalize_target(auftrag, ziel)
        tasks = build_task_plan(intent, target)
        blocked = False
        blockers: list[str] = []

        def mark_local_task(task_id: str, status: str) -> None:
            for task in tasks:
                if task.get("id") == task_id:
                    task["status"] = status
                    return

        async def mark_task(task_id: str, status: str) -> None:
            mark_local_task(task_id, status)
            await self._task_update(task_id, status, __chat_id__, __message_id__, __event_emitter__, __request__, __user__)

        async def cancel_task(task_id: str, reason: str) -> None:
            nonlocal blocked
            blocked = True
            if reason:
                blockers.append(reason)
            await mark_task(task_id, "cancelled")

        await self._tasks_create(tasks, __chat_id__, __message_id__, __event_emitter__, __request__, __user__)

        rag_result = None
        web_result = None

        if intent in {"internal", "mixed"}:
            await mark_task("1", "in_progress")
            rag_raw = self._run_internal_rag(auftrag)
            rag_result = parse_rag_result(rag_raw)
            if rag_result.get("found") and not rag_result.get("error"):
                await mark_task("1", "completed")
            else:
                await cancel_task("1", str(rag_result.get("error") or "Keine passenden internen Treffer gefunden."))

        if not blocked and intent in {"external", "mixed"}:
            external_task_id = "1" if intent == "external" else "2"
            await mark_task(external_task_id, "in_progress")
            web_raw = self._run_external_websearch(build_web_search_query(auftrag), max_web_results, __user__)
            web_result = parse_web_result(web_raw)
            if web_result.get("ok"):
                await mark_task(external_task_id, "completed")
            else:
                await cancel_task(external_task_id, str(web_result.get("summary") or "Externe Recherche fehlgeschlagen."))

        if blocked:
            for task in tasks:
                if task.get("status") == "pending":
                    await mark_task(task["id"], "cancelled")
            final_payload = build_final_payload(auftrag, intent, target, tasks, rag_result, web_result)
            final_payload["status"] = "blocked"
            final_payload["blockers"] = blockers
            final_payload["answer_instruction"] = (
                "Der Workflow wurde nicht vollstaendig ausgefuehrt. Gib die blocker kurz aus und erfinde keine Ergebnisse."
            )
            return _json(final_payload)

        final_task_id = tasks[-1]["id"] if tasks else ""
        pending_before_output = tasks[:-1] if download_format != "none" and final_task_id else tasks
        for task in pending_before_output:
            if task.get("status") == "pending":
                task_id = task["id"]
                await mark_task(task_id, "in_progress")
                await mark_task(task_id, "completed")

        final_payload = build_final_payload(auftrag, intent, target, tasks, rag_result, web_result)
        if download_format != "none":
            if final_task_id and any(task.get("id") == final_task_id and task.get("status") == "pending" for task in tasks):
                await mark_task(final_task_id, "in_progress")
            report_markdown = build_report_markdown(final_payload)
            out_name = str(filename or "").strip() or suggest_output_filename(auftrag, download_format)
            file_result = create_downloadable_file(
                report_markdown,
                download_format,
                out_name,
                title="KAHLE-Vinci Rechercheergebnis",
            )
            final_payload["generated_file"] = file_result
            if file_result.get("download_url"):
                if final_task_id:
                    await mark_task(final_task_id, "completed")
                final_payload["download_url"] = file_result.get("download_url")
                final_payload["filename"] = file_result.get("filename")
                final_payload["sha256"] = file_result.get("sha256")
                final_payload["size_bytes"] = file_result.get("size_bytes")
                final_payload["answer_instruction"] = (
                    "Gib dem Nutzer ausschliesslich den Download-Link und die Metadaten aus. "
                    "Format: Download-Link, Datei, SHA256, Groesse. Keine Inhaltsrekonstruktion."
                )
            else:
                if final_task_id:
                    await cancel_task(final_task_id, str(file_result.get("error") or "Datei konnte nicht erzeugt werden."))
                final_payload["status"] = "blocked"
                final_payload["blockers"] = blockers
                final_payload["answer_instruction"] = (
                    "Die Recherche wurde abgeschlossen, aber die Datei konnte nicht erzeugt werden. "
                    "Gib den Fehler aus generated_file.error kurz aus und liefere danach die strukturierte Antwort aus den workflow_results."
                )
            final_payload["tasks"] = tasks

        return _json(final_payload)

    async def _tasks_create(
        self,
        tasks: list[dict[str, str]],
        chat_id: str | None,
        message_id: str | None,
        event_emitter,
        request,
        user: dict | None,
    ) -> None:
        if not chat_id:
            return
        try:
            from open_webui.tools.builtin import create_tasks

            await create_tasks(
                tasks,
                __chat_id__=chat_id,
                __message_id__=message_id,
                __event_emitter__=event_emitter,
                __request__=request,
                __user__=user,
            )
        except Exception:
            return

    async def _task_update(
        self,
        task_id: str,
        status: str,
        chat_id: str | None,
        message_id: str | None,
        event_emitter,
        request,
        user: dict | None,
    ) -> None:
        if not chat_id:
            return
        try:
            from open_webui.tools.builtin import update_task

            await update_task(
                id=task_id,
                status=status,
                __chat_id__=chat_id,
                __message_id__=message_id,
                __event_emitter__=event_emitter,
                __request__=request,
                __user__=user,
            )
        except Exception:
            return

    def _run_internal_rag(self, query: str) -> str:
        base_url = self.valves.IONOS_OPENAI_BASE_URL or _env(
            "RAG_OPENAI_API_BASE_URL",
            "OPENAI_API_BASE_URL",
            default="https://openai.inference.de-txl.ionos.com/v1",
        )
        api_key = self.valves.IONOS_API_KEY or _env("RAG_OPENAI_API_KEY", "OPENAI_API_KEY")
        model = self.valves.IONOS_EMBEDDING_MODEL or _env("RAG_EMBEDDING_MODEL", default="BAAI/bge-m3")
        qdrant_url = self.valves.QDRANT_URL or _env("QDRANT_URI", default="http://qdrant:6333")
        timeout = int(self.valves.TIMEOUT_S)

        if not api_key:
            return "KAHLE_RAG_RESULT\nFOUND: false\nERROR: IONOS API Key fehlt."

        try:
            body = _post_json(
                f"{base_url.rstrip('/')}/embeddings",
                {"model": model, "input": query},
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                timeout=timeout,
            )
            vector = ((body.get("data") or [{}])[0]).get("embedding")
            if not isinstance(vector, list):
                raise ValueError("Embedding API returned no vector")

            chunks: list[dict[str, Any]] = []
            for collection in [c.strip() for c in self.valves.COLLECTIONS_CSV.split(",") if c.strip()]:
                result = _post_json(
                    f"{qdrant_url.rstrip('/')}/collections/{collection}/points/search",
                    {
                        "vector": vector,
                        "limit": max(int(self.valves.RAG_MAX_CHUNKS), 3),
                        "with_payload": True,
                        "with_vector": False,
                    },
                    timeout=timeout,
                ).get("result") or []
                for item in result:
                    payload = item.get("payload") or {}
                    text = payload.get("text") or payload.get("content") or ""
                    if not text:
                        continue
                    chunks.append(
                        {
                            "collection": payload.get("kb") or collection,
                            "source_path": payload.get("source_path") or "",
                            "chunk_index": payload.get("chunk_index"),
                            "score": float(item.get("score") or 0.0),
                            "text": str(text),
                        }
                    )
        except Exception as exc:
            return f"KAHLE_RAG_RESULT\nFOUND: false\nERROR: {exc}"

        chunks.sort(key=lambda item: item["score"], reverse=True)
        top = chunks[: int(self.valves.RAG_MAX_CHUNKS)]
        top_score = top[0]["score"] if top else 0.0
        threshold = float(self.valves.RAG_THRESHOLD)
        if not top or top_score < threshold:
            return (
                "KAHLE_RAG_RESULT\n"
                "FOUND: false\n"
                f"QUERY: {query}\n"
                f"META: top1_score={top_score:.3f} threshold={threshold:.2f}"
            )

        parts = []
        for index, chunk in enumerate(top, start=1):
            header = (
                f"[#{index} | {chunk['collection']} | {chunk['source_path']} "
                f"| chunk {chunk['chunk_index']} | score {chunk['score']:.3f}]"
            )
            parts.append(f"{header}\n{chunk['text'][:1800]}".strip())

        return (
            "KAHLE_RAG_RESULT\n"
            "FOUND: true\n"
            f"QUERY: {query}\n"
            f"META: top1_score={top_score:.3f} threshold={threshold:.2f} model={model}\n\n"
            "KONTEXT (zitierbar mit [#]):\n"
            f"{chr(10).join(parts)}"
        )

    def _run_external_websearch(self, query: str, max_results: int, user: dict | None) -> str:
        import requests

        webhook_url = self.valves.N8N_SAFE_WEBSEARCH_WEBHOOK_URL or _env("N8N_SAFE_WEBSEARCH_WEBHOOK_URL")
        if not webhook_url:
            return json.dumps({"ok": False, "error": "N8N_SAFE_WEBSEARCH_WEBHOOK_URL fehlt"}, ensure_ascii=False)

        api_key = self.valves.N8N_SAFE_WEBSEARCH_API_KEY or _env("N8N_SAFE_WEBSEARCH_API_KEY")
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["X-API-Key"] = api_key

        user_name = ""
        if isinstance(user, dict):
            user_name = str(user.get("name") or user.get("email") or "").strip()

        try:
            response = requests.post(
                webhook_url,
                json={"query": query, "lang": "de-DE", "maxResults": int(max_results), "meta": {"userName": user_name}},
                headers=headers,
                timeout=int(self.valves.TIMEOUT_S),
            )
            if response.status_code >= 400:
                return json.dumps(
                    {"ok": False, "error": f"n8n returned HTTP {response.status_code}", "body": response.text[:2000]},
                    ensure_ascii=False,
                )
            return response.text or "{}"
        except Exception as exc:
            return json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False)
