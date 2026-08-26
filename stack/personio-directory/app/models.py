from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class PersonRecord:
    personio_id: str
    first_name: str
    last_name: str
    display_name: str
    position: str
    department: str
    team: str
    office: str
    business_email: str
    business_phone: str
    employment_status: Literal["ACTIVE", "LEAVE", "ONBOARDING"]
    source_updated_at: str


@dataclass(frozen=True)
class DirectoryQuery:
    text: str
    intent: Literal[
        "person_lookup", "directory_search", "coworker_lookup", "onboarding_search", "supervisor_lookup"
    ]
    user_id: str
    user_role: str


@dataclass(frozen=True)
class DirectoryHit:
    personio_id: str
    score: float
    fields: dict[str, object]
