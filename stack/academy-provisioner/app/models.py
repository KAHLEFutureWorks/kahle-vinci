from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EligibleUser:
    openwebui_id: str
    email: str
    first_name: str
    last_name: str
    role: str


@dataclass(frozen=True)
class InvalidUser:
    openwebui_id: str
    error_code: str
