from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ConfidentialitySuggestion:
    level: str
    reason: str
    signals: tuple[str, ...]


class ContentConfidentialityClassifier:
    """Fail-safe local pre-classification before optional model processing."""

    CONFIDENTIAL = {
        "credentials": re.compile(r"\b(passwort|kennwort|api[- ]?key|client[- ]?secret|zugangscode)\b", re.I),
        "bank_data": re.compile(r"\b(?:DE\d{20}|iban|bic|kontonummer)\b", re.I),
        "health_data": re.compile(r"\b(gesundheitsdaten|diagnose|arbeitsunfähig|krankmeldung)\b", re.I),
        "customer_identity": re.compile(r"\b(kundennummer|fahrgestellnummer|vin)\b.{0,50}\b[A-Z0-9-]{6,}\b", re.I),
    }
    RESTRICTED = {
        "email": re.compile(r"\b[^\s@]+@[^\s@]+\.[A-Za-z]{2,}\b"),
        "phone": re.compile(r"\b(?:\+49|0)\s?\d{2,5}(?:[ /-]?\d){5,}\b"),
        "personnel": re.compile(r"\b(personalakte|gehalt|abmahnung|mitarbeitergespräch)\b", re.I),
        "business_sensitive": re.compile(r"\b(marge|einkaufspreis|rabattgrenze|vertraulich|nur für den bereich)\b", re.I),
    }

    def classify(self, markdown: str) -> ConfidentialitySuggestion:
        confidential = tuple(name for name, pattern in self.CONFIDENTIAL.items() if pattern.search(markdown or ""))
        if confidential:
            return ConfidentialitySuggestion(
                "confidential", "Sensible Zugangs-, Bank-, Gesundheits- oder Kundendaten erkannt.", confidential,
            )
        restricted = tuple(name for name, pattern in self.RESTRICTED.items() if pattern.search(markdown or ""))
        if restricted:
            return ConfidentialitySuggestion(
                "restricted", "Personenbezogene oder bereichssensible Angaben erkannt.", restricted,
            )
        return ConfidentialitySuggestion(
            "internal", "Keine Merkmale für eine höhere Vertraulichkeitsstufe erkannt.", (),
        )


def stricter_level(requested: str, suggested: str) -> str:
    ranks = {"internal": 0, "restricted": 1, "confidential": 2}
    if requested not in ranks or suggested not in ranks:
        raise ValueError("invalid_confidentiality")
    return max((requested, suggested), key=ranks.__getitem__)
