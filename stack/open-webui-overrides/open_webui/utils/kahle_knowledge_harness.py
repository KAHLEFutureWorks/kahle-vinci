"""Shared, side-effect-free knowledge harness contracts for shadow evaluation.

This first migration step observes the existing OpenWebUI path.  It does not
rewrite prompts, execute tools, emit UI events or modify an assistant answer.
"""

from dataclasses import asdict, dataclass, field
import json
import re
import unicodedata
from typing import Any


SCHEMA_VERSION = "kahle.knowledge-harness.v1"

KNOWN_ALIASES = {
    "TD": "Teiledienst",
    "VK": "Verkauf",
    "NIE": "Nienburg",
    "HAN": "Hannover",
    "SHG": "Stadthagen",
}


@dataclass(frozen=True)
class UserIntent:
    kind: str
    procedural: bool
    clarification_required: bool = False
    clarification_question: str = ""


@dataclass(frozen=True)
class ResolvedContext:
    original_query: str
    retrieval_query: str
    aliases: dict[str, str] = field(default_factory=dict)
    conversation_reference: bool = False


@dataclass(frozen=True)
class RetrievalPlan:
    required_tool: str
    queries: tuple[str, ...]
    permission_scope: dict[str, Any]
    mode: str = "shadow"


@dataclass(frozen=True)
class EvidenceBundle:
    status: str
    supported_claims: tuple[Any, ...] = ()
    missing_information: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    sources: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class AnswerContract:
    evidence_only: bool = True
    citations_required: bool = True
    incomplete_evidence: str = "partial_answer"
    allow_unsubstantiated_examples: bool = False
    allow_unsubstantiated_referrals: bool = False
    preserve_native_tool_status: bool = True
    preserve_document_sources: bool = True
    preserve_feedback_link: bool = True


@dataclass(frozen=True)
class AnswerValidation:
    schema_version: str
    status: str
    violations: tuple[dict[str, Any], ...] = ()

    @property
    def retry_required(self) -> bool:
        return self.status == "retry_required"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def retry_prompt(self) -> str:
        """Return a structured retry order without rewriting the answer."""
        payload = {
            "schema_version": "kahle.answer-retry.v1",
            "violations": list(self.violations),
            "instructions": (
                "Erzeuge die Antwort erneut aus demselben EvidenceBundle. "
                "Behebe alle genannten Verstöße. Ergänze keine neuen Informationen."
            ),
        }
        return (
            "KAHLE_KNOWLEDGE_ANSWER_RETRY\n"
            + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        )


@dataclass(frozen=True)
class HarnessDecision:
    schema_version: str
    model_profile: dict[str, str]
    user_intent: UserIntent
    resolved_context: ResolvedContext
    retrieval_plan: RetrievalPlan
    evidence_bundle: EvidenceBundle
    answer_contract: AnswerContract
    events: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def answer_prompt(self) -> str:
        """Return the model-independent contract consumed before answering."""
        payload = {
            "schema_version": "kahle.answer-contract.v1",
            "user_intent": asdict(self.user_intent),
            "resolved_context": asdict(self.resolved_context),
            "evidence_bundle": asdict(self.evidence_bundle),
            "answer_contract": asdict(self.answer_contract),
        }
        contract = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return (
            "KAHLE_KNOWLEDGE_ANSWER_CONTRACT\n"
            f"{contract}\n"
            "Antworte nur aus der bereitgestellten Evidenz. "
            "Bei partially_supported beantworte ausschließlich die belegten Teile und "
            "benenne die fehlenden Informationen. Bei unsupported nutze kein allgemeines "
            "Modellwissen. Jede konkrete interne Aussage benötigt eine vorhandene Quellen-ID. "
            "Ergänze keine Beispiele, möglichen Eingabefelder, Alternativen, Ansprechpartner, "
            "Support-Verweise oder Handlungsempfehlungen, sofern diese nicht ausdrücklich in "
            "der Evidenz stehen. Wenn eine Anleitung fehlt, sage nur, welcher belegte Teil "
            "vorliegt und welche Information fehlt. "
            "Erzeuge genau eine endgültige Antwort."
        )

    def direct_answer(self) -> str:
        """Return a stable pre-answer result only when no synthesis is required."""
        if self.user_intent.clarification_required:
            return self.user_intent.clarification_question
        if self.evidence_bundle.status == "unsupported":
            return "Dazu habe ich keine verlässliche freigegebene Information."
        return ""

    def validation_fallback(self) -> str:
        """Return a stable answer-component fallback after a failed retry."""
        missing = next(
            (
                item.strip().rstrip(".")
                for item in self.evidence_bundle.missing_information
                if str(item).strip()
            ),
            "Für die vollständige Antwort fehlen ausreichende freigegebene Informationen",
        )
        return f"Die vorhandenen Quellen beantworten nur einen Teil der Anfrage. {missing}."


def _fold(value: str) -> str:
    return (
        unicodedata.normalize("NFKD", str(value or ""))
        .encode("ascii", "ignore")
        .decode()
        .casefold()
    )


def _decision_value(decision: HarnessDecision | dict[str, Any], name: str) -> Any:
    if isinstance(decision, HarnessDecision):
        return getattr(decision, name)
    return decision.get(name) if isinstance(decision, dict) else None


def _mapping(value: Any) -> dict[str, Any]:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    return value if isinstance(value, dict) else {}


def validate_answer(
    answer: str,
    decision: HarnessDecision | dict[str, Any],
) -> AnswerValidation:
    """Validate a completed answer without changing its content.

    The checks intentionally use only deterministic structure and explicit
    language patterns. Semantic repair belongs to the answer model, which
    receives ``retry_prompt`` when this result requires another attempt.
    """
    text = str(answer or "").strip()
    evidence = _mapping(_decision_value(decision, "evidence_bundle"))
    contract = _mapping(_decision_value(decision, "answer_contract"))
    retrieval_plan = _mapping(_decision_value(decision, "retrieval_plan"))
    violations: list[dict[str, Any]] = []

    def add(code: str, message: str, **details: Any) -> None:
        violation = {"code": code, "message": message}
        violation.update(details)
        if violation not in violations:
            violations.append(violation)

    if not text:
        add("answer_missing", "Die Antwort ist leer.")

    permission_scope = _mapping(retrieval_plan.get("permission_scope"))
    if not str(permission_scope.get("user_id") or "").strip():
        add(
            "permission_scope_missing",
            "Der Retrieval-Plan enthält keinen gebundenen Benutzerkontext.",
        )

    sources = [item for item in evidence.get("sources") or [] if isinstance(item, dict)]
    source_ids = {
        str(item.get("number") or item.get("source_id") or "").lstrip("#")
        for item in sources
        if str(item.get("number") or item.get("source_id") or "").strip()
    }
    cited_ids = set(
        re.findall(r"\[(?:#\s*|Quelle\s*)?(\d+)\]", text, re.IGNORECASE)
    )
    unknown_ids = sorted(cited_ids - source_ids)
    if unknown_ids:
        add(
            "unknown_source_id",
            "Die Antwort verwendet Quellen-IDs, die nicht im EvidenceBundle existieren.",
            source_ids=unknown_ids,
        )
    if (
        text
        and contract.get("citations_required", True)
        and evidence.get("status") in {"supported", "partially_supported"}
        and source_ids
        and not cited_ids
    ):
        add("citation_missing", "Die Antwort enthält keine vorhandene Quellen-ID.")

    resolved_context = _mapping(_decision_value(decision, "resolved_context"))
    retrieval_query = _fold(resolved_context.get("retrieval_query") or "")
    requested_departments = {
        department
        for department, markers in {
            "verkauf": ("verkauf",),
            "service": ("service",),
            "teiledienst": ("teiledienst", "teile/zubehor", "teile und zubehor"),
        }.items()
        if any(marker in retrieval_query for marker in markers)
    }
    if evidence.get("status") == "supported" and len(requested_departments) == 1:
        labels = {
            "teiledienst" if label.startswith("teile") else label
            for label in re.findall(
                r"(?im)^\s*[-*]?\s*(?:\*\*)?\s*"
                r"(verkauf|service|teiledienst|teile\s*/\s*zubehor)"
                r"(?:\*\*)?\s*:",
                _fold(text),
            )
        }
        unrequested = sorted(labels - requested_departments)
        if unrequested:
            add(
                "unrequested_scope_expansion",
                "Die Antwort enthält eigene Abschnitte für nicht angefragte Bereiche.",
                departments=unrequested,
            )

    if evidence.get("status") == "partially_supported":
        folded = _fold(text)
        if not any(
            marker in folded
            for marker in (
                "nicht enthalten", "keine anleitung", "anleitung fehlt",
                "informationen fehlen", "nicht ausreichend", "nicht vor",
            )
        ):
            add(
                "missing_information_not_disclosed",
                "Die Antwort benennt die fehlenden Informationen nicht.",
            )
        if not contract.get("allow_unsubstantiated_examples", False) and re.search(
            r"(?i)\b(?:zum beispiel|z\.\s*b\.|beispielsweise)\b", text
        ):
            add(
                "unsubstantiated_example",
                "Die Teilantwort ergänzt ein nicht belegtes Beispiel.",
            )
        if not contract.get("allow_unsubstantiated_referrals", False) and re.search(
            r"(?i)\b(?:wende\s+dich|kontakt(?:iere|aufnahme)|support|konsultiere|"
            r"handbuch\s+(?:zu\s+)?(?:suchen|konsultieren)|"
            r"kann\s+ich\s+(?:eine\s+)?suche\s+durchfuehren|"
            r"kann\s+ich\s+(?:eine\s+)?suche\s+durchführen)\b",
            text,
        ):
            add(
                "unsubstantiated_referral",
                "Die Teilantwort ergänzt einen nicht belegten Verweis oder ein Hilfsangebot.",
            )

    return AnswerValidation(
        schema_version="kahle.answer-validation.v1",
        status="retry_required" if violations else "accepted",
        violations=tuple(violations),
    )


def summarize_harness_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate privacy-safe runtime records for the reference dashboard."""
    rows = [record for record in records if isinstance(record, dict)]

    def rate(predicate: Any) -> float:
        return round(sum(1 for row in rows if predicate(row)) / len(rows), 4) if rows else 0.0

    latencies = sorted(
        int(row["latency_ms"])
        for row in rows
        if isinstance(row.get("latency_ms"), (int, float)) and row["latency_ms"] >= 0
    )

    def percentile(percent: int) -> int | None:
        if not latencies:
            return None
        index = max(0, ((len(latencies) * percent + 99) // 100) - 1)
        return latencies[min(index, len(latencies) - 1)]

    return {
        "schema_version": "kahle.harness-metrics-summary.v1",
        "sample_size": len(rows),
        "correct_tool_path_rate": rate(
            lambda row: bool(row.get("required_tool"))
            and row.get("tool_called") == row.get("required_tool")
        ),
        "accepted_rate": rate(
            lambda row: row.get("final_validation_status") == "accepted"
        ),
        "retry_rate": rate(lambda row: int(row.get("retry_count") or 0) > 0),
        "fallback_rate": rate(lambda row: bool(row.get("fallback_used"))),
        "source_presence_rate": rate(
            lambda row: not int(row.get("source_count") or 0)
            or bool(row.get("document_sources_present"))
        ),
        "feedback_link_rate": rate(lambda row: bool(row.get("feedback_link_present"))),
        "latency_p50_ms": percentile(50),
        "latency_p95_ms": percentile(95),
    }


def _is_procedural(query: str) -> bool:
    folded = _fold(query)
    intent_text = re.sub(
        r"\b(?:kein(?:e|en|er|es)?|ohne)\s+"
        r"(?:\w+\s+){0,2}"
        r"(?:anleitung|schritte?|ablaufschritte?|vorgehen|ablauf)\w*",
        "",
        folded,
    )
    if any(
        marker in intent_text
        for marker in ("anleitung", "schritt", "vorgehen", "ablauf")
    ):
        return True
    return bool(
        re.search(
            r"\bwie\s+(?:"
            r"kann|muss|soll|darf|gehe|verfahre|funktioniert|laeuft|"
            r"bedien|nutz|verwend|richt|beantrag|aender|pfleg|meld|"
            r"fuehr|oeffn|waehl|trag|gib|erfass|speicher|bestaetig|"
            r"erstell|plan|buch|sperr"
            r")\w*\b",
            intent_text,
        )
    )


def _intent_kind(query: str) -> str:
    folded = _fold(query)
    named_person = bool(
        re.fullmatch(
            r"wer\s+ist\s+(?:(?:unser|unsere|der|die)\s+)?"
            r"[a-z][a-z.-]+(?:\s+[a-z][a-z.-]+){1,2}\s*[?!.]*",
            folded,
        )
    )
    directory_terms = (
        "ansprechpartner", "mitarbeiter", "mitarbeiterin", "kollege", "kollegin",
        "durchwahl", "telefonnummer", "geschaftliche email", "geschaftliche e-mail",
        "dienstliche email", "dienstliche e-mail",
    )
    return (
        "employee_directory"
        if named_person or any(term in folded for term in directory_terms)
        else "internal_knowledge"
    )


def _aliases_in_query(query: str) -> dict[str, str]:
    return {
        alias: expansion
        for alias, expansion in KNOWN_ALIASES.items()
        if re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", query, re.IGNORECASE)
    }


def resolve_query_aliases(query: str) -> str:
    """Expand only documented whole-token aliases for retrieval.

    The original user wording remains part of ``ResolvedContext``.  This
    canonical form is intended for routing and source lookup, not as a rewritten
    user prompt.
    """
    resolved = str(query or "")
    for alias, expansion in KNOWN_ALIASES.items():
        resolved = re.sub(
            rf"(?<!\w){re.escape(alias)}(?!\w)",
            expansion,
            resolved,
            flags=re.IGNORECASE,
        )
    return resolved


def _extract_marker(text: str, name: str) -> str:
    match = re.search(rf"(?im)^{re.escape(name)}:\s*(.+)$", text)
    return match.group(1).strip() if match else ""


def _extract_context(text: str) -> str:
    marker = re.search(
        r"(?im)^(?:CONTEXT|KONTEXT\s*\(zitierbar\s+mit\s+\[#\]\)):\s*$",
        text,
    )
    if not marker:
        return ""
    return re.split(
        r"(?im)^(?:SOURCES_JSON|FEEDBACK_LINK):",
        text[marker.end() :],
        maxsplit=1,
    )[0].strip()


def _extract_sources(text: str, context: str) -> tuple[dict[str, Any], ...]:
    raw = _extract_marker(text, "SOURCES_JSON")
    if raw:
        try:
            sources = json.loads(raw)
            if isinstance(sources, list):
                return tuple(source for source in sources if isinstance(source, dict))
        except (TypeError, ValueError, json.JSONDecodeError):
            pass

    fallback = []
    for number, title in re.findall(
        r"(?im)^\[(?:#\s*|Quelle\s+)(\d+)\]\s*([^\n]*)$", context
    ):
        fallback.append({"source_id": f"#{number}", "title": title.strip()})
    return tuple(fallback)


def rag_result_from_sources(sources: list[dict[str, Any]]) -> str:
    """Return the untouched rag_chat result carried by native source events."""
    for source in sources or []:
        if not isinstance(source, dict):
            continue
        source_name = str((source.get("source") or {}).get("name") or "").casefold()
        if "rag_chat" not in source_name:
            continue
        documents = source.get("document")
        if isinstance(documents, list):
            return "\n".join(str(document or "") for document in documents)
    return ""


def _declared_evidence_bundle(text: str) -> EvidenceBundle | None:
    raw = _extract_marker(text, "EVIDENCE_BUNDLE_JSON")
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    if value.get("schema_version") != "kahle.evidence-bundle.v1":
        return None
    status = str(value.get("status") or "")
    if status not in {"supported", "partially_supported", "unsupported"}:
        return None
    return EvidenceBundle(
        status=status,
        supported_claims=tuple(value.get("supported_claims") or ()),
        missing_information=tuple(str(item) for item in value.get("missing_information") or ()),
        conflicts=tuple(str(item) for item in value.get("conflicts") or ()),
        sources=tuple(
            item for item in value.get("sources") or () if isinstance(item, dict)
        ),
    )


def _supported_claims(context: str) -> tuple[str, ...]:
    claims = []
    for block in re.split(r"(?im)(?=^\[(?:#\s*|Quelle\s+)\d+\])", context):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) > 1:
            claims.append(" ".join(lines[1:])[:500])
    return tuple(claims)


def _procedure_is_supported(context: str) -> bool:
    folded = _fold(context)
    action_patterns = (
        r"\bo?ffn\w*",
        r"\bnavigier\w*",
        r"\bklick\w*",
        r"\bwaehl\w*",
        r"\b(?:eingeb\w*|gib)\b",
        r"\berfass\w*",
        r"\bspeicher\w*",
        r"\bbestaetig\w*",
        r"\berstell\w*",
    )
    return sum(bool(re.search(pattern, folded)) for pattern in action_patterns) >= 3


def _evidence_bundle(rag_result: str, procedural: bool) -> EvidenceBundle:
    text = str(rag_result or "")
    declared = _declared_evidence_bundle(text)
    if declared is not None:
        return declared
    found = bool(re.search(r"(?im)^FOUND:\s*true\s*$", text))
    clarification = bool(
        re.search(r"(?im)^CLARIFICATION_REQUIRED:\s*true\s*$", text)
    )
    context = _extract_context(text)
    claims = _supported_claims(context)
    sources = _extract_sources(text, context)

    if clarification or not found:
        return EvidenceBundle(
            status="unsupported",
            missing_information=(
                "Für die konkrete Anfrage liegt keine ausreichende freigegebene Evidenz vor.",
            ),
            sources=sources,
        )
    if procedural and not _procedure_is_supported(context):
        return EvidenceBundle(
            status="partially_supported",
            supported_claims=claims,
            missing_information=(
                "Die Evidenz beschreibt das Thema, enthält aber keine ausreichende Anleitung.",
            ),
            sources=sources,
        )
    return EvidenceBundle(
        status="supported",
        supported_claims=claims,
        sources=sources,
    )


def _has_conversation_reference(messages: list[dict[str, Any]], query: str) -> bool:
    user_messages = [
        message
        for message in messages
        if isinstance(message, dict) and message.get("role") == "user"
    ]
    if len(user_messages) < 2:
        return False
    folded = _fold(query)
    return len(folded.split()) <= 5 or any(
        token in folded.split() for token in ("dort", "alles", "beide", "allgemein")
    )


def build_decision(
    *,
    query: str,
    resolved_query: str,
    messages: list[dict[str, Any]],
    model_id: str,
    permission_scope: dict[str, Any],
    rag_result: str,
) -> HarnessDecision:
    """Build an observable decision without changing the live answer path."""
    original = str(query or "").strip()
    retrieval_query = str(resolved_query or original).strip()
    procedural = _is_procedural(retrieval_query)
    clarification = bool(
        re.search(r"(?im)^CLARIFICATION_REQUIRED:\s*true\s*$", rag_result or "")
    )
    clarification_question = (
        _extract_marker(rag_result or "", "ANSWER") if clarification else ""
    )
    evidence = _evidence_bundle(rag_result, procedural)

    return HarnessDecision(
        schema_version=SCHEMA_VERSION,
        model_profile={
            "id": str(model_id or ""),
            "harness_policy": "shared",
        },
        user_intent=UserIntent(
            kind=_intent_kind(retrieval_query),
            procedural=procedural,
            clarification_required=clarification,
            clarification_question=clarification_question,
        ),
        resolved_context=ResolvedContext(
            original_query=original,
            retrieval_query=retrieval_query,
            aliases=_aliases_in_query(original),
            conversation_reference=_has_conversation_reference(messages, original),
        ),
        retrieval_plan=RetrievalPlan(
            required_tool="rag_chat",
            queries=(retrieval_query,),
            permission_scope=dict(permission_scope or {}),
        ),
        evidence_bundle=evidence,
        answer_contract=AnswerContract(),
        events=(
            {"type": "intent/started"},
            {"type": "intent/completed"},
            {"type": "retrieval/started", "tool": "rag_chat"},
            {
                "type": "retrieval/completed",
                "tool": "rag_chat",
                "source_count": len(evidence.sources),
            },
            {"type": "evidence/completed", "status": evidence.status},
        ),
    )


def build_shadow_decision(**kwargs: Any) -> HarnessDecision:
    """Backward-compatible name for callers still running comparison mode."""
    return build_decision(**kwargs)
