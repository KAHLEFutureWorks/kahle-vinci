import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


MAPPING = {
    "personio_id": "id",
    "display_name": "preferred_name",
    "position": "position",
    "department": "department",
    "team": "team",
    "office": "office",
    "business_email": "business_email",
    "business_phone": "business_phone",
    "employment_status": "employment_status",
    "source_updated_at": "updated_at",
}


def raw_person(status: str, employment_type: str) -> dict[str, str]:
    return {
        "id": "person-1",
        "preferred_name": "Erika Beispiel",
        "first_name": "Erika",
        "last_name": "Beispiel",
        "display_name": "Erika Beispiel",
        "position": "Serviceberaterin",
        "department": "Service",
        "team": "Service Hannover",
        "office": "Hannover",
        "business_email": "erika.beispiel@kahle.de",
        "business_phone": "+49 511 123456",
        "employment_status": status,
        "employment_type": employment_type,
        "updated_at": "2026-08-24T10:15:00Z",
    }
