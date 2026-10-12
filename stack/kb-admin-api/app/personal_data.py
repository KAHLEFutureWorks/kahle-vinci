"""Detect personal customer data in an uploaded document by category.

Only categories and counts leave this module, never the matched values.
One strong signal or two different weak signals require an explicit
confirmation by the uploader (user decision 2026-10-12).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_PATTERNS = {
    "external_email": re.compile(r"\b[\w.+-]+@(?![\w.-]*kahle\.)[\w-]+(?:\.[\w-]+)+\b", re.I),
    "mobile_phone": re.compile(r"(?<!\d)(?:\+49[\s/-]?|0)1[5-7]\d[\s/-]?\d{3,4}[\s/-]?\d{3,5}(?!\d)"),
    "private_phone": re.compile(r"(?i)\b(?:telefon|tel\.?)\s*privat\b[^\n]{0,20}\d{4,}"),
    "postal_address": re.compile(
        r"(?i)\b[\wäöüß.-]+(?:stra(?:ss|ß)e|str\.|weg|allee|platz|ring|damm|gasse)\s+\d+\s*[a-z]?\b"
        r"[,\s]+\d{5}\s+[A-ZÄÖÜ][a-zäöüß]+"
    ),
    "vin": re.compile(
        r"\b(?=[A-HJ-NPR-Z0-9]{17}\b)(?=[A-HJ-NPR-Z0-9]*\d)(?=[A-HJ-NPR-Z0-9]*[A-HJ-NPR-Z])"
        r"[A-HJ-NPR-Z0-9]{17}\b"
    ),
    "licence_plate": re.compile(r"\b[A-ZÄÖÜ]{1,3}[\s-][A-Z]{1,2}[\s-]?\d{1,4}[EH]?\b"),
    "iban": re.compile(r"\bDE\d{2}(?:\s?\d{4}){4}\s?\d{2}\b"),
    "birth_date": re.compile(r"(?i)\bgeb(?:\.|oren|urtsdatum)\s*(?:am\s*)?:?\s*\d{1,2}\.\d{1,2}\.\d{2,4}"),
}
STRONG_CATEGORIES = frozenset({"vin", "licence_plate", "mobile_phone", "private_phone", "iban", "birth_date"})


@dataclass(frozen=True)
class PersonalDataFindings:
    categories: dict[str, int]
    requires_confirmation: bool


def detect(markdown: str) -> PersonalDataFindings:
    text = str(markdown or "")
    categories = {
        name: len(pattern.findall(text))
        for name, pattern in _PATTERNS.items()
        if pattern.search(text)
    }
    requires = bool(STRONG_CATEGORIES & set(categories)) or len(categories) >= 2
    return PersonalDataFindings(categories=categories, requires_confirmation=requires)
