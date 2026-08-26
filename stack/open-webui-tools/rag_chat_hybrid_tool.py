"""title: RAG Chat KAHLE Hybrid
version: 1.0.0
description: Berechtigungsgefilterte Dense+BM25-Suche mit RRF, Reranking und Quellen.
"""
# ACHTUNG: Diese Datei ist NICHT in OpenWebUI installierbar.
# Sie verweist auf Klassen aus hybrid_retrieval.py und laeuft allein mit
# NameError. Installiere die gebaute Fassung aus dist/ desselben Namens:
#     python stack/open-webui-tools/build_tools.py
#     -> stack/open-webui-tools/dist/<diese Datei>

import hashlib
import json
import os
import re
import time
import requests
from pydantic import BaseModel, Field


def _feedback_link(chat_id, message_id):
    """Bewusst einfache, von OpenWebUI stabil verarbeitete Portaladresse."""
    return (
        "[Wissensfehler melden]"
        f"(/wissen/?feedback=1&chat_id={chat_id}&message_id={message_id})"
    )


def _missing_rag_result(query, chat_id, message_id):
    evidence = _evidence_bundle(
        query,
        missing_information=[
            "Für die konkrete Anfrage liegt keine ausreichende freigegebene Evidenz vor."
        ],
    )
    return (
        "KAHLE_RAG_RESULT\nFOUND: false\n"
        f"{_evidence_bundle_line(evidence)}\n"
        "ANSWER: Dazu habe ich keine verlässliche freigegebene Information.\n"
        f"FEEDBACK_LINK: {_feedback_link(chat_id, message_id)}"
    )


def _hybrid_setting(primary, fallback=""):
    return os.environ.get(primary) or fallback


def _hybrid_embed(base_url, api_key, model, query, timeout):
    response = requests.post(
        f"{base_url.rstrip('/')}/embeddings",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": model, "input": query}, timeout=timeout,
    )
    response.raise_for_status()
    vector = response.json()["data"][0]["embedding"]
    if not vector:
        raise RetrievalError("dense_embedding_unavailable")
    return vector


def _hybrid_user_id(user):
    if not isinstance(user, dict):
        return ""
    return str(user.get("id") or (user.get("user") or {}).get("id") or "").strip()


def _sanitize_rag_query(query):
    """Remove an OpenWebUI answer prompt accidentally forwarded as query.

    Some native tool-capable models may repeat the complete synthesis prompt,
    including a previous ``<context>`` block, when they invoke rag_chat again.
    Retrieval must only see the user's actual question at the end. Normal
    queries are returned unchanged.
    """
    value = str(query or "").strip()
    if "KAHLE_RAG_RESULT" not in value or "</context>" not in value.lower():
        return value
    value = re.split(r"</context>", value, flags=re.IGNORECASE)[-1].strip()
    return re.sub(r"^query\s*[:=-]?\s*", "", value, flags=re.IGNORECASE).strip()


def _expand_kahle_query_aliases(query):
    """Expand unambiguous internal shorthand before every retrieval stage.

    Location codes intentionally remain case-sensitive: lowercase ``nie`` and
    ``neu`` are normal German words. This keeps natural questions unchanged
    while supporting the uppercase codes employees use in daily work.
    """
    value = str(query or "").strip()
    aliases = (
        ("TD", "Teiledienst"),
        ("VK", "Verkauf"),
        ("HAN", "Hannover"),
        ("WUN", "Wunstorf"),
        ("WED", "Wedemark"),
        ("WAL", "Walsrode"),
        ("NEU", "Neustadt am Rübenberge"),
        ("NIE", "Nienburg"),
        ("STA", "Stadthagen"),
        ("SHG", "Stadthagen"),
    )
    for alias, canonical in aliases:
        value = re.sub(
            rf"(?<![A-Za-z0-9])(?:LOC-)?{re.escape(alias)}(?![A-Za-z0-9])",
            canonical,
            value,
        )
    return value


def _clarification_for_query(query):
    """Ask for the required scope instead of returning an arbitrary long list."""
    value = str(query or "").strip().casefold()
    if (
        re.search(r"\b(?:erfind|fingier|dicht)\w*", value)
        and re.search(r"\b(?:richtlinie|policy|arbeitsanweisung|vorgabe|regelung)\w*", value)
    ):
        return (
            "Ich kann keine bestehende interne Richtlinie erfinden. "
            "Ich kann nur einen ausdrücklich als Entwurf gekennzeichneten Vorschlag erstellen."
        )
    customer_lock = (
        re.search(r"\b(?:kunde|kunden)(?:\b|(?=sperr|entsperr))", value)
        and re.search(r"(?:\b(?:sperr|entsperr)\w*|\bkunden(?:sperr|entsperr)\w*)", value)
    )
    marketing_scope = re.search(
        r"\b(?:werbung|werbewiderspruch|befragung(?:en)?|kontaktfreigabe(?:n)?|dse[- ]einstellung(?:en)?)\b",
        value,
    )
    general_scope = re.search(
        r"\b(?:allgemein(?:e|en|er)?|vollstaendig(?:e|en|er)?|vollständig(?:e|en|er)?|"
        r"verkaufssperre|auftragssperre|finanzsperre)\b",
        value,
    )
    if customer_lock and not marketing_scope and not general_scope:
        return (
            "Geht es darum, Werbung und Befragungen für den Kunden in Hannover, "
            "Wunstorf oder Wedemark zu sperren, oder um eine allgemeine "
            "Kundensperre in Vaudis für einen anderen Standort?"
        )
    if not re.search(r"\b(?:öffnungszeiten|oeffnungszeiten|öffnungszeit|oeffnungszeit)\b", value):
        return ""
    complete_scope = (
        re.search(r"\b(?:alle|allen|sämtliche|saemtliche)\s+(?:kahle[- ]?)?standort\w*\b", value)
        and all(department in value for department in ("verkauf", "service", "teiledienst"))
    )
    if complete_scope:
        return ""
    locations = (
        "hannover", "wunstorf", "neustadt", "rübenberge", "ruebenberge",
        "wedemark", "walsrode", "nienburg", "stadthagen",
    )
    if any(location in value for location in locations):
        return ""
    return (
        "Für welchen Standort und welchen Bereich (Verkauf, Service oder "
        "Teiledienst) brauchst du die Öffnungszeiten?"
    )


def _guided_response_for_query(query):
    """Keep operational next steps source-driven through RAG."""
    return ""


def _filter_evidence_chunks(query, chunks):
    """Reject passages that cannot carry the relationship asked for."""
    folded_query = _fold_evidence_text(query)

    def passage(chunk):
        return _fold_evidence_text("\n".join((
            str(getattr(chunk, "title", "") or ""),
            " > ".join(str(item) for item in (getattr(chunk, "heading_path", ()) or ())),
            str(getattr(chunk, "parent_content", "") or ""),
        )))

    selected = list(chunks or [])
    if (
        re.search(r"\barbeitsanweisung\w*\b", folded_query)
        and re.search(r"\b(?:pruf|freigab|veroffentlich|ablauf|prozess)\w*\b", folded_query)
    ):
        release = (
            "release-paket", "releasepaket", "kryptografische signatur",
            "prufsumme", "client akzeptiert", "software-update", "updates",
        )
        workflow = (
            "arbeitsanweisung", "wissensportal", "dokument", "upload",
            "fachlich", "veroffentlich",
        )
        selected = [
            chunk for chunk in selected
            if not (
                any(marker in passage(chunk) for marker in release)
                and not any(marker in passage(chunk) for marker in workflow)
            )
        ]

    relationship = re.search(
        r"\b(?:support|ansprechpartner|zustandig|zustandigkeit|betreut|verantwortlich)\w*\b",
        folded_query,
    )
    system_match = re.search(
        r"\b(?:support\w*\s+(?:fur|von)|fur\s+den\s+technischen\s+support\s+von)\s+"
        r"([a-z0-9][a-z0-9_-]*)",
        folded_query,
    )
    if relationship and system_match:
        system = system_match.group(1)
        relation = re.compile(
            r"\b(?:support|ansprechpartner|zustandig|zustandigkeit|betreut|verantwortlich)\w*\b"
        )
        selected = [
            chunk for chunk in selected
            if system in passage(chunk) and relation.search(passage(chunk))
        ]

    if (
        "kundensperre" in folded_query
        and re.search(r"\b(?:allgemein|vollstandig|verkaufssperre|auftragssperre|finanzsperre)\w*\b", folded_query)
    ):
        marketing = (
            "werbung", "werbewiderspruch", "befragung", "kontaktfreigabe",
            "hersteller-zufriedenheitsbefragung", "hersteller zufriedenheitsbefragung",
        )
        general = (
            "allgemeine kundensperre", "vollstandige kundensperre",
            "verkaufssperre", "auftragssperre", "finanzsperre",
        )
        selected = [
            chunk for chunk in selected
            if any(marker in passage(chunk) for marker in general)
            or (
                "datenschutz" in passage(chunk)
                and any(marker in passage(chunk) for marker in (
                    "sperranfrage", "sperrenanfrage",
                ))
            )
        ]
    return selected


def _rag_answer_instruction(query):
    """Return query-specific grounding rules without replacing retrieval."""
    value = str(query or "").strip().casefold()
    marketing_scope = re.search(
        r"\b(?:werbung|werbesperre|werbewiderspruch|befragung(?:en)?|"
        r"kontaktfreigabe(?:n)?|dse[- ]einstellung(?:en)?)\b",
        value,
    )
    instruction = (
        "Antworte nur aus CONTEXT. Belege jede konkrete interne Aussage mit [Quelle N]. "
        "Bei Konflikt nicht stillschweigend entscheiden. "
    )
    if marketing_scope:
        instruction += (
            "Nutze ausschließlich einschlägige Textstellen zu Werbewiderspruch, Werbung, "
            "automatisierten Befragungen, DSE-Kontaktfreigaben und Sperrliste. "
            "Leite keine allgemeine Kundensperre und keine Felder, Register oder Datenkategorien "
            "aus anderen Vaudis-Handbuchtreffern ab. Nenne insbesondere besondere Merkmale oder "
            "Finanzdaten nur, wenn die einschlägige Quelle zum Werbewiderspruch dies ausdrücklich verlangt. "
        )
    folded = (
        str(query or "").casefold()
        .replace("ä", "ae").replace("ö", "oe")
        .replace("ü", "ue").replace("ß", "ss")
    )
    if (
        "standort" in folded
        and all(department in folded for department in ("verkauf", "service", "teiledienst"))
    ):
        instruction += (
            "Beschränke die Übersicht auf die ausdrücklich angefragten Standorte und Bereiche. "
            "Nenne keine Personen, Ansprechpartner, Unternehmenshistorie oder sonstigen Zusatzdaten, "
            "wenn danach nicht gefragt wurde. Verallgemeinere Angaben eines einzelnen Standorts nicht "
            "auf andere Standorte. "
        )
    return instruction


def _fold_evidence_text(value):
    return (
        str(value or "").casefold()
        .replace("ä", "ae").replace("ö", "oe")
        .replace("ü", "ue").replace("ß", "ss")
    )


def _procedural_evidence_intent(query):
    value = _fold_evidence_text(query)
    value = re.sub(
        r"\b(?:kein(?:e|en|er|es)?|ohne)\s+"
        r"(?:\w+\s+){0,2}"
        r"(?:anleitung|schritte?|ablaufschritte?|vorgehen|ablauf)\w*",
        "",
        value,
    )
    if any(marker in value for marker in ("anleitung", "schritt", "vorgehen", "ablauf")):
        return True
    return bool(
        re.search(
            r"\bwie\s+(?:"
            r"kann|muss|soll|darf|gehe|verfahre|funktioniert|laeuft|"
            r"bedien|nutz|verwend|richt|beantrag|aender|pfleg|meld|"
            r"fuehr|oeffn|waehl|trag|gib|erfass|speicher|bestaetig|"
            r"erstell|plan|buch|sperr"
            r")\w*\b",
            value,
        )
    )


def _context_has_procedure(context):
    value = _fold_evidence_text(context)
    patterns = (
        r"\bo?ffn\w*", r"\bnavigier\w*", r"\bklick\w*",
        r"\bwaehl\w*", r"\b(?:eingeb\w*|gib)\b", r"\berfass\w*",
        r"\bspeicher\w*", r"\bbestaetig\w*", r"\berstell\w*",
    )
    return sum(bool(re.search(pattern, value)) for pattern in patterns) >= 3


def _detected_conflict_source_ids(source_items):
    """Detect explicit mutually exclusive procedure instructions."""
    folded = [
        (source.get("number"), _fold_evidence_text(source.get("evidence_text")))
        for source in source_items
        if source.get("number") and source.get("evidence_text")
    ]
    opposites = (
        (r"\bunten\s+rechts\b", r"\bunten\s+links\b"),
        (r"\boben\s+rechts\b", r"\boben\s+links\b"),
        (r"\bals\s+vorgang\b", r"\bals\s+aktion\b"),
        (r"\bvorgang\s+anleg\w*", r"\baktion\s+anleg\w*"),
    )
    conflicts = set()
    for index, (left_number, left_text) in enumerate(folded):
        for right_number, right_text in folded[index + 1:]:
            if any(
                (re.search(left, left_text) and re.search(right, right_text))
                or (re.search(right, left_text) and re.search(left, right_text))
                for left, right in opposites
            ):
                conflicts.update((f"#{left_number}", f"#{right_number}"))
    return sorted(conflicts, key=lambda value: int(value.lstrip("#")))


def _claim_evidence_spans(query, passage):
    """Select exact relevant sentences; never synthesize a claim across passages."""
    sentences = [
        sentence.strip()
        for sentence in re.findall(r"[^.!?\n]+[.!?]?", str(passage or ""))
        if sentence.strip()
    ]
    if not sentences:
        return []
    stopwords = {
        "aber", "dass", "eine", "einen", "einer", "fuer", "kahle", "oder",
        "sind", "ueber", "unter", "unser", "unsere", "unseren", "unserer",
        "vollstaendig", "welche", "wer", "wie", "wird", "zustandig",
    }
    query_terms = {
        term for term in re.findall(r"[a-z0-9]{3,}", _fold_evidence_text(query))
        if term not in stopwords
    }
    scored = []
    for position, sentence in enumerate(sentences):
        terms = set(re.findall(r"[a-z0-9]{3,}", _fold_evidence_text(sentence)))
        scored.append((len(query_terms.intersection(terms)), position, sentence))
    best = max(score for score, _position, _sentence in scored)
    if best <= 0:
        return sentences[:1]
    return [
        sentence for score, _position, sentence in scored
        if score == best
    ][:3]


def _evidence_bundle(query, context="", sources=None, missing_information=None):
    source_items = list(sources or [])
    missing = list(missing_information or [])
    claims = []
    for source in source_items:
        number = source.get("number")
        passage = str(source.get("evidence_text") or "").strip()
        if number and passage:
            for claim_index, claim in enumerate(_claim_evidence_spans(query, passage), 1):
                claims.append({
                    "claim_id": f"R{number}C{claim_index}",
                    "source_id": f"#{number}",
                    "text": claim[:1000],
                    "evidence_span": claim[:1000],
                    "document_id": source.get("document_id"),
                    "version_id": source.get("version_id"),
                    "claim_type": (
                        (source.get("evidence_capabilities") or ["factual_support"])[0]
                    ),
                })
    clean_sources = [
        {key: value for key, value in source.items() if key != "evidence_text"}
        for source in source_items
    ]
    conflicts = [
        f"#{source['number']}"
        for source in source_items
        if source.get("number") and source.get("conflict")
    ]
    detected_conflicts = _detected_conflict_source_ids(source_items)
    conflicts = sorted(
        set(conflicts) | set(detected_conflicts),
        key=lambda value: int(value.lstrip("#")),
    )
    if not source_items:
        status = "unsupported"
    else:
        status = "supported"
        if conflicts:
            status = "partially_supported"
            missing.append(
                "Die Quellen widersprechen sich in einem angefragten Ablauf."
                if detected_conflicts
                else "Die Quellen enthalten einen gekennzeichneten inhaltlichen Konflikt."
            )
        if _procedural_evidence_intent(query) and not _context_has_procedure(context):
            status = "partially_supported"
            missing.append(
                "Die Quellen bestätigen das Thema, enthalten aber keine ausreichende Anleitung."
            )
        folded_query = _fold_evidence_text(query)
        folded_context = _fold_evidence_text(context)
        if re.search(r"\b(?:machbar|umsetzbar|realisierbar|technisch moglich)\b", folded_query) and not re.search(
            r"\b(?:machbar|umsetzbar|realisierbar|technisch moglich|technisch freigegeben)\b",
            folded_context,
        ):
            status = "partially_supported"
            missing.append("Die technische Machbarkeit ist in den Quellen nicht bestätigt.")
        if "datenschutz" in folded_query and re.search(r"\b(?:ohne|keine|nicht)\b", folded_query) and not (
            "datenschutz" in folded_context
            and re.search(r"\b(?:freigabe|prufung|bedenken|zulassig)\w*", folded_context)
        ):
            status = "partially_supported"
            missing.append("Eine Datenschutzfreigabe ist in den Quellen nicht bestätigt.")
    return {
        "schema_version": "kahle.evidence-bundle.v1",
        "status": status,
        "supported_claims": claims,
        "missing_information": missing,
        "conflicts": conflicts,
        "sources": clean_sources,
    }


def _evidence_bundle_line(bundle):
    return "EVIDENCE_BUNDLE_JSON: " + json.dumps(bundle, ensure_ascii=False, separators=(",", ":"))


def _hybrid_record_event(portal_url, internal_key, user_id, query, found,
                         source_count, started_at, error_code=None):
    """Best-effort Betriebsmetrik ohne Fragetext oder Dokumentinhalt."""
    try:
        requests.post(
            f"{portal_url.rstrip('/')}/portal/internal/retrieval-events",
            headers={"X-API-Key": internal_key, "Content-Type": "application/json"},
            json={
                "user_id": user_id,
                "query_hash": hashlib.sha256(query.encode("utf-8")).hexdigest(),
                "found": bool(found),
                "source_count": int(source_count),
                "latency_ms": max(0, round((time.monotonic() - started_at) * 1000)),
                "error_code": error_code,
            },
            timeout=1,
        )
    except requests.RequestException:
        pass


class Tools:
    class Valves(BaseModel):
        PORTAL_API_URL: str = Field(default="http://kb-admin-api:8092")
        INTERNAL_API_KEY: str = Field(default="")
        KB_SYNC_URL: str = Field(default="http://kb-sync:8093")
        QDRANT_URL: str = Field(default="http://qdrant:6333")
        COLLECTION_ALIAS: str = Field(default="vinci_knowledge")
        IONOS_OPENAI_BASE_URL: str = Field(default="")
        IONOS_API_KEY: str = Field(default="")
        IONOS_EMBEDDING_MODEL: str = Field(default="")
        RERANKER_MODEL: str = Field(default="Qwen/Qwen3-VL-Reranker-8B")
        MINIMUM_RERANK_SCORE: float = Field(default=0.25, ge=0, le=1)
        TIMEOUT_S: int = Field(default=60)

    def __init__(self):
        self.valves = self.Valves()

    async def rag_chat(self, query: str = "", __user__: dict | None = None, __chat_id__: str = "", __message_id__: str = "", __metadata__: dict | None = None) -> str:
        """Durchsucht ausschließlich freigegebenes Wissen, das der angemeldete Nutzer lesen darf."""
        query = _expand_kahle_query_aliases(_sanitize_rag_query(query))
        started_at = time.monotonic()
        user_id = _hybrid_user_id(__user__)
        internal_key = self.valves.INTERNAL_API_KEY or _hybrid_setting("KB_ADMIN_MAINTENANCE_API_KEY")
        api_key = self.valves.IONOS_API_KEY or _hybrid_setting("RAG_OPENAI_API_KEY", _hybrid_setting("OPENAI_API_KEY"))
        base_url = self.valves.IONOS_OPENAI_BASE_URL or _hybrid_setting(
            "RAG_OPENAI_API_BASE_URL", _hybrid_setting("OPENAI_API_BASE_URL", "https://openai.inference.de-txl.ionos.com/v1")
        )
        model = self.valves.IONOS_EMBEDDING_MODEL or _hybrid_setting("RAG_EMBEDDING_MODEL", "BAAI/bge-m3")
        clarification = _clarification_for_query(query)
        if clarification:
            evidence = _evidence_bundle(query, missing_information=[clarification])
            return (
                "KAHLE_RAG_RESULT\nFOUND: false\n"
                "CLARIFICATION_REQUIRED: true\n"
                f"{_evidence_bundle_line(evidence)}\n"
                f"ANSWER: {clarification}\n"
                f"FEEDBACK_LINK: {_feedback_link(__chat_id__, __message_id__)}"
            )
        guided_response = _guided_response_for_query(query)
        if guided_response:
            evidence = _evidence_bundle(
                query,
                missing_information=[
                    "Für eine operative Anleitung liegt keine freigegebene Evidenz vor."
                ],
            )
            return (
                "KAHLE_RAG_RESULT\nFOUND: true\n"
                "GUIDED_RESPONSE: true\n"
                f"{_evidence_bundle_line(evidence)}\n"
                f"ANSWER: {guided_response}\n"
                f"FEEDBACK_LINK: {_feedback_link(__chat_id__, __message_id__)}"
            )
        if not query or not user_id or not internal_key or not api_key:
            return _missing_rag_result(query, __chat_id__, __message_id__)
        try:
            scope = PortalScopeClient(self.valves.PORTAL_API_URL, internal_key).resolve(user_id)
            dense = _hybrid_embed(base_url, api_key, model, query, int(self.valves.TIMEOUT_S))
            retriever = QdrantHybridRetriever(
                self.valves.QDRANT_URL, self.valves.COLLECTION_ALIAS,
                RemoteSparseQueryEncoder(self.valves.KB_SYNC_URL, internal_key),
                IonosReranker(base_url, api_key, self.valves.RERANKER_MODEL),
                timeout=int(self.valves.TIMEOUT_S), minimum_rerank_score=self.valves.MINIMUM_RERANK_SCORE,
            )
            information_needs = (
                (__metadata__ or {}).get("_kahle_information_needs")
                if isinstance(__metadata__, dict) else None
            )
            chunks = retriever.retrieve(
                query, dense, scope,
                information_needs=(information_needs if isinstance(information_needs, list) else None),
            )
            chunks = _filter_evidence_chunks(query, chunks)
        except Exception as exc:
            error_code = (
                str(exc).strip()
                if isinstance(exc, RetrievalError) and str(exc).strip()
                else type(exc).__name__
            )
            _hybrid_record_event(self.valves.PORTAL_API_URL, internal_key, user_id, query,
                                 False, 0, started_at, error_code)
            return (
                "KAHLE_RAG_RESULT\nFOUND: false\n"
                f"{_evidence_bundle_line(_evidence_bundle(query, missing_information=[error_code]))}\n"
                "ANSWER: Dazu habe ich keine verlässliche freigegebene Information.\n"
                f"ERROR_CODE: {error_code}\n"
                f"FEEDBACK_LINK: {_feedback_link(__chat_id__, __message_id__)}"
            )
        if not chunks:
            _hybrid_record_event(self.valves.PORTAL_API_URL, internal_key, user_id, query,
                                 False, 0, started_at)
            return _missing_rag_result(query, __chat_id__, __message_id__)
        context, sources = [], []
        for index, chunk in enumerate(chunks, 1):
            heading = " > ".join(chunk.heading_path)
            context.append(f"[Quelle {index}] {chunk.title} | {heading}\n{chunk.parent_content}")
            sources.append({
                "number": index, "title": chunk.title, "document_id": chunk.document_id,
                "version_id": chunk.version_id, "valid_until": chunk.valid_until,
                "source_url": chunk.source_url, "conflict": chunk.conflict,
                "knowledgebase_ids": list(chunk.knowledgebase_ids),
                "domain": getattr(chunk, "domain", "internal_general"),
                "document_type": getattr(chunk, "document_type", "knowledge_document"),
                "topics": list(getattr(chunk, "topics", ()) or ()),
                "evidence_capabilities": list(
                    getattr(chunk, "evidence_capabilities", ()) or ()
                ),
                "source_provider": getattr(chunk, "source_provider", "knowledge_portal"),
                "classification_status": getattr(chunk, "classification_status", "review_required"),
                "classification_version": getattr(chunk, "classification_version", ""),
                "classification_confidence": float(
                    getattr(chunk, "classification_confidence", 0) or 0
                ),
                "evidence_text": chunk.parent_content,
            })
        joined_context = "\n\n".join(context)
        evidence = _evidence_bundle(query, joined_context, sources)
        _hybrid_record_event(self.valves.PORTAL_API_URL, internal_key, user_id, query,
                             True, len(sources), started_at)
        return (
            "KAHLE_RAG_RESULT\nFOUND: true\n"
            f"{_evidence_bundle_line(evidence)}\n"
            f"INSTRUCTION: {_rag_answer_instruction(query)}\n"
            f"CONTEXT:\n{joined_context}\n"
            f"SOURCES_JSON: {json.dumps(sources, ensure_ascii=False)}\n"
            f"FEEDBACK_LINK: {_feedback_link(__chat_id__, __message_id__)}"
        )
