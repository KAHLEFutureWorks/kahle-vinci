from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from .models import PersonRecord


class QdrantDirectoryIndex:
    """Narrow Qdrant boundary for the dedicated employee directory collection."""

    collection_name = "vinci_personio_directory"

    def __init__(
        self,
        transport: Any,
        *,
        base_url: str = "http://qdrant:6333",
        collection_name: str = collection_name,
    ) -> None:
        if collection_name != self.collection_name:
            raise ValueError("directory_collection_invalid")
        self._transport = transport
        self._base_url = base_url.rstrip("/")

    def ensure_collection(self, vector_size: int = 1) -> None:
        existing = self._request("get", f"/collections/{self.collection_name}")
        status = int(getattr(existing, "status_code", 0))
        if 200 <= status < 300:
            return
        if status != 404:
            raise RuntimeError("qdrant_collection_check_failed")
        created = self._request(
            "put",
            f"/collections/{self.collection_name}",
            json={"vectors": {"size": vector_size, "distance": "Cosine"}},
        )
        if not 200 <= int(getattr(created, "status_code", 0)) < 300:
            raise RuntimeError("qdrant_collection_create_failed")

    def upsert(self, person: PersonRecord) -> None:
        self.upsert_many((person,))

    def upsert_many(self, people: Iterable[PersonRecord]) -> None:
        points = [self._point(person) for person in people]
        if points:
            response = self._request(
                "put",
                f"/collections/{self.collection_name}/points?wait=true",
                json={"points": points},
            )
            self._require_mutation_success(response)

    def delete_personio_ids(self, personio_ids: set[str]) -> None:
        if not personio_ids:
            return
        response = self._request(
            "post",
            f"/collections/{self.collection_name}/points/delete?wait=true",
            json={"filter": {"must": [{"key": "personio_id", "match": {"any": sorted(personio_ids)}}]}},
        )
        self._require_mutation_success(response)

    def indexed_personio_ids(self) -> set[str]:
        """Return only stable Personio IDs for full-reconciliation deletes."""
        ids: set[str] = set()
        offset: object | None = None
        while True:
            payload: dict[str, object] = {
                "limit": 256,
                "with_payload": ["personio_id"],
                "with_vector": False,
            }
            if offset is not None:
                payload["offset"] = offset
            response = self._request(
                "post", f"/collections/{self.collection_name}/points/scroll", json=payload
            )
            self._require_read_success(response)
            try:
                result = response.json()["result"]
                points = result["points"]
            except (AttributeError, KeyError, TypeError):
                raise RuntimeError("qdrant_response_invalid") from None
            if not isinstance(points, list):
                raise RuntimeError("qdrant_response_invalid")
            for point in points:
                if not isinstance(point, Mapping):
                    raise RuntimeError("qdrant_response_invalid")
                payload_value = point.get("payload")
                if not isinstance(payload_value, Mapping):
                    raise RuntimeError("qdrant_response_invalid")
                personio_id = payload_value.get("personio_id")
                if not isinstance(personio_id, str) or not personio_id:
                    raise RuntimeError("qdrant_response_invalid")
                ids.add(personio_id)
            offset = result.get("next_page_offset") if isinstance(result, Mapping) else None
            if offset is None:
                return ids

    def people_by_personio_ids(self, personio_ids: set[str]) -> dict[str, PersonRecord]:
        """Fetch only pre-existing, safe directory records for bounded rollback."""
        if not personio_ids:
            return {}
        response = self._request(
            "post",
            f"/collections/{self.collection_name}/points/scroll",
            json={
                "limit": len(personio_ids),
                "filter": {"must": [{"key": "personio_id", "match": {"any": sorted(personio_ids)}}]},
                "with_payload": True,
                "with_vector": False,
            },
        )
        self._require_read_success(response)
        try:
            points = response.json()["result"]["points"]
        except (AttributeError, KeyError, TypeError):
            raise RuntimeError("qdrant_response_invalid") from None
        if not isinstance(points, list):
            raise RuntimeError("qdrant_response_invalid")
        people: dict[str, PersonRecord] = {}
        for point in points:
            if not isinstance(point, Mapping) or not isinstance(point.get("payload"), Mapping):
                raise RuntimeError("qdrant_response_invalid")
            person = _person_from_payload(point["payload"])
            people[person.personio_id] = person
        return people

    def _request(self, method: str, path: str, **kwargs: object) -> object:
        return self._transport.request(method, f"{self._base_url}{path}", **kwargs)

    @staticmethod
    def _require_mutation_success(response: object) -> None:
        if not 200 <= int(getattr(response, "status_code", 0)) < 300:
            raise RuntimeError("qdrant_mutation_failed")

    @staticmethod
    def _require_read_success(response: object) -> None:
        if not 200 <= int(getattr(response, "status_code", 0)) < 300:
            raise RuntimeError("qdrant_read_failed")

    def _point(self, person: PersonRecord) -> dict[str, object]:
        return {
            "id": str(uuid5(NAMESPACE_URL, f"{self.collection_name}:{person.personio_id}")),
            "vector": [0.0],
            "payload": self._payload(person),
        }

    @staticmethod
    def _payload(person: PersonRecord) -> dict[str, object]:
        return {
            "personio_id": person.personio_id,
            "first_name": person.first_name,
            "last_name": person.last_name,
            "display_name": person.display_name,
            "position": person.position,
            "department": person.department,
            "team": person.team,
            "office": person.office,
            "business_email": person.business_email,
            "business_phone": person.business_phone,
            "employment_status": person.employment_status,
            "source_updated_at": person.source_updated_at,
            "exact_display_name": _normalise_text(person.display_name),
            "exact_email": person.business_email.casefold(),
            "exact_phone": "".join(char for char in person.business_phone if char.isdigit()),
            "search_text": " ".join(
                value for value in (
                    person.display_name, person.position, person.department, person.team, person.office
                ) if value
            ),
        }


def _normalise_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _person_from_payload(payload: Mapping[str, object]) -> PersonRecord:
    fields = PersonRecord.__dataclass_fields__
    values = {field: payload.get(field) for field in fields}
    optional = {"position", "department", "team", "office", "business_email", "business_phone"}
    if any(not isinstance(value, str) for value in values.values()) or any(
        not values[field] for field in fields if field not in optional
    ):
        raise RuntimeError("qdrant_response_invalid")
    if values["employment_status"] not in {"ACTIVE", "LEAVE", "ONBOARDING"}:
        raise RuntimeError("qdrant_response_invalid")
    return PersonRecord(**values)  # type: ignore[arg-type]
