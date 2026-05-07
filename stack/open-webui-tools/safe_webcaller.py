import hashlib
import json
import os
import re

try:
    import requests
except Exception:  # pragma: no cover - local helper tests do not call HTTP
    requests = None


FINAL_PREFIX = "<<<FINAL_NOTICE>>>\n"
FINAL_SUFFIX = "\n<<<END_FINAL_NOTICE>>>"


STOP_PHRASES_RE = re.compile(
    r"\b("
    r"bitte|mal|einmal|kurz|kannst du|koenntest du|könntest du|"
    r"recherchiere|recherche|suche|such|google|finde|pruefe|prüfe|"
    r"gib mir|erstelle|ausgeben|ausgabe|als pdf|als docx|als markdown|als datei|download"
    r")\b",
    re.IGNORECASE,
)

CURRENT_INTENT_RE = re.compile(
    r"\b(aktuell\w*|heute|stand heute|neueste\w*|neusten\w*|latest|current|news|nachrichten)\b",
    re.IGNORECASE,
)


def _collapse_ws(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _clean_user_query(query: str) -> str:
    q = str(query or "").strip()
    q = re.sub(r"Attached files in this message.*", " ", q, flags=re.IGNORECASE | re.DOTALL)
    q = re.sub(r"https?://\S+", " ", q)
    q = STOP_PHRASES_RE.sub(" ", q)
    q = re.sub(r"\b(zu|zum|zur|ueber|über|ueber den|ueber die|ueber das|über den|über die|über das)\b", " ", q, flags=re.IGNORECASE)
    q = re.sub(r"[?!.:,;]+", " ", q)
    return _collapse_ws(q)


def build_search_query(query: str) -> str:
    """Create a search-engine query from a conversational user request."""
    original = str(query or "").strip()
    cleaned = _clean_user_query(original)
    lower = cleaned.lower()
    original_lower = original.lower()
    has_current_intent = bool(CURRENT_INTENT_RE.search(original))

    # Common KAHLE-Vinci research cases. Keep these deterministic and transparent.
    if re.search(r"\bclaude\b", lower) and re.search(r"\b(ai|anthropic)\b", lower):
        cleaned = "Claude AI Anthropic Modelle Funktionen Preise Enterprise Vergleich"
    elif re.search(r"\bcupra\b", lower) and re.search(r"\btindaya\b", lower):
        cleaned = "CUPRA Tindaya Konzeptfahrzeug offizielle Informationen technische Daten Design Marktstart"
    elif re.search(r"\bki\b", lower) and re.search(r"\b(news|nachrichten)\b", original_lower):
        cleaned = "aktuelle KI News OpenAI Anthropic Google Meta Microsoft EU AI Act"
    elif re.search(r"\bki\b", lower) and re.search(r"\brichtlin", lower):
        cleaned = "KI Richtlinie Unternehmen Inhalte Vorlage EU AI Act Datenschutz Compliance"

    # Generic enrichment for short entity-only searches.
    tokens = re.findall(r"[\wÄÖÜäöüß-]+", cleaned, flags=re.UNICODE)
    content_tokens = [t for t in tokens if len(t) >= 3]
    if cleaned and len(content_tokens) <= 2:
        cleaned = f"{cleaned} Überblick aktuelle Informationen Funktionen Einsatzbereiche Vergleich"

    if has_current_intent and not re.search(r"\b(19|20)\d{2}\b", cleaned):
        cleaned = f"{cleaned} 2026"

    return _collapse_ws(cleaned or original)


class Tools:
    def __init__(self):
        self.webhook_url = (os.getenv("N8N_SAFE_WEBSEARCH_WEBHOOK_URL") or "").strip()
        self.api_key = (os.getenv("N8N_SAFE_WEBSEARCH_API_KEY") or "").strip()
        self.timeout = float(os.getenv("N8N_SAFE_WEBSEARCH_TIMEOUT") or "50")

        self.strict_notice_only = os.getenv("KV_STRICT_NOTICE_ONLY", "1").strip().lower() in ("1", "true", "yes", "on")
        self.notice_on_blocked = os.getenv("KV_NOTICE_ON_BLOCKED", "1").strip().lower() in ("1", "true", "yes", "on")
        self.strip_bracket_citations_in_summary = os.getenv("KV_STRIP_BRACKET_CITATIONS_IN_SUMMARY", "1").strip().lower() in ("1", "true", "yes", "on")
        self.top_links_max = int(os.getenv("KV_TOP_LINKS_MAX") or "4")
        self.hide_raw_sources = os.getenv("KV_HIDE_RAW_SOURCES", "0").strip().lower() in ("1", "true", "yes", "on")
        self.sources_text_snippet_prefix = os.getenv("KV_SOURCES_TEXT_SNIPPET_PREFIX", "1").strip().lower() in ("1", "true", "yes", "on")
        self.snippet_max_len = int(os.getenv("KV_SNIPPET_MAX_LEN") or "280")
        self.user_mode = (os.getenv("KV_USER_MODE") or "plain").strip().lower()
        self.user_hash_salt = (os.getenv("KV_USER_HASH_SALT") or "").strip()

    def _safe_json_loads(self, text: str):
        try:
            return json.loads(text)
        except Exception:
            return None

    def _unquote_json_string(self, value):
        if not isinstance(value, str):
            return value
        text = value.strip()
        if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
            try:
                return json.loads(text)
            except Exception:
                return value
        return value

    def _clean_summary(self, summary: str) -> str:
        text = self._unquote_json_string(summary or "").strip()
        text = re.sub(r"(?im)^\s*(\*?quellen\*?\s*:).*$", "", text).strip()
        if self.strip_bracket_citations_in_summary:
            text = re.sub(r"\[\s*\d+\s*\]", "", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _pick_best_item(self, items: list) -> dict:
        dicts = [item for item in items if isinstance(item, dict)]
        if not dicts:
            return {}

        def score(item: dict) -> int:
            decision = (item.get("decision") or (item.get("policy") or {}).get("decision") or "").strip()
            notice = item.get("notice") or (item.get("policy") or {}).get("notice") or ""
            value = 0
            if item.get("blocked"):
                value += 100
            if decision in {"block_high_risk", "needs_clarification"}:
                value += 80
            if decision == "proceed":
                value += 20
            if notice:
                value += 10
            return value

        return sorted(dicts, key=score, reverse=True)[0]

    def _coerce_data_to_dict(self, data):
        if isinstance(data, dict):
            return data
        if isinstance(data, list):
            return self._pick_best_item(data)
        return {}

    def _build_top_links(self, sources):
        links = []
        if not isinstance(sources, list):
            return links
        for source in sources:
            if not isinstance(source, dict):
                continue
            url = (source.get("url") or "").strip()
            if not url:
                continue
            normalized = url[:-1] if url.endswith("/") else url
            if normalized not in links:
                links.append(normalized)
            if len(links) >= self.top_links_max:
                break
        return links

    def _clean_snippet(self, snippet: str) -> str:
        text = re.sub(r"\s{2,}", " ", snippet or "").strip()
        if len(text) > self.snippet_max_len:
            return text[: self.snippet_max_len].rstrip() + "..."
        return text

    def _build_sources_by_id(self, sources):
        result = {}
        if not isinstance(sources, list):
            return result
        for source in sources:
            if not isinstance(source, dict):
                continue
            source_id = source.get("id")
            url = (source.get("url") or "").strip()
            if source_id is not None and url:
                result[str(source_id)] = url
        return result

    def _build_sources_text(self, sources, limit: int = 4):
        lines = []
        if not isinstance(sources, list):
            return ""
        count = 0
        for source in sources:
            if not isinstance(source, dict):
                continue
            source_id = source.get("id")
            title = (source.get("title") or source.get("name") or "").replace('"', "'").strip()
            url = (source.get("url") or "").strip()
            snippet = self._clean_snippet(source.get("snippet") or "")
            if source_id is None or not url:
                continue
            lines.append(f'<source id="{source_id}" name="{title}">{url}</source>')
            if self.sources_text_snippet_prefix and snippet:
                lines.append(f"Snippet: {snippet}")
            lines.append("")
            count += 1
            if count >= limit:
                break
        return "\n".join(lines).strip()

    def _encode_user(self, name: str) -> str:
        user = (name or "").strip()
        if not user:
            return ""
        if self.user_mode == "hash":
            return hashlib.sha256((self.user_hash_salt + user).encode("utf-8")).hexdigest()
        return user

    def _extract_username_from_userobj(self, user_obj) -> str:
        if not isinstance(user_obj, dict):
            return ""
        for key in ("name", "username", "email", "id"):
            value = user_obj.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _extract_payload(self, data: dict) -> dict:
        if not isinstance(data, dict):
            return {}
        policy = data.get("policy") if isinstance(data.get("policy"), dict) else {}
        decision = (data.get("decision") or policy.get("decision") or "").strip()
        notice = self._unquote_json_string(data.get("notice") or policy.get("notice") or "")
        redacted = data.get("redacted", policy.get("redacted", False))
        blocked = data.get("blocked", policy.get("blocked", False))
        triggered = data.get("triggered")
        if not isinstance(triggered, dict):
            triggered = policy.get("triggered", {"checks": [], "patterns": [], "entityTypes": []})
        sources = data.get("sources") if isinstance(data.get("sources"), list) else []
        return {
            "decision": decision,
            "notice": notice,
            "redacted": bool(redacted),
            "blocked": bool(blocked),
            "triggered": triggered if isinstance(triggered, dict) else {"checks": [], "patterns": [], "entityTypes": []},
            "searchQuery": data.get("searchQuery") or data.get("search_query") or data.get("query") or "",
            "summary": self._clean_summary(data.get("summary") or ""),
            "sources": sources,
        }

    def safe_websearch(
        self,
        query: str = "",
        lang: str = "de-DE",
        maxResults: int = 5,
        userName: str = "",
        __user__: dict = None,
        **kwargs,
    ) -> str:
        """
        Sichere Websuche ueber n8n/SearXNG.

        query darf eine natuerliche Nutzerfrage sein. Das Tool erzeugt daraus vor dem
        n8n-Aufruf eine suchmaschinengeeignete Query.
        """
        if not self.webhook_url:
            return f"{FINAL_PREFIX}Missing env var N8N_SAFE_WEBSEARCH_WEBHOOK_URL{FINAL_SUFFIX}"
        if requests is None:
            return f"{FINAL_PREFIX}Python package requests is not available{FINAL_SUFFIX}"

        if not str(query or "").strip():
            return "Bitte nenne ein konkretes Suchthema."

        optimized_query = build_search_query(query)
        user_from_context = self._extract_username_from_userobj(__user__)
        chosen_user = (user_from_context or userName or "").strip()
        user_value = self._encode_user(chosen_user)

        payload = {
            "query": optimized_query,
            "lang": lang,
            "maxResults": int(maxResults),
            "meta": {"userName": user_value, "userMode": self.user_mode},
        }

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        if user_value:
            headers["X-OWUI-User"] = user_value

        try:
            response = requests.post(self.webhook_url, json=payload, headers=headers, timeout=self.timeout)
            if response.status_code >= 400:
                return json.dumps(
                    {
                        "ok": False,
                        "error": f"n8n returned HTTP {response.status_code}",
                        "body": (response.text or "")[:2000],
                        "requestedQuery": query,
                        "optimizedQuery": optimized_query,
                    },
                    ensure_ascii=False,
                )

            content_type = (response.headers.get("content-type") or "").lower()
            if "application/json" in content_type:
                data = response.json()
            else:
                parsed = self._safe_json_loads(response.text or "")
                data = parsed if parsed is not None else {"raw": response.text or ""}

            data = self._coerce_data_to_dict(data)
            normalized = self._extract_payload(data)
            decision = (normalized.get("decision") or "").strip()
            blocked = bool(normalized.get("blocked", False))
            notice = self._unquote_json_string(normalized.get("notice") or "").strip()

            if self.strict_notice_only and decision in {"block_high_risk", "needs_clarification"}:
                return notice or "Bitte praezisiere deine Anfrage."

            if self.notice_on_blocked and blocked:
                return notice or "Ausgabe wurde aus Sicherheitsgruenden blockiert."

            output = {"ok": True, **normalized}
            output["requestedQuery"] = query
            output["optimizedQuery"] = optimized_query
            output["notice"] = notice
            output["topLinks"] = self._build_top_links(output.get("sources", []))
            output["linksText"] = "Links (URLs):\n" + "\n".join(output["topLinks"][: self.top_links_max])
            output["sourcesById"] = self._build_sources_by_id(output.get("sources", []))
            output["sourcesText"] = self._build_sources_text(output.get("sources", []), limit=self.top_links_max)
            if self.hide_raw_sources:
                output.pop("sources", None)
            return json.dumps(output, ensure_ascii=False)

        except requests.Timeout:
            return f"{FINAL_PREFIX}Timeout calling n8n{FINAL_SUFFIX}"
        except Exception as exc:
            return f"{FINAL_PREFIX}Request failed: {type(exc).__name__}: {exc}{FINAL_SUFFIX}"
