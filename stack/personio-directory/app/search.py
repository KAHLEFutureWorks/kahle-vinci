from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Literal, Protocol

from .models import DirectoryQuery, PersonRecord
from .policy import public_payload


DirectoryIntent = Literal[
    "person_lookup", "directory_search", "coworker_lookup", "onboarding_search"
]
_ONBOARDING_WORD = re.compile(r"\bonboarding\b", re.IGNORECASE)
_COWORKER_PHRASE = re.compile(
    r"\bmit\s+wem\b.*\b(?:zusammenarbeit|zusammenarbeiten|arbeitet)\b",
    re.IGNORECASE,
)
_PERSON_LOOKUP_PHRASE = re.compile(
    r"\b(?:was\s+weisst\s+du\s+uber|wo\s+arbeitet|was\s+macht)\b",
    re.IGNORECASE,
)
_SHORT_PERSON_QUESTION = re.compile(r"^wer\s+ist\s+\w+(?:\s+\w+)*$")
_EMAIL = re.compile(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", re.IGNORECASE)
_STOP_WORDS = frozenset(
    {
        "aktuell",
        "alle",
        "bei",
        "arbeitet",
        "arbeiten",
        "das",
        "dem",
        "den",
        "der",
        "des",
        "die",
        "ein",
        "eine",
        "einem",
        "einen",
        "einer",
        "im",
        "in",
        "ist",
        "heissen",
        "heisst",
        "mit",
        "mitarbeitende",
        "mitarbeitenden",
        "mitarbeiter",
        "mitarbeitern",
        "nach",
        "neue",
        "neuen",
        "neuer",
        "neu",
        "onboarding",
        "sind",
        "team",
        "und",
        "uns",
        "von",
        "welche",
        "welcher",
        "welches",
        "wer",
        "wie",
        "zu",
    }
)
_ROLE_VARIANTS: dict[str, tuple[str, ...]] = {
    "serviceassistenz": ("serviceassistenz", "serviceassistent"),
    "verkaufer": ("verkaufer", "automobilverkaufer", "verkauf"),
}
_COLLABORATION_DISCLAIMER = (
    "Die Zuordnung beschreibt nur organisatorische Nähe und keine tatsächliche "
    "persönliche, fachliche oder projektbezogene Zusammenarbeit."
)


@dataclass(frozen=True)
class DirectoryEvidence:
    """Evidence-safe Personio data for the Knowledge Harness."""

    status: Literal["ok", "not_found", "not_ready"]
    claims: tuple[dict[str, object], ...]
    sources: tuple[dict[str, str], ...]
    sync_completed_at: str | None
    stale: bool


@dataclass(frozen=True)
class CoworkerResult:
    basis: Literal["team", "position_and_office", "department_and_office"] | None
    people: tuple[PersonRecord, ...]


class DirectoryIndex(Protocol):
    """Read-only subset supplied by ``QdrantDirectoryIndex``."""

    def indexed_personio_ids(self) -> set[str]: ...

    def people_by_personio_ids(
        self, personio_ids: set[str]
    ) -> dict[str, PersonRecord]: ...


def classify_directory_query(text: str) -> DirectoryIntent:
    """Classify only the directory-local question shape, deterministically."""
    normalized = _normalise_text(text)
    if _ONBOARDING_WORD.search(normalized):
        return "onboarding_search"
    if _COWORKER_PHRASE.search(normalized):
        return "coworker_lookup"
    if _is_controlled_role_description(normalized):
        return "directory_search"
    if _PERSON_LOOKUP_PHRASE.search(normalized) or _SHORT_PERSON_QUESTION.fullmatch(
        normalized
    ):
        return "person_lookup"
    return "directory_search"


class DirectorySearch:
    """Read-only, privacy-aware search over already synchronized people."""

    def __init__(
        self,
        index: DirectoryIndex,
        *,
        sync_completed_at: str | Callable[[], str | None] | None = None,
        stale: bool | Callable[[], bool] = False,
    ) -> None:
        self._index = index
        self._sync_completed_at = sync_completed_at
        self._stale = stale

    def search(self, query: DirectoryQuery) -> DirectoryEvidence:
        sync_completed_at = self._current_sync_completed_at()
        if sync_completed_at is None:
            return DirectoryEvidence("not_ready", (), (), None, False)

        intent = self._safe_intent(query)
        people = self._eligible_people(onboarding_requested=intent == "onboarding_search")
        if intent == "person_lookup":
            matches = self._exact_person_matches(query.text, people)
            return self._evidence(matches, sync_completed_at=sync_completed_at)
        if intent == "coworker_lookup":
            targets = self._exact_person_matches(query.text, people)
            if not targets:
                return self._evidence((), sync_completed_at=sync_completed_at)
            coworkers = self.coworkers(targets[0], people=people)
            return self._evidence(
                coworkers.people,
                sync_completed_at=sync_completed_at,
                relationship_basis=coworkers.basis,
            )
        return self._evidence(
            self._directory_candidates(
                query.text,
                people,
                ignore_unstructured_terms=intent == "onboarding_search",
            ),
            sync_completed_at=sync_completed_at,
        )

    def coworkers(
        self, person: PersonRecord, *, people: Iterable[PersonRecord] | None = None
    ) -> CoworkerResult:
        """Return only a deterministic organizational-nearness interpretation."""
        candidates = tuple(people) if people is not None else self._eligible_people(False)
        candidates = tuple(
            candidate
            for candidate in candidates
            if candidate.personio_id != person.personio_id
            and candidate.employment_status == "ACTIVE"
        )
        if person.team:
            return CoworkerResult(
                "team",
                self._ordered(
                    candidate for candidate in candidates if candidate.team == person.team
                ),
            )
        if person.position and person.office:
            return CoworkerResult(
                "position_and_office",
                self._ordered(
                    candidate
                    for candidate in candidates
                    if candidate.position == person.position and candidate.office == person.office
                ),
            )
        if person.department and person.office:
            return CoworkerResult(
                "department_and_office",
                self._ordered(
                    candidate
                    for candidate in candidates
                    if candidate.department == person.department and candidate.office == person.office
                ),
            )
        return CoworkerResult(None, ())

    def _eligible_people(self, onboarding_requested: bool) -> tuple[PersonRecord, ...]:
        indexed_ids = self._index.indexed_personio_ids()
        records = self._index.people_by_personio_ids(indexed_ids)
        people = tuple(records.values())
        allowed_statuses = {"ONBOARDING"} if onboarding_requested else {"ACTIVE", "LEAVE"}
        return self._ordered(
            person
            for person in people
            if person.employment_status in allowed_statuses
        )

    def _safe_intent(self, query: DirectoryQuery) -> DirectoryIntent:
        classified = classify_directory_query(query.text)
        if query.intent == "onboarding_search" and classified != "onboarding_search":
            return "directory_search"
        return query.intent

    def _exact_person_matches(
        self, text: str, people: Iterable[PersonRecord]
    ) -> tuple[PersonRecord, ...]:
        normalized = _normalise_text(text)
        normalized_email_text = _normalise_email_text(text)
        matches = []
        for person in people:
            full_name = _normalise_text(person.display_name)
            email = _normalise_email(person.business_email)
            name_matches = bool(full_name) and f" {full_name} " in f" {normalized} "
            email_matches = bool(email) and email in normalized_email_text
            if name_matches or email_matches:
                matches.append(person)
        return self._ordered(matches)

    def _directory_candidates(
        self,
        text: str,
        people: Iterable[PersonRecord],
        *,
        ignore_unstructured_terms: bool = False,
    ) -> tuple[PersonRecord, ...]:
        people = tuple(people)
        filters = _explicit_field_filters(text, people)
        terms = () if ignore_unstructured_terms or filters else _search_terms(text)
        phone_digits = _digits(text)
        query_emails = _EMAIL.findall(text)
        normalized_emails = {_normalise_email(email) for email in query_emails}
        scored: list[tuple[float, PersonRecord]] = []
        for person in people:
            exact_email = _normalise_email(person.business_email)
            exact_phone = _digits(person.business_phone)
            candidate_text = _normalise_text(
                " ".join(
                    (
                        person.display_name,
                        person.position,
                        person.department,
                        person.team,
                        person.office,
                    )
                )
            )
            if normalized_emails and exact_email not in normalized_emails:
                continue
            if len(phone_digits) >= 5 and phone_digits not in exact_phone:
                continue
            if any(
                requested and _normalise_text(str(getattr(person, field))) not in requested
                for field, requested in filters.items()
            ):
                continue
            matched_terms = sum(term in candidate_text.split() for term in terms)
            if terms and matched_terms != len(terms):
                continue
            scored.append((float(matched_terms), person))
        return tuple(
            person
            for _, person in sorted(
                scored,
                key=lambda item: (
                    -item[0],
                    _normalise_text(item[1].display_name),
                    item[1].personio_id,
                ),
            )
        )

    def _evidence(
        self,
        people: Iterable[PersonRecord],
        *,
        sync_completed_at: str,
        relationship_basis: Literal[
            "team", "position_and_office", "department_and_office"
        ]
        | None = None,
    ) -> DirectoryEvidence:
        claims: list[dict[str, object]] = []
        sources: list[dict[str, str]] = []
        for number, person in enumerate(people, start=1):
            payload = public_payload(
                person,
                onboarding_requested=person.employment_status == "ONBOARDING",
            )
            if not payload:
                continue
            source_id = f"P{number}"
            claim = dict(payload)
            claim["source_id"] = source_id
            if relationship_basis is not None:
                claim["relationship_basis"] = relationship_basis
                claim["relationship_disclaimer"] = _COLLABORATION_DISCLAIMER
            claims.append(claim)
            sources.append({"id": source_id, "kind": "personio_directory"})
        return DirectoryEvidence(
            "ok" if claims else "not_found",
            tuple(claims),
            tuple(sources),
            sync_completed_at,
            self._current_stale(),
        )

    def _current_sync_completed_at(self) -> str | None:
        value = self._sync_completed_at
        return value() if callable(value) else value

    def _current_stale(self) -> bool:
        value = self._stale
        return value() if callable(value) else value

    @staticmethod
    def _ordered(people: Iterable[PersonRecord]) -> tuple[PersonRecord, ...]:
        return tuple(
            sorted(
                people,
                key=lambda person: (_normalise_text(person.display_name), person.personio_id),
            )
        )


def _normalise_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    without_diacritics = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return " ".join(re.sub(r"[^\w]+", " ", without_diacritics.casefold()).split())


def _normalise_email(value: str) -> str:
    return value.casefold().strip()


def _normalise_email_text(value: str) -> str:
    return " ".join(_normalise_email(match) for match in _EMAIL.findall(value))


def _digits(value: str) -> str:
    return "".join(character for character in value if character.isdigit())


def _search_terms(text: str) -> tuple[str, ...]:
    return tuple(
        term
        for term in _normalise_text(text).split()
        if term not in _STOP_WORDS and len(term) > 1
    )


def _explicit_field_filters(
    text: str, people: Iterable[PersonRecord]
) -> dict[str, frozenset[str]]:
    """Extract only field values stated in the question from indexed vocabulary.

    Matching a location in an arbitrary team label is not enough: a request for
    "in Hannover" must match the person's Office field.  The same convention
    applies to explicitly stated position, department and team labels.
    """
    normalized = f" {_normalise_text(text)} "
    filters: dict[str, frozenset[str]] = {}
    for field in ("position", "department", "team", "office"):
        requested = {
            normalized_value
            for person in people
            if (normalized_value := _normalise_text(str(getattr(person, field))))
            and _field_value_is_explicitly_requested(field, normalized, normalized_value)
        }
        if requested:
            filters[field] = frozenset(requested)
    if _explicit_office_request(normalized) and "office" not in filters:
        # An expressly named but unknown location must not degrade into a
        # role-only list. It is a bounded zero-result filter, never a fuzzy match.
        filters["office"] = frozenset({"__unmatched_office__"})
    _add_controlled_variants(filters, normalized, people)
    return filters


def _add_controlled_variants(
    filters: dict[str, frozenset[str]],
    query: str,
    people: Iterable[PersonRecord],
) -> None:
    """Add only a small, auditable set of role and business-field variants."""
    people = tuple(people)
    for role, variants in _ROLE_VARIANTS.items():
        if role == "serviceassistenz":
            requested = bool(re.search(r"\bserviceassistenz(?:en)?\b", query))
        else:
            requested = bool(re.search(r"\bverkaufer\b", query))
        if requested:
            _add_matching_field_values(filters, "position", people, variants)
    if re.search(r"\bseat\b", query):
        _add_matching_field_values(filters, "team", people, ("seat",))
    if re.search(r"\bneuwagen\b", query):
        _add_matching_field_values(filters, "department", people, ("neuwagen",))


def _add_matching_field_values(
    filters: dict[str, frozenset[str]],
    field: str,
    people: Iterable[PersonRecord],
    variants: Iterable[str],
) -> None:
    normalized_variants = frozenset(variants)
    matched = {
        value
        for person in people
        if (value := _normalise_text(str(getattr(person, field))))
        and normalized_variants.intersection(value.split())
    }
    if matched:
        filters[field] = frozenset(set(filters.get(field, ())) | matched)


def _is_controlled_role_description(query: str) -> bool:
    return bool(
        re.search(r"\bserviceassistenz(?:en)?\b", query)
        or (
            re.search(r"\bverkaufer\b", query)
            and re.search(r"\b(?:seat|neuwagen|automobil)\b", query)
        )
    )


def _explicit_office_request(query: str) -> bool:
    return bool(
        re.search(
            r"\b(?:in(?:\s+der|\s+dem)?|nach|am\s+standort)\s+[\w]+",
            query,
        )
    )


def _field_value_is_explicitly_requested(
    field: str, query: str, value: str
) -> bool:
    if field != "office":
        return f" {value} " in query
    return bool(
        re.search(
            rf"\b(?:in(?:\s+der|\s+dem)?|nach|am|(?:am\s+)?standort)\s+{re.escape(value)}\b",
            query,
        )
    )
