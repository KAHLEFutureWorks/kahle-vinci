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
    # Interne Kontaktdaten stufen nicht hoch. Nahezu jede KAHLE-Richtlinie endet
    # mit einem Verantwortlichkeitsblock aus @kahle.de-Adressen und einer
    # Servicenummer. Als personenbezogenes Merkmal gewertet, landete dadurch
    # praktisch jedes Dokument auf "bereichsbeschraenkt" und ging zur
    # Adminpruefung, womit die Einstufung ihre Aussagekraft verlor (PRD 15.2:
    # Kalibrierung anhand echter KAHLE-Dokumente).
    INTERNAL_EMAIL_DOMAINS = ("kahle.de",)
    # 0800/0180/0900 sind Service- und keine Personenrufnummern.
    SERVICE_PHONE = re.compile(r"\b0(?:800|180\d?|900)[ /-]?\d[\d /-]*\b")

    RESTRICTED = {
        "phone": re.compile(r"\b(?:\+49|0)\s?\d{2,5}(?:[ /-]?\d){5,}\b"),
        "personnel": re.compile(r"\b(personalakte|gehalt|abmahnung|mitarbeitergespräch)\b", re.I),
        "business_sensitive": re.compile(r"\b(marge|einkaufspreis|rabattgrenze|nur für den bereich)\b", re.I),
        # "vertraulich" erklaert in Richtlinien meist einen Begriff. Nur eine
        # ausdrueckliche Kennzeichnung stuft das Dokument selbst ein.
        "confidentiality_label": re.compile(
            r"\b(?:klassifizierung|einstufung|vertraulichkeitsstufe)\s*[:=-]\s*vertraulich\b", re.I,
        ),
    }
    EXTERNAL_EMAIL = re.compile(r"\b[^\s@]+@([^\s@]+\.[A-Za-z]{2,})\b")

    def _external_emails(self, markdown: str) -> bool:
        for domain in self.EXTERNAL_EMAIL.findall(markdown or ""):
            clean = domain.casefold().rstrip(".")
            if not any(
                clean == internal or clean.endswith(f".{internal}")
                for internal in self.INTERNAL_EMAIL_DOMAINS
            ):
                return True
        return False

    def _personal_phone(self, markdown: str) -> bool:
        without_service = self.SERVICE_PHONE.sub(" ", markdown or "")
        return bool(self.RESTRICTED["phone"].search(without_service))

    def classify(self, markdown: str) -> ConfidentialitySuggestion:
        confidential = tuple(name for name, pattern in self.CONFIDENTIAL.items() if pattern.search(markdown or ""))
        if confidential:
            return ConfidentialitySuggestion(
                "confidential", "Sensible Zugangs-, Bank-, Gesundheits- oder Kundendaten erkannt.", confidential,
            )
        restricted = tuple(
            name for name, pattern in self.RESTRICTED.items()
            if (self._personal_phone(markdown) if name == "phone" else pattern.search(markdown or ""))
        )
        if self._external_emails(markdown):
            restricted += ("email",)
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
