from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import create_app
from app.search import DirectoryEvidence


class FakeSearch:
    def search(self, query):
        if query.intent == "onboarding_search":
            claims = (
                {
                    "display_name": "Erika Beispiel",
                    "position": "Serviceberaterin",
                    "department": "Service",
                    "team": "Service Hannover",
                    "office": "Hannover",
                    "source_id": "P1",
                },
            )
        else:
            claims = ({"display_name": "Erika Beispiel", "business_email": "erika@kahle.de", "source_id": "P1"},)
        return DirectoryEvidence("ok", claims, ({"id": "P1", "kind": "personio_directory"},), "2026-08-24T10:15:00Z", False)


class UnsafeSearch:
    def search(self, query):
        return DirectoryEvidence(
            "ok",
            (
                {
                    "display_name": "Erika Beispiel",
                    "position": "Serviceberaterin",
                    "department": "Service",
                    "team": "Service Hannover",
                    "office": "Hannover",
                    "business_email": "must-not-escape@kahle.de",
                    "business_phone": "+49 511 999999",
                    "personio_id": "personio-private-id",
                    "employment_status": "ONBOARDING",
                    "start_date": "2026-09-01",
                    "contract_number": "private-contract-data",
                    "source_id": "P1",
                },
            ),
            ({"id": "P1", "kind": "personio_directory", "unsafe": "must-not-escape@kahle.de"},),
            "2026-08-24T10:15:00Z",
            False,
        )


def client() -> TestClient:
    return TestClient(create_app(search=FakeSearch(), internal_api_key="test-key", start_background=False))


def request(*, role: str, intent: str = "person_lookup") -> dict[str, str]:
    return {
        "query": "Wo arbeitet Erika Beispiel?",
        "intent": intent,
        "user_id": "local-user-1",
        "user_role": role,
    }


def test_search_accepts_user_and_admin_but_rejects_pending() -> None:
    with client() as api:
        headers = {"X-API-Key": "test-key"}
        assert api.post("/internal/search", json=request(role="user"), headers=headers).status_code == 200
        assert api.post("/internal/search", json=request(role="admin"), headers=headers).status_code == 200
        assert api.post("/internal/search", json=request(role="pending"), headers=headers).status_code == 403


def test_search_rejects_missing_or_wrong_internal_key() -> None:
    with client() as api:
        assert api.post("/internal/search", json=request(role="user")).status_code == 403
        assert api.post("/internal/search", json=request(role="user"), headers={"X-API-Key": "wrong"}).status_code == 403


def test_onboarding_api_never_serializes_contact_fields() -> None:
    with client() as api:
        response = api.post(
            "/internal/search",
            json=request(role="user", intent="onboarding_search"),
            headers={"X-API-Key": "test-key"},
        )
    assert response.status_code == 200
    rendered = json.dumps(response.json())
    assert "business_email" not in rendered
    assert "business_phone" not in rendered
    assert "personio_id" not in rendered
    assert "employment_status" not in rendered


def test_onboarding_api_whitelists_unsafe_search_claims() -> None:
    with TestClient(create_app(search=UnsafeSearch(), internal_api_key="test-key", start_background=False)) as api:
        response = api.post(
            "/internal/search",
            json=request(role="user", intent="onboarding_search"),
            headers={"X-API-Key": "test-key"},
        )
    assert response.status_code == 200
    rendered = json.dumps(response.json())
    for unsafe in (
        "business_email", "business_phone", "personio_id", "employment_status",
        "start_date", "contract_number", "must-not-escape@kahle.de",
        "private-contract-data", "2026-09-01",
    ):
        assert unsafe not in rendered
    assert response.json()["claims"] == [{
        "display_name": "Erika Beispiel", "position": "Serviceberaterin",
        "department": "Service", "team": "Service Hannover",
        "office": "Hannover", "source_id": "P1",
    }]
    assert response.json()["sources"] == [{"id": "P1", "kind": "personio_directory"}]


def test_search_validates_bounded_request_fields() -> None:
    with client() as api:
        response = api.post(
            "/internal/search",
            json={**request(role="user"), "query": "x" * 1001},
            headers={"X-API-Key": "test-key"},
        )
    assert response.status_code == 422


def test_health_requires_a_readable_recent_successful_sync() -> None:
    recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    healthy_runtime = SimpleNamespace(
        search=FakeSearch(),
        state=SimpleNamespace(last_successful_at=lambda: recent, indexed_people=lambda: {}),
    )
    stale_runtime = SimpleNamespace(
        search=FakeSearch(),
        state=SimpleNamespace(
            last_successful_at=lambda: (datetime.now(timezone.utc) - timedelta(hours=49)).isoformat().replace("+00:00", "Z"),
            indexed_people=lambda: {},
        ),
    )
    with TestClient(create_app(runtime=healthy_runtime, internal_api_key="test-key", start_background=False)) as api:
        assert api.get("/health").status_code == 200
    with TestClient(create_app(runtime=stale_runtime, internal_api_key="test-key", start_background=False)) as api:
        assert api.get("/health").status_code == 503


def test_failed_bootstrap_starts_retry_loop_until_sync_succeeds(monkeypatch) -> None:
    from app import main

    retry_completed = threading.Event()
    successful_sync = {"at": None}

    class FakeIndex:
        def __init__(self) -> None:
            self.ensure_calls = 0

        def ensure_collection(self) -> None:
            self.ensure_calls += 1
            if self.ensure_calls == 1:
                raise RuntimeError("collection_temporarily_unavailable")

        def indexed_personio_ids(self) -> set[str]:
            return set()

    class FakeSync:
        def full_sync_due(self, now: str) -> bool:
            return True

        def run_full(self) -> None:
            successful_sync["at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            retry_completed.set()

        def run_delta(self) -> None:
            raise AssertionError("a new service must bootstrap with a full sync")

    fake_index = FakeIndex()
    fake_runtime = SimpleNamespace(
        search=FakeSearch(),
        state=SimpleNamespace(last_successful_at=lambda: successful_sync["at"], indexed_people=lambda: {}),
        index=fake_index,
        sync=FakeSync(),
    )
    monkeypatch.setattr(main, "_build_runtime", lambda: fake_runtime)
    with TestClient(create_app(internal_api_key="test-key", sync_interval_seconds=0.01)) as api:
        assert retry_completed.wait(timeout=1)
        assert api.get("/health").status_code == 200
    assert fake_index.ensure_calls >= 2
    # The lifecycle retried collection preparation and a complete full sync
    # without restarting the process; keep the test bounded for slower CI.
    assert retry_completed.is_set()
