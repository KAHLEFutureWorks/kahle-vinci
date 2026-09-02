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

_PERSON_NAME_WORD = (
    r"(?!(?:der|die|das|den|dem|ein|eine|einen|einem|einer|"
    r"ansprechpartner|kontakt(?:daten)?|rolle|position|abteilung|team|standort|"
    r"onboarding|prozess|verkaufer|serviceberater|servicekraft|mitarbeiter)\b)[\w.-]+"
)

_ORGANIZATION_UNIT_PATTERN = (
    r"(?:personal(?:wesen|abteilung|bereich)?|hr|"
    r"(?:finanz)?buchhaltung|rechnungslegung|disposition|controlling|"
    r"marketing|it|edv|verkauf|service|teiledienst)"
)
_FUNCTIONAL_CONTACT_TOPIC_PATTERN = (
    r"(?:bewerbung(?:en)?|karriere|datenschutz|krankmeldung(?:en)?)"
)
_EMAIL_LITERAL = re.compile(r"(?i)\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b")
_PHONE_LITERAL = re.compile(r"(?<!\w)(?:\+?\d[\d ()/.-]{4,}\d)(?!\w)")


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
class RelationRequirement:
    subject_type: str
    predicate: str
    object: str
    evidence_scope: str = "single_passage"


@dataclass(frozen=True)
class InformationNeed:
    kind: str
    domain: str
    document_types: tuple[str, ...] = ()
    evidence_capabilities: tuple[str, ...] = ()
    entity: str = ""
    relation: RelationRequirement | None = None


@dataclass(frozen=True)
class RetrievalPlan:
    required_tools: tuple[str, ...]
    queries: tuple[str, ...]
    permission_scope: dict[str, Any]
    information_needs: tuple[InformationNeed, ...] = ()
    mode: str = "shadow"

    @property
    def required_tool(self) -> str:
        """Compatibility view for single-tool consumers of the harness."""
        return self.required_tools[0] if len(self.required_tools) == 1 else "multi_source"


@dataclass(frozen=True)
class EvidenceBundle:
    status: str
    supported_claims: tuple[Any, ...] = ()
    missing_information: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    sources: tuple[dict[str, Any], ...] = ()
    sync_completed_at: str | None = None
    stale: bool = False


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
    allowed_contact_values: tuple[str, ...] = ()


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
        payload = asdict(self)
        payload["retrieval_plan"]["required_tool"] = self.retrieval_plan.required_tool
        return payload

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
            "vorliegt und welche Information fehlt. Wenn sync_completed_at gesetzt ist, nenne "
            "den Zeitpunkt als letzten Stand des Personio-Mitarbeiterverzeichnisses. Wenn stale "
            "true ist, kennzeichne diesen Stand ausdrücklich als möglicherweise veraltet. "
            "E-Mail-Adressen und Telefonnummern darfst du ausschließlich wortgleich aus "
            "answer_contract.allowed_contact_values übernehmen. "
            "Erzeuge genau eine endgültige Antwort."
        )

    def direct_answer(self) -> str:
        """Return a stable pre-answer result only when no synthesis is required."""
        if self.user_intent.clarification_required:
            return self.user_intent.clarification_question
        if _contact_information_requested(self.resolved_context.retrieval_query):
            if self.evidence_bundle.status == "unsupported":
                return "Dazu habe ich keine verlässliche freigegebene Kontaktinformation."
            if any(
                need.kind == "organization_contact"
                for need in self.retrieval_plan.information_needs
            ):
                return _organization_contact_answer(
                    self.resolved_context.retrieval_query,
                    self.retrieval_plan,
                    self.evidence_bundle,
                )
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


def _organization_unit_reference(query: str) -> bool:
    return bool(re.search(rf"\b{_ORGANIZATION_UNIT_PATTERN}\b", _fold(query)))


def _contact_information_requested(query: str) -> bool:
    folded = _fold(query)
    return bool(
        re.search(
            r"\b(?:e-?mail(?:-adresse)?|telefon(?:nummer)?|durchwahl|"
            r"kontakt(?:e|daten|informationen|moglichkeiten)?|erreich\w*|"
            r"ansprechpartner(?:in|innen)?)\b",
            folded,
        )
        or re.search(r"\bin\s+kontakt\b", folded)
        or _functional_contact_delivery_question(folded)
    )


def _functional_contact_delivery_question(folded_query: str) -> bool:
    """Recognize a requested destination for a documented functional topic."""
    if not re.search(rf"\b{_FUNCTIONAL_CONTACT_TOPIC_PATTERN}\b", folded_query):
        return False
    return bool(
        re.search(
            r"\b(?:wohin|wo|an\s+wen)\b.{0,80}"
            r"\b(?:hin)?(?:schick|send|reich|geb)\w*\b",
            folded_query,
        )
        or re.search(
            r"\b(?:hin)?(?:schick|send|reich|geb)\w*\b.{0,80}"
            r"\b(?:hin|ein|ab)\b",
            folded_query,
        )
    )


def _organizational_contact_question(query: str) -> bool:
    """Return whether both documented channels and current people may answer."""
    folded = _fold(query)
    if not _contact_information_requested(folded):
        return False
    return bool(
        _organization_unit_reference(folded)
        or re.search(rf"\b{_FUNCTIONAL_CONTACT_TOPIC_PATTERN}\b", folded)
    )


def _organization_unit_directory_question(query: str) -> bool:
    folded = _fold(query)
    if not _organization_unit_reference(folded):
        return False
    return bool(
        _contact_information_requested(folded)
        or re.search(
            r"\b(?:wer\s+arbeitet|welche\s+(?:mitarbeiter|mitarbeitenden|kollegen)|"
            r"mitarbeiter\s+(?:im|in))\b",
            folded,
        )
    )


def _requested_contact_channels(query: str) -> frozenset[str]:
    folded = _fold(query)
    channels = set()
    if re.search(r"\be-?mail(?:-adresse)?\b", folded):
        channels.add("email")
    if re.search(r"\b(?:telefon(?:nummer)?|durchwahl)\b", folded):
        channels.add("phone")
    if not channels and _contact_information_requested(folded):
        channels.add("any")
    return frozenset(channels)


def _contact_values(evidence: EvidenceBundle) -> tuple[str, ...]:
    values: list[str] = []
    for claim in evidence.supported_claims:
        if isinstance(claim, dict):
            for field in ("business_email", "email"):
                value = str(claim.get(field) or "").strip()
                if value and _EMAIL_LITERAL.fullmatch(value):
                    values.append(value)
            for field in ("business_phone", "phone"):
                value = str(claim.get(field) or "").strip()
                if value and len(re.sub(r"\D", "", value)) >= 6:
                    values.append(value)
            texts = (
                str(claim.get("evidence_span") or ""),
                str(claim.get("text") or ""),
            )
        else:
            texts = (str(claim or ""),)
        for text in texts:
            values.extend(match.group(0) for match in _EMAIL_LITERAL.finditer(text))
            values.extend(
                candidate
                for match in _PHONE_LITERAL.finditer(text)
                if _is_phone_literal(candidate := match.group(0).strip())
            )
    return tuple(dict.fromkeys(values))


def _is_phone_literal(value: str) -> bool:
    candidate = str(value or "").strip()
    if len(re.sub(r"\D", "", candidate)) < 6:
        return False
    if re.fullmatch(r"\d{1,4}[.-]\d{1,2}[.-]\d{2,4}", candidate):
        return False
    return True


def _contact_value_channels(values: tuple[str, ...]) -> frozenset[str]:
    return frozenset(
        "email" if _EMAIL_LITERAL.fullmatch(value) else "phone"
        for value in values
    )


def _cited_contact_instructions(evidence: EvidenceBundle) -> tuple[tuple[str, str], ...]:
    instructions: list[tuple[str, str]] = []
    for claim in evidence.supported_claims:
        if not isinstance(claim, dict):
            continue
        text = str(claim.get("evidence_span") or claim.get("text") or "").strip()
        source_id = str(claim.get("source_id") or "").strip()
        folded = _fold(text)
        if text and source_id and re.search(
            r"\b(?:ticket(?:system)?|intranet|funktionspostfach|postfach|"
            r"kontakt|erreich\w*|wenden)\b",
            folded,
        ):
            instructions.append((text, source_id))
    return tuple(dict.fromkeys(instructions))


def _apply_contact_evidence_requirement(
    query: str, evidence: EvidenceBundle
) -> tuple[EvidenceBundle, tuple[str, ...]]:
    requested = _requested_contact_channels(query)
    if not requested:
        return evidence, ()
    allowed_values = _contact_values(evidence)
    available = _contact_value_channels(allowed_values)
    satisfied = (
        bool(available) or bool(_cited_contact_instructions(evidence))
        if "any" in requested
        else requested.issubset(available)
    )
    if evidence.status == "unsupported" or not satisfied:
        return (
            EvidenceBundle(
                status="unsupported",
                missing_information=(
                    "Die freigegebene Evidenz enthält keine passende Kontaktinformation.",
                ),
                sources=evidence.sources,
                sync_completed_at=evidence.sync_completed_at,
                stale=evidence.stale,
            ),
            (),
        )
    return evidence, allowed_values


def _organization_contact_answer(
    query: str, retrieval_plan: RetrievalPlan, evidence: EvidenceBundle
) -> str:
    channels = _requested_contact_channels(query)
    del retrieval_plan
    people = []
    for claim in evidence.supported_claims:
        if not isinstance(claim, dict):
            continue
        name = str(claim.get("display_name") or "").strip()
        email = str(claim.get("business_email") or claim.get("email") or "").strip()
        phone = str(claim.get("business_phone") or claim.get("phone") or "").strip()
        contacts = []
        if email and ("email" in channels or "any" in channels):
            contacts.append(email)
        if phone and ("phone" in channels or "any" in channels):
            contacts.append(phone)
        if name and contacts:
            people.append(f"- {name} – {' · '.join(contacts)}")

    documented = []
    allowed = set(_contact_values(evidence))
    for claim in evidence.supported_claims:
        if not isinstance(claim, dict):
            continue
        text = str(claim.get("evidence_span") or claim.get("text") or "").strip()
        source_id = str(claim.get("source_id") or "").strip()
        if text and source_id and (
            any(value in text for value in allowed)
            or (text, source_id) in _cited_contact_instructions(evidence)
        ):
            documented.append(f"{text} [{source_id}]")

    sections = []
    if documented:
        sections.append(
            "Dokumentierter Kontaktweg:\n\n"
            + "\n".join(dict.fromkeys(documented))
        )
    if people:
        sections.append(
            "Aktuelle Ansprechpersonen aus Personio:\n\n"
            + "\n".join(dict.fromkeys(people))
        )
    return "\n\n".join(sections) or (
        "Dazu habe ich keine verlässliche freigegebene Kontaktinformation."
    )


def _citation_identifier(value: str) -> str:
    normalized = re.sub(r"\s+", "", str(value or "").lstrip("#"))
    return (
        normalized.upper()
        if re.fullmatch(r"[PR]\d+", normalized, re.IGNORECASE)
        else normalized
    )


def _source_identifier(source: dict[str, Any]) -> str:
    value = source.get("id") or source.get("number") or source.get("source_id") or ""
    return _citation_identifier(str(value)) if str(value).strip() else ""


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

    folded_text = _fold(text)
    resolved_context = _mapping(_decision_value(decision, "resolved_context"))
    retrieval_query = _fold(resolved_context.get("retrieval_query") or "")
    claim_text = " ".join(
        str(item.get("text") or "") if isinstance(item, dict) else str(item or "")
        for item in evidence.get("supported_claims") or []
    )
    folded_claims = _fold(claim_text)

    if (
        re.search(r"\b(?:erfind|dicht|fingier|glaubwurdig(?:en|er)? wortlaut)\w*", retrieval_query)
        and re.search(
            r"\b(?:richtlinie|policy|arbeitsanweisung|vorgabe|regelung|freigabe)\w*",
            folded_text,
        )
    ):
        add(
            "fabricated_internal_authority",
            "Eine interne Regel oder Freigabe darf nicht auf Aufforderung erfunden werden.",
        )

    technical_approval = re.search(
        r"\b(?:technisch\w*\s+)?(?:problemlos|machbar|umsetzbar|realisierbar|moglich)\b",
        folded_text,
    )
    if technical_approval and not re.search(
        r"\b(?:machbar|umsetzbar|realisierbar|technisch moglich|technisch freigegeben)\b",
        folded_claims,
    ):
        add(
            "unsupported_technical_approval",
            "Die technische Machbarkeit ist in den unterstützten Aussagen nicht bestätigt.",
        )

    privacy_clearance_pattern = (
        r"(?:\b(?:keine|nicht|ohne)\s+(?:weitere\s+)?"
        r"(?:datenschutz(?:rechtliche)?\w*\s*)?"
        r"(?:prufung|freigabe|bedenken|problem)\w*|"
        r"\bdatenschutz\w*\s+(?:ist\s+)?(?:nicht|kein\w*|ohne)\s+"
        r"(?:erforderlich|notwendig|problematisch|bedenklich))"
    )
    privacy_approval = re.search(privacy_clearance_pattern, folded_text)
    if privacy_approval and not re.search(privacy_clearance_pattern, folded_claims):
        add(
            "unsupported_privacy_approval",
            "Eine Datenschutzfreigabe ist in den unterstützten Aussagen nicht bestätigt.",
        )
    feedback_placeholder = re.search(
        r"\[[^\]]*feedback[- ]link[^\]]*"
        r"(?:einfug|tool-ergebnis|vorhanden)[^\]]*\]",
        folded_text,
    ) or re.search(
        r"wissensfehler melden.{0,12}\[[^\]]*\blink\b[^\]]*"
        r"(?:rag|falls|vorhanden)[^\]]*\]",
        folded_text,
    )
    if feedback_placeholder:
        add(
            "feedback_link_placeholder",
            "Die Antwort enthält einen Platzhalter statt des kanonischen Feedback-Links.",
        )

    permission_scope = _mapping(retrieval_plan.get("permission_scope"))
    if not str(permission_scope.get("user_id") or "").strip():
        add(
            "permission_scope_missing",
            "Der Retrieval-Plan enthält keinen gebundenen Benutzerkontext.",
        )

    sources = [item for item in evidence.get("sources") or [] if isinstance(item, dict)]
    source_ids = {
        _source_identifier(item)
        for item in sources
        if _source_identifier(item)
    }
    cited_ids = set(
        _citation_identifier(value)
        for value in re.findall(
            r"\[(?:#\s*|Quelle\s*)?((?:[PR]\s*)?\d+)\]",
            text,
            re.IGNORECASE,
        )
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


def _has_named_person_reference(query: str) -> bool:
    """Recognize explicit employee profile and contact questions only."""
    raw = str(query or "")
    return bool(
        re.search(
            r"(?iu)\b(?:wer\s+ist|wo\s+arbeitet|was\s+macht|"
            r"was\s+wei(?:ß|ss)t\s+du(?:\s+alles)?\s+über|"
            r"wie\s+erreiche(?:\s+ich)?|wie\s+lautet.*?(?:von|für)|"
            r"wie\s+kann\s+ich|"
            r"welche\s+(?:telefonnummer|e-?mail(?:-adresse)?|durchwahl)\s+hat|"
            r"welche\s+(?:position|rolle|abteilung|team|standort)\s+hat|"
            r"mit\s+wem\s+arbeitet|was\s+hat|wie\s+hängen)\s+"
            rf"(?:unser(?:e|en)?\s+)?{_PERSON_NAME_WORD}\s+{_PERSON_NAME_WORD}",
            raw,
        )
        or re.search(
            r"(?iu)\b(?:kontakt(?:daten|informationen|m(?:ö|oe)glichkeiten)?|"
            r"e-?mail(?:-adresse)?|telefon(?:nummer)?|durchwahl)\b"
            r".{0,80}?\b(?:von|für)\s+"
            rf"(?:unser(?:e|en)?\s+)?{_PERSON_NAME_WORD}\s+{_PERSON_NAME_WORD}",
            raw,
        )
        or re.search(
            r"(?iu)\b(?:infos?|informationen|details)\s+(?:über|ueber|zu)\s+"
            rf"(?:unser(?:e|en)?\s+)?{_PERSON_NAME_WORD}\s+{_PERSON_NAME_WORD}",
            raw,
        )
    )


def classify_personio_directory_intent(query: str) -> str:
    """Classify bounded directory sub-intents for planning and execution."""
    raw = str(query or "")
    folded = _fold(raw)
    if (
        "onboard" in folded
        and re.search(r"\b(?:wer|welche|mitarbeiter|personen)\b", folded)
        and "onboarding-prozess" not in folded
    ):
        return "onboarding_search"
    if _has_supervisor_reference(folded):
        return "supervisor_lookup"
    if re.search(r"\bmit\s+wem\b.*\b(?:arbeitet|zusammen)\b", folded):
        return "coworker_lookup"
    if _organization_unit_directory_question(raw):
        return "directory_search"
    if _has_named_person_reference(raw):
        return "person_lookup"
    return "directory_search"


def _directory_information_need(query: str) -> bool:
    folded = _fold(query)
    if _functional_responsibility_question(folded):
        return False
    if _organizational_contact_question(folded):
        return True
    if _organization_unit_directory_question(folded):
        return True
    if _explicit_onboarding_people_request(folded):
        return True
    if _has_supervisor_reference(folded):
        return True
    if _has_named_person_reference(query):
        return True
    if _controlled_role_list_request(folded):
        return True
    contact_or_list_patterns = (
        r"\bansprechpartner\b",
        r"\bkontaktdaten\b",
        r"\b(?:e-?mail|telefonnummer|durchwahl)\b.*\b(?:von|fur)\b",
        r"\bwie\s+(?:lautet|erreiche)\b.*\b(?:e-?mail|telefon|durchwahl)\b",
        r"\bwer\s+arbeitet\b",
        r"\bwelche\s+(?:mitarbeiter(?:innen)?|kolleg(?:en|innen))\b",
        r"\b(?:mitarbeiter(?:innen)?|kolleg(?:en|innen))\s+im\b",
    )
    return any(re.search(pattern, folded) for pattern in contact_or_list_patterns)


def _has_supervisor_reference(query: str) -> bool:
    """Recognize explicit supervisor wording plus one controlled character typo."""
    folded = _fold(query)
    if re.search(r"\b(?:fuhrungskraft|vorgesetzt\w*)\b", folded):
        return True
    return any(
        token.startswith("fuhrung") and _one_character_apart(token, "fuhrungskraft")
        for token in folded.split()
    )


def _one_character_apart(left: str, right: str) -> bool:
    if left == right or abs(len(left) - len(right)) > 1:
        return False
    index_left = index_right = edits = 0
    while index_left < len(left) and index_right < len(right):
        if left[index_left] == right[index_right]:
            index_left += 1
            index_right += 1
            continue
        edits += 1
        if edits > 1:
            return False
        if len(left) > len(right):
            index_left += 1
        elif len(right) > len(left):
            index_right += 1
        else:
            index_left += 1
            index_right += 1
    return edits + (index_left < len(left)) + (index_right < len(right)) == 1


def _controlled_role_list_request(folded_query: str) -> bool:
    """Recognize only explicit directory-list requests for approved role families."""
    return bool(
        re.search(
            r"\b(?:wer\s+(?:sind|ist|arbeitet)|welche|wie\s+hei(?:ss)?en|nenn(?:e)?(?:\s+mir)?|"
            r"(?:liste|zeig(?:e)?|gib)(?:\s+mir)?)\b.*\b(?:"
            r"serviceassisten(?:z(?:en)?|t(?:in|innen|en)?)|"
            r"serviceberater\w*|servicekr(?:a|ae)ft(?:e|en)?|"
            r"(?:automobil)?verkaufer|verkauf|teiledienst\w*)\b",
            folded_query,
        )
    )


def _explicit_onboarding_people_request(folded_query: str) -> bool:
    if "onboard" not in folded_query or re.search(r"\bonboarding[-\s]+prozess\b", folded_query):
        return False
    return bool(
        re.search(r"\bwer\s+ist\b.*\bonboard", folded_query)
        or re.search(r"\bwelche\b.*\b(?:sind|kommen)\b.*\bonboard", folded_query)
        or re.search(r"\b(?:mitarbeiter(?:innen)?|personen)\b.*\bonboard", folded_query)
    )


def _rag_information_need(query: str) -> bool:
    folded = _fold(query)
    if _organizational_contact_question(folded):
        return True
    if _directory_information_need(query) and re.search(
        r"\b(?:erreich\w*|kontakt(?:daten)?|telefon(?:nummer)?|durchwahl|e-?mail)\b",
        folded,
    ):
        return False
    relation = bool(
        re.search(r"\bmit\b.+\bzu\s+tun\b", folded)
        or re.search(r"\bhang\w*\b.*\bzusammen\b", folded)
        or "zusammenhang" in folded
    )
    rag_terms = (
        "projekt", "system", "prozess", "arbeitsanweisung", "arbeitsweise",
        "verantwortlichkeit", "verantwortlich", "anleitung",
    )
    return (
        relation
        or _functional_responsibility_question(folded)
        or _is_procedural(query)
        or any(term in folded for term in rag_terms)
    )


def _functional_responsibility_question(folded_query: str) -> bool:
    return bool(
        re.search(r"\bmahnung\w*\b", folded_query)
        or re.search(r"\bkundenbeschwerd\w*\b", folded_query)
    )


def _intent_kind(query: str) -> str:
    return "employee_directory" if _directory_information_need(query) else "internal_knowledge"


def _relation_target(query: str) -> str:
    """Return only a target explicitly named in a person-relation question."""
    match = re.search(
        r"(?iu)\bwas\s+hat\s+[A-ZÄÖÜ][\w.-]+\s+[A-ZÄÖÜ][\w.-]+\s+"
        r"mit\s+([\w.-]+(?:\s+[\w.-]+){0,2}?)\s+zu\s+tun\b",
        str(query or ""),
    )
    if match:
        return match.group(1).strip(" .?!,;:")
    return ""


def _internal_system_entity(query: str) -> str:
    """Extract an explicitly named internal system without inventing aliases."""
    relation_target = _relation_target(query)
    if relation_target:
        return relation_target
    match = re.search(
        r"(?iu)\b(?:in|im|mit|system)\s+(?:unser(?:em|en)\s+)?"
        r"([A-ZÄÖÜ][A-Za-zÄÖÜäöüß0-9.-]{1,30})\b",
        str(query or ""),
    )
    return match.group(1) if match else ""


def _information_needs(query: str) -> tuple[InformationNeed, ...]:
    """Describe required evidence before retrieval, independently of the model."""
    folded = _fold(query)
    relation_target = _relation_target(query)
    if _functional_responsibility_question(folded):
        return (
            InformationNeed(
                kind="functional_responsibility",
                domain="customer_processes",
                document_types=("process_description", "responsibility_matrix"),
                evidence_capabilities=("approved_functional_responsibility",),
            ),
        )
    if _organizational_contact_question(folded):
        return (
            InformationNeed(
                kind="organization_contact",
                domain="internal_organization",
                document_types=(
                    "contact_directory",
                    "responsibility_matrix",
                ),
                evidence_capabilities=("current_person_record", "contact_details"),
            ),
        )
    if relation_target:
        return (
            InformationNeed(
                kind="directory_record",
                domain="employee_directory",
                evidence_capabilities=("current_person_record",),
            ),
            InformationNeed(
                kind="relationship",
                domain="internal_systems",
                document_types=("responsibility_matrix", "system_documentation"),
                evidence_capabilities=("explicit_relationship",),
                entity=relation_target,
                relation=RelationRequirement(
                    subject_type="person",
                    predicate="related_to",
                    object=relation_target,
                ),
            ),
        )

    usage_scope = re.search(
        r"\b(?:an\s+welchen|welche[nr]?|wo)\s+(?:kahle[- ]?)?standort\w*\b",
        folded,
    ) and re.search(r"\b(?:eingesetzt|genutzt|verwendet|verfugbar|ausgerollt)\w*\b", folded)
    if usage_scope:
        entity_match = re.search(
            r"\b(?:wird|werden|ist|sind)\s+([A-ZÄÖÜ][A-Za-zÄÖÜäöüß0-9.-]{1,30})\b",
            str(query or ""),
        )
        return (
            InformationNeed(
                kind="system_usage_locations",
                domain="internal_systems",
                document_types=("system_overview", "system_documentation"),
                evidence_capabilities=("explicit_usage_scope",),
                entity=entity_match.group(1) if entity_match else "",
            ),
        )

    opening_hours = bool(re.search(
        r"\b(?:offnungszeiten|oeffnungszeiten|offnungszeit|oeffnungszeit)\b", folded
    ))
    if opening_hours:
        return (
            InformationNeed(
                kind="opening_hours",
                domain="internal_locations",
                document_types=("location_profile",),
                evidence_capabilities=("opening_hours",),
            ),
        )

    if (
        "standort" in folded
        and all(department in folded for department in ("verkauf", "service", "teiledienst"))
    ):
        return (
            InformationNeed(
                kind="location_department_overview",
                domain="internal_locations",
                document_types=("location_profile",),
                evidence_capabilities=("location_department_overview",),
            ),
        )

    if "arbeitsanweisung" in folded and any(
        marker in folded
        for marker in ("freigab", "pruf", "veroffentlich", "fachlich", "ablauf")
    ):
        return (
            InformationNeed(
                kind="workflow",
                domain="knowledge_governance",
                document_types=("work_instruction", "process_description"),
                evidence_capabilities=("approval_workflow", "procedure"),
            ),
        )

    system_entity = _internal_system_entity(query)
    if _is_procedural(query):
        return (
            InformationNeed(
                kind="procedure",
                domain="internal_systems" if system_entity else "internal_processes",
                document_types=("work_instruction", "process_description"),
                evidence_capabilities=("procedure",),
                entity=system_entity,
            ),
        )

    if _directory_information_need(query):
        return (
            InformationNeed(
                kind="directory_record",
                domain="employee_directory",
                evidence_capabilities=("current_person_record",),
            ),
        )

    return (
        InformationNeed(
            kind="internal_knowledge",
            domain="internal_general",
            document_types=("knowledge_document",),
            evidence_capabilities=("factual_support",),
        ),
    )


def plan_retrieval(
    query: str,
    resolved_query: str,
    messages: list[dict[str, Any]],
    model_id: str,
    permission_scope: dict[str, Any],
) -> RetrievalPlan:
    """Select required evidence sources from information needs, not model choice."""
    del query, messages, model_id
    retrieval_query = str(resolved_query or "").strip()
    directory_needed = _directory_information_need(retrieval_query)
    rag_needed = _rag_information_need(retrieval_query)
    required_tools = (
        ("personio_directory", "rag_chat")
        if directory_needed and rag_needed
        else ("personio_directory",)
        if directory_needed
        else ("rag_chat",)
    )
    return RetrievalPlan(
        required_tools=required_tools,
        queries=(retrieval_query,),
        permission_scope=dict(permission_scope or {}),
        information_needs=_information_needs(retrieval_query),
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
    sources = tuple(
        item for item in value.get("sources") or () if isinstance(item, dict)
    )
    source_ids = {
        _source_identifier(item) for item in sources if _source_identifier(item)
    }
    claims = tuple(value.get("supported_claims") or ())
    claim_ids: list[str] = []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        source_id = _citation_identifier(str(claim.get("source_id") or ""))
        if source_id and source_id not in source_ids:
            return EvidenceBundle(
                status="unsupported",
                missing_information=(
                    "Das EvidenceBundle enthält einen Claim ohne vorhandene Quellen-ID.",
                ),
                conflicts=("evidence_bundle_claim_source_invalid",),
                sources=sources,
            )
        claim_id = str(claim.get("claim_id") or "").strip()
        if claim_id:
            claim_ids.append(claim_id)
    if len(claim_ids) != len(set(claim_ids)):
        return EvidenceBundle(
            status="unsupported",
            missing_information=("Das EvidenceBundle enthält doppelte Claim-IDs.",),
            conflicts=("evidence_bundle_claim_id_duplicate",),
            sources=sources,
        )
    return EvidenceBundle(
        status=status,
        supported_claims=claims,
        missing_information=tuple(str(item) for item in value.get("missing_information") or ()),
        conflicts=tuple(str(item) for item in value.get("conflicts") or ()),
        sources=sources,
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


def _functional_responsibility_evidence(rag_result: str) -> EvidenceBundle:
    """Keep responsibility questions fail-closed until a role-only mapping is approved."""
    evidence = _evidence_bundle(rag_result, procedural=False)
    return EvidenceBundle(
        status="unsupported",
        missing_information=(
            "Für diese fachliche Zuständigkeit liegt keine freigegebene, "
            "eindeutig auf Personio abbildbare Rollen-Zuordnung vor.",
        ),
        sources=evidence.sources,
    )


_PERSONIO_CURRENT_FIELDS = frozenset(
    {
        "display_name",
        "first_name",
        "last_name",
        "position",
        "department",
        "team",
        "office",
        "business_email",
        "business_phone",
        "email",
        "phone",
    }
)
_PERSONIO_OWNED_RAG_FIELDS = frozenset(
    {
        "personio_id",
        "display_name",
        "first_name",
        "last_name",
        "position",
        "department",
        "team",
        "office",
        "business_email",
        "business_phone",
        "email",
        "phone",
        "employment_status",
        "source_updated_at",
        "supervisor_personio_id",
        "supervisor",
        "supervisor_id",
        "supervisor_name",
        "manager",
        "manager_id",
        "manager_name",
    }
)
_RAG_CLAIM_ALLOWED_FIELDS = frozenset(
    {
        "claim_id",
        "source_id",
        "text",
        "evidence_span",
        "document_id",
        "version_id",
        "claim_type",
        "field",
    }
)
_PERSON_ENTITY_EXCLUSION_TOKENS = frozenset(
    {
        "abteilung",
        "bereich",
        "das",
        "dem",
        "den",
        "der",
        "die",
        "ein",
        "eine",
        "einem",
        "einen",
        "gruppe",
        "kg",
        "gmbh",
        "organisation",
        "team",
        "unternehmen",
    }
)
_PERSONIO_RELATION_MARKER = re.compile(
    r"\b(?:chef\w*|fuhr\w*|fuhrungskraft|leit\w*|manager\w*|"
    r"supervisor|teamleit\w*|vorgesetzt\w*)\b"
)


def _has_named_person_entity(text: str) -> bool:
    """Recognize a likely two-token personal name, excluding organization labels."""
    for match in re.finditer(
        r"\b(?:[A-ZÄÖÜ][A-Za-zÄÖÜäöüß.-]*\s+){1,2}[A-ZÄÖÜ][A-Za-zÄÖÜäöüß.-]*\b",
        text,
    ):
        tokens = _fold(match.group(0)).split()
        if not any(token in _PERSON_ENTITY_EXCLUSION_TOKENS for token in tokens):
            return True
    return False


def _contains_contact_literal(text: str) -> bool:
    return bool(
        _EMAIL_LITERAL.search(text)
        or any(
            _is_phone_literal(match.group(0).strip())
            for match in _PHONE_LITERAL.finditer(text)
        )
    )


def _claim_clauses(text: str) -> tuple[str, ...]:
    return tuple(
        clause.strip()
        for clause in re.split(r";|[.!?](?=\s|$)|\n+", text)
        if clause.strip()
    )


def _normalized_claim_field_name(value: Any) -> str:
    raw = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(value or ""))
    return re.sub(r"[^a-z0-9]+", "_", _fold(raw)).strip("_")


def _personio_evidence(personio_result: Any) -> EvidenceBundle:
    """Convert the internal directory response into safe, cited harness evidence."""
    if isinstance(personio_result, EvidenceBundle):
        return personio_result
    if not isinstance(personio_result, dict):
        return EvidenceBundle(
            status="unsupported",
            missing_information=(
                "Für die konkrete Anfrage liegt keine aktuelle Personio-Verzeichnisevidenz vor.",
            ),
        )

    source_by_id: dict[str, dict[str, Any]] = {}
    for item in personio_result.get("sources") or ():
        if not isinstance(item, dict):
            continue
        source_id = _source_identifier(item)
        if re.fullmatch(r"P[1-9]\d*", source_id):
            source_by_id[source_id] = dict(item, id=source_id)

    claims: list[dict[str, Any]] = []
    for item in personio_result.get("claims") or ():
        if not isinstance(item, dict):
            continue
        source_id = _citation_identifier(str(item.get("source_id") or ""))
        if source_id not in source_by_id:
            continue
        claim = dict(item)
        claim["source_id"] = source_id
        claims.append(claim)

    sync_completed_at = personio_result.get("sync_completed_at")
    if not isinstance(sync_completed_at, str) or not sync_completed_at.strip():
        sync_completed_at = None
    stale = personio_result.get("stale") is True
    if str(personio_result.get("status") or "") == "ok" and claims:
        return EvidenceBundle(
            status="supported",
            supported_claims=tuple(claims),
            sources=tuple(source_by_id.values()),
            sync_completed_at=sync_completed_at,
            stale=stale,
        )
    return EvidenceBundle(
        status="unsupported",
        missing_information=(
            "Dazu finde ich im aktuellen Personio-Mitarbeiterverzeichnis keine passende freigegebene Information.",
        ),
        sync_completed_at=sync_completed_at,
        stale=stale,
    )


def _personio_authoritative_fields(claims: tuple[Any, ...]) -> set[str]:
    return {
        field
        for claim in claims
        if isinstance(claim, dict)
        for field in _PERSONIO_CURRENT_FIELDS
        if str(claim.get(field) or "").strip()
    }


def _rag_claim_asserts_personio_owned_data(claim: Any) -> bool:
    """Reject RAG claims that assert current person or supervisor data."""
    if isinstance(claim, dict):
        texts = (
            str(claim.get("text") or ""),
            str(claim.get("evidence_span") or ""),
        )
    else:
        texts = (str(claim or ""),)

    return any(
        _has_named_person_entity(clause)
        and bool(
            _PERSONIO_RELATION_MARKER.search(_fold(clause))
            or _contains_contact_literal(clause)
        )
        for text in texts
        for clause in _claim_clauses(text)
    )


def _sanitize_result_driven_rag_claim(claim: Any) -> Any | None:
    if _rag_claim_asserts_personio_owned_data(claim):
        return None
    if not isinstance(claim, dict):
        return claim
    normalized = {
        str(key): _normalized_claim_field_name(key) for key in claim
    }
    if any(
        field not in _RAG_CLAIM_ALLOWED_FIELDS | _PERSONIO_OWNED_RAG_FIELDS
        for field in normalized.values()
    ):
        return None
    filtered = {}
    for key, value in claim.items():
        field = normalized[str(key)]
        if field in _PERSONIO_OWNED_RAG_FIELDS:
            continue
        if field == "field":
            if _normalized_claim_field_name(value) not in _PERSONIO_OWNED_RAG_FIELDS:
                return None
            continue
        filtered[field] = value
    return filtered if set(filtered) - {"claim_id", "source_id"} else None


def _result_driven_rag_evidence(rag_result: Any, procedural: bool) -> EvidenceBundle:
    """Keep model-led RAG evidence within the documented-source authority."""
    evidence = (
        rag_result
        if isinstance(rag_result, EvidenceBundle)
        else _evidence_bundle(str(rag_result or ""), procedural)
    )
    if evidence.status == "unsupported":
        return EvidenceBundle(
            status="unsupported",
            missing_information=evidence.missing_information,
            conflicts=evidence.conflicts,
            sources=evidence.sources,
        )
    retained: list[Any] = []
    evidence_changed = False
    for claim in evidence.supported_claims:
        sanitized = _sanitize_result_driven_rag_claim(claim)
        if sanitized is None:
            evidence_changed = True
            continue
        if sanitized != claim:
            evidence_changed = True
        retained.append(sanitized)
    if not evidence_changed:
        return evidence
    missing = tuple(
        dict.fromkeys(
            (*evidence.missing_information, "Aktuelle Personen- und Supervisor-Daten erfordern Personio-Evidenz.")
        )
    )
    return EvidenceBundle(
        status="partially_supported" if retained else "unsupported",
        supported_claims=tuple(retained),
        missing_information=missing,
        conflicts=tuple(
            dict.fromkeys(
                (*evidence.conflicts, "Personio ist führend für aktuelle Stammdaten und Führungskräfte.")
            )
        ),
        sources=evidence.sources,
    )


def _personio_display_names(claims: tuple[Any, ...]) -> tuple[str, ...]:
    names = []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        display_name = str(claim.get("display_name") or "").strip()
        first_and_last = " ".join(
            str(claim.get(field) or "").strip()
            for field in ("first_name", "last_name")
        ).strip()
        names.extend(name for name in (display_name, first_and_last) if name)
    return tuple(dict.fromkeys(_fold(name) for name in names))


def _is_unstructured_rag_master_data_assertion(
    claim: Any,
    personio_names: tuple[str, ...],
) -> bool:
    if not isinstance(claim, str) or not personio_names:
        return False
    folded = _fold(claim)
    if not _contains_personio_name(folded, personio_names):
        return False
    if _has_documented_relation_marker(folded):
        return False
    return _has_current_master_data_marker(folded)


def _contains_personio_name(folded_claim: str, personio_names: tuple[str, ...]) -> bool:
    return any(name in folded_claim for name in personio_names)


def _has_documented_relation_marker(folded_claim: str) -> bool:
    return any(
        marker in folded_claim
        for marker in (
            "projekt", "system", "prozess", "arbeitsanweisung", "arbeitsweise",
            "verantwort", "aufgabe", "zustandig", "zusammenhang", "zu tun",
        )
    )


def _is_complete_documented_relation_clause(folded_claim: str) -> bool:
    if any(marker in folded_claim for marker in ("moglicherweise", "eventuell", "vielleicht")):
        return False
    object_pattern = r"\b(?:projekt|system|prozess)\b"
    return bool(
        re.search(
            rf"\b(?:verantwort\w*|begleit\w*|unterstutz\w*|leit\w*)\b"
            rf"[^.!?]{{0,160}}{object_pattern}",
            folded_claim,
        )
        or re.search(
            rf"\barbeit\w*\s+(?:an|am)\b[^.!?]{{0,160}}{object_pattern}",
            folded_claim,
        )
        or (
            re.search(r"\bist\b", folded_claim)
            and re.search(r"\bbeteiligt\b", folded_claim)
            and re.search(object_pattern, folded_claim)
        )
    )


def _has_current_master_data_marker(folded_claim: str) -> bool:
    complete_documented_relation = _is_complete_documented_relation_clause(folded_claim)
    works_on_documented_relation = bool(
        re.search(r"\barbeit\w*\s+(?:an|am)\b", folded_claim)
        and complete_documented_relation
    )
    markers = (
        "position", "rolle", "team", "abteilung", "bereich",
        "standort", "office", "telefon", "e-mail", "email", "durchwahl",
    )
    if not complete_documented_relation:
        markers += (" ist ",)
    if not works_on_documented_relation:
        markers += (" arbeitet",)
    return any(
        marker in folded_claim
        for marker in markers
    )


def _split_mixed_unstructured_rag_claim(
    claim: Any,
    personio_names: tuple[str, ...],
) -> tuple[str, ...] | None:
    """Retain only independently supportable documented-relation clauses.

    The split is intentionally narrow. If a sentence cannot be assigned wholly
    to current master data or documented relation evidence, the caller drops it.
    """
    if not isinstance(claim, str):
        return None
    folded = _fold(claim)
    if not (
        _contains_personio_name(folded, personio_names)
        and _has_current_master_data_marker(folded)
        and _has_documented_relation_marker(folded)
    ):
        return None
    content = claim.strip()
    terminal = content[-1] if content.endswith((".", "!", "?")) else "."
    content = content.rstrip(".!? ")
    subject_match = re.match(r"(?is)^(.+?)\s+(?=ist\b|arbeitet\b)", content)
    if not subject_match:
        return ()
    subject = subject_match.group(1).strip()
    if not _contains_personio_name(_fold(subject), personio_names):
        return ()
    fragments = [
        fragment.strip()
        for fragment in re.split(r"\s*(?:,|;|\bund\b)\s*", content, flags=re.IGNORECASE)
        if fragment.strip()
    ]
    if len(fragments) < 2:
        return ()

    retained: list[str] = []
    dropped_master_data = False
    for fragment in fragments:
        expanded = (
            fragment
            if _contains_personio_name(_fold(fragment), personio_names)
            else f"{subject} {fragment}"
        )
        folded_fragment = _fold(expanded)
        is_relation = _is_complete_documented_relation_clause(folded_fragment)
        is_master_data = _has_current_master_data_marker(folded_fragment)
        if is_master_data and not is_relation:
            dropped_master_data = True
            continue
        if is_relation:
            retained.append(expanded.rstrip(".!? ") + terminal)
            continue
        return ()
    return tuple(retained) if dropped_master_data and retained else ()


def _without_superseded_rag_claims(
    claims: tuple[Any, ...],
    personio_fields: set[str],
    personio_names: tuple[str, ...],
) -> tuple[tuple[Any, ...], tuple[str, ...]]:
    retained: list[Any] = []
    conflicts: list[str] = []
    for claim in claims:
        split_claims = _split_mixed_unstructured_rag_claim(claim, personio_names)
        if split_claims is not None:
            retained.extend(split_claims)
            conflicts.append("Personio ist führend für aktuelle Stammdaten.")
            continue
        if _is_unstructured_rag_master_data_assertion(claim, personio_names):
            conflicts.append("Personio ist führend für aktuelle Stammdaten.")
            continue
        if not isinstance(claim, dict):
            retained.append(claim)
            continue
        source_id = _citation_identifier(str(claim.get("source_id") or ""))
        if not source_id.startswith("R"):
            retained.append(claim)
            continue
        superseded = {
            field
            for field in personio_fields
            if str(claim.get(field) or "").strip()
        }
        if isinstance(claim.get("field"), str) and claim["field"] in personio_fields:
            superseded.add(claim["field"])
        if not superseded:
            text = claim.get("text")
            if _is_unstructured_rag_master_data_assertion(text, personio_names):
                conflicts.append("Personio ist führend für aktuelle Stammdaten.")
                continue
            retained.append(claim)
            continue
        filtered = {
            key: value
            for key, value in claim.items()
            if key not in superseded and key != "field"
        }
        if set(filtered) - {"source_id"}:
            retained.append(filtered)
        conflicts.extend(
            f"Personio ist führend für aktuelle {field}." for field in sorted(superseded)
        )
    return tuple(retained), tuple(dict.fromkeys(conflicts))


def merge_evidence(
    rag_result: Any, personio_result: Any, *, result_driven: bool = False
) -> EvidenceBundle:
    """Merge distinct evidence sources while preserving their respective authority."""
    rag = (
        _result_driven_rag_evidence(rag_result, False)
        if result_driven
        else (
            rag_result
            if isinstance(rag_result, EvidenceBundle)
            else _evidence_bundle(str(rag_result or ""), False)
        )
    )
    personio = _personio_evidence(personio_result)
    personio_fields = _personio_authoritative_fields(personio.supported_claims)
    rag_claims, authority_conflicts = _without_superseded_rag_claims(
        rag.supported_claims,
        personio_fields,
        _personio_display_names(personio.supported_claims),
    )
    claims = tuple(personio.supported_claims) + rag_claims
    source_by_id: dict[str, dict[str, Any]] = {}
    for source in tuple(personio.sources) + tuple(rag.sources):
        source_id = _source_identifier(source)
        if source_id:
            source_by_id[source_id] = dict(source)

    if not claims:
        status = "unsupported"
    elif personio.status == rag.status == "supported":
        status = "supported"
    else:
        status = "partially_supported"
    missing = tuple(dict.fromkeys(personio.missing_information + rag.missing_information))
    conflicts = tuple(dict.fromkeys(personio.conflicts + rag.conflicts + authority_conflicts))
    return EvidenceBundle(
        status=status,
        supported_claims=claims,
        missing_information=missing,
        conflicts=conflicts,
        sources=tuple(source_by_id.values()),
        sync_completed_at=personio.sync_completed_at,
        stale=personio.stale,
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
    personio_result: Any = None,
) -> HarnessDecision:
    """Build an observable decision without changing the live answer path."""
    original = str(query or "").strip()
    retrieval_query = str(resolved_query or original).strip()
    procedural = _is_procedural(retrieval_query)
    retrieval_plan = plan_retrieval(
        original,
        retrieval_query,
        messages,
        model_id,
        permission_scope,
    )
    clarification = bool(
        re.search(r"(?im)^CLARIFICATION_REQUIRED:\s*true\s*$", rag_result or "")
    ) and "rag_chat" in retrieval_plan.required_tools
    clarification_question = (
        _extract_marker(rag_result or "", "ANSWER") if clarification else ""
    )
    if retrieval_plan.required_tools == ("personio_directory",):
        evidence = _personio_evidence(personio_result)
    elif retrieval_plan.required_tools == ("rag_chat",):
        evidence = (
            _functional_responsibility_evidence(rag_result)
            if _functional_responsibility_question(_fold(retrieval_query))
            else _evidence_bundle(rag_result, procedural)
        )
    else:
        evidence = merge_evidence(rag_result, personio_result)
    evidence, allowed_contact_values = _apply_contact_evidence_requirement(
        retrieval_query, evidence
    )

    retrieval_events = []
    for tool in retrieval_plan.required_tools:
        retrieval_events.append({"type": "retrieval/started", "tool": tool})
        source_count = sum(
            1
            for source in evidence.sources
            if tool == "personio_directory"
            and _source_identifier(source).startswith("P")
            or tool == "rag_chat"
            and not _source_identifier(source).startswith("P")
        )
        retrieval_events.append(
            {"type": "retrieval/completed", "tool": tool, "source_count": source_count}
        )

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
        retrieval_plan=retrieval_plan,
        evidence_bundle=evidence,
        answer_contract=AnswerContract(
            allowed_contact_values=allowed_contact_values,
        ),
        events=(
            {"type": "intent/started"},
            {"type": "intent/completed"},
            *retrieval_events,
            {"type": "evidence/completed", "status": evidence.status},
        ),
    )


def build_result_driven_decision(
    *,
    called_tools: tuple[str, ...],
    query: str,
    messages: list[dict[str, Any]],
    model_id: str,
    permission_scope: dict[str, Any],
    rag_result: Any = "",
    personio_result: Any = None,
) -> HarnessDecision | None:
    """Validate evidence from internal tools that actually ran in this request."""
    actual_tools = tuple(
        dict.fromkeys(
            str(tool or "")
            for tool in called_tools
            if str(tool or "") in {"personio_directory", "rag_chat"}
        )
    )
    if not actual_tools:
        return None

    original = str(query or "").strip()
    procedural = _is_procedural(original)
    if actual_tools == ("personio_directory",):
        evidence = _personio_evidence(personio_result)
    elif actual_tools == ("rag_chat",):
        evidence = _result_driven_rag_evidence(rag_result, procedural)
    else:
        evidence = merge_evidence(rag_result, personio_result, result_driven=True)

    retrieval_plan = RetrievalPlan(
        required_tools=actual_tools,
        queries=(original,),
        permission_scope=dict(permission_scope or {}),
        information_needs=(),
        mode="model_led",
    )
    clarification = bool(
        "rag_chat" in actual_tools
        and re.search(r"(?im)^CLARIFICATION_REQUIRED:\s*true\s*$", str(rag_result or ""))
    )
    retrieval_events = []
    for tool in actual_tools:
        retrieval_events.append({"type": "retrieval/started", "tool": tool})
        source_count = sum(
            1
            for source in evidence.sources
            if (
                tool == "personio_directory"
                and _source_identifier(source).startswith("P")
            )
            or (
                tool == "rag_chat"
                and not _source_identifier(source).startswith("P")
            )
        )
        retrieval_events.append(
            {"type": "retrieval/completed", "tool": tool, "source_count": source_count}
        )

    return HarnessDecision(
        schema_version=SCHEMA_VERSION,
        model_profile={
            "id": str(model_id or ""),
            "harness_policy": "shared",
        },
        user_intent=UserIntent(
            kind="internal_knowledge",
            procedural=procedural,
            clarification_required=clarification,
            clarification_question=(
                _extract_marker(str(rag_result or ""), "ANSWER") if clarification else ""
            ),
        ),
        resolved_context=ResolvedContext(
            original_query=original,
            retrieval_query=original,
            aliases=_aliases_in_query(original),
            conversation_reference=_has_conversation_reference(messages, original),
        ),
        retrieval_plan=retrieval_plan,
        evidence_bundle=evidence,
        answer_contract=AnswerContract(
            allowed_contact_values=_contact_values(evidence),
        ),
        events=(
            *retrieval_events,
            {"type": "evidence/completed", "status": evidence.status},
        ),
    )


def build_shadow_decision(**kwargs: Any) -> HarnessDecision:
    """Backward-compatible name for callers still running comparison mode."""
    return build_decision(**kwargs)
