from __future__ import annotations

from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

import pytest

from app.index import QdrantDirectoryIndex, _person_from_payload
from app.models import PersonRecord


@dataclass
class Call:
    method: str
    path: str
    payload: object


class FakeQdrant:
    def __init__(self, responses: list[object] | None = None) -> None:
        self.calls: list[Call] = []
        self.responses = list(responses or [])

    def request(self, method: str, path: str, **kwargs: object) -> object:
        self.calls.append(Call(method, path, kwargs.get("json")))
        return self.responses.pop(0) if self.responses else None


@dataclass
class Response:
    status_code: int


def active_person(personio_id: str = "person-1") -> PersonRecord:
    return PersonRecord(
        personio_id=personio_id,
        first_name="Erika",
        last_name="Beispiel",
        display_name="Erika Beispiel",
        position="Serviceberaterin",
        department="Service",
        team="Service Hannover",
        office="Hannover",
        business_email="erika.beispiel@kahle.de",
        business_phone="+49 511 123456",
        employment_status="ACTIVE",
        source_updated_at="2026-08-24T10:15:00Z",
    )


def test_index_uses_isolated_collection_deterministic_id_and_safe_payload():
    transport = FakeQdrant([Response(200)])
    index = QdrantDirectoryIndex(transport, base_url="http://qdrant.test")

    index.upsert(active_person())

    assert index.collection_name == "vinci_personio_directory"
    call = transport.calls[0]
    assert call.method == "put"
    assert call.path == "http://qdrant.test/collections/vinci_personio_directory/points?wait=true"
    assert "vinci_knowledge" not in call.path
    point = call.payload["points"][0]
    assert point["id"] == str(uuid5(NAMESPACE_URL, "vinci_personio_directory:person-1"))
    assert point["payload"] == {
        "personio_id": "person-1",
        "first_name": "Erika",
        "last_name": "Beispiel",
        "display_name": "Erika Beispiel",
        "position": "Serviceberaterin",
        "department": "Service",
        "team": "Service Hannover",
        "office": "Hannover",
        "business_email": "erika.beispiel@kahle.de",
        "business_phone": "+49 511 123456",
            "employment_status": "ACTIVE",
            "source_updated_at": "2026-08-24T10:15:00Z",
            "supervisor_personio_id": "",
        "exact_display_name": "erika beispiel",
        "exact_email": "erika.beispiel@kahle.de",
        "exact_phone": "49511123456",
        "search_text": "Erika Beispiel Serviceberaterin Service Service Hannover Hannover",
    }
    assert all("private" not in key and "salary" not in key for key in point["payload"])
    assert "employment_type" not in point["payload"]


def test_qdrant_read_accepts_empty_optional_directory_fields():
    person = active_person()
    payload = QdrantDirectoryIndex._payload(person) | {
        "position": "",
        "department": "",
        "team": "",
        "office": "",
        "business_email": "",
        "business_phone": "",
    }

    assert _person_from_payload(payload).display_name == person.display_name


def test_index_physically_deletes_points_by_personio_id():
    transport = FakeQdrant([Response(200)])
    index = QdrantDirectoryIndex(transport, base_url="http://qdrant.test")

    index.delete_personio_ids({"person-2", "person-1"})

    call = transport.calls[0]
    assert call.method == "post"
    assert call.path == "http://qdrant.test/collections/vinci_personio_directory/points/delete?wait=true"
    assert call.payload == {"filter": {"must": [{"key": "personio_id", "match": {"any": ["person-1", "person-2"]}}]}}


def test_existing_directory_collection_is_not_replaced_during_initialization():
    transport = FakeQdrant([Response(200)])
    index = QdrantDirectoryIndex(transport, base_url="http://qdrant.test")

    index.ensure_collection()

    assert [(call.method, call.path) for call in transport.calls] == [
        ("get", "http://qdrant.test/collections/vinci_personio_directory")
    ]


@pytest.mark.parametrize("status_code", [400, 500])
def test_index_rejects_unsuccessful_upsert_responses(status_code):
    index = QdrantDirectoryIndex(FakeQdrant([Response(status_code)]), base_url="http://qdrant.test")

    with pytest.raises(RuntimeError, match="qdrant_mutation_failed") as error:
        index.upsert(active_person())

    assert "Erika" not in str(error.value)


@pytest.mark.parametrize("status_code", [400, 500])
def test_index_rejects_unsuccessful_delete_responses(status_code):
    index = QdrantDirectoryIndex(FakeQdrant([Response(status_code)]), base_url="http://qdrant.test")

    with pytest.raises(RuntimeError, match="qdrant_mutation_failed"):
        index.delete_personio_ids({"person-1"})
