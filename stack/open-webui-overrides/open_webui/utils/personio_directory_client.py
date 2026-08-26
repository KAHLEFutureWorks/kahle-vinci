"""Small internal-only client for the synchronized Personio directory."""

from __future__ import annotations

import asyncio
import os
import re
from typing import Any, Callable


_ALLOWED_INTENTS = frozenset(
    {"person_lookup", "directory_search", "coworker_lookup", "onboarding_search"}
)
_ALLOWED_STATUSES = frozenset({"ok", "not_found", "not_ready"})
_SOURCE_ID = re.compile(r"^P[1-9][0-9]*$")
_SYNC_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)
_DIRECTORY_CLAIM_FIELDS = frozenset(
    {
        "personio_id",
        "first_name",
        "last_name",
        "display_name",
        "position",
        "department",
        "team",
        "office",
        "business_email",
        "business_phone",
        "employment_status",
        "employment_type",
        "source_updated_at",
        "source_id",
        "relationship_basis",
        "relationship_disclaimer",
    }
)
_ONBOARDING_CLAIM_FIELDS = frozenset(
    {"display_name", "position", "department", "team", "office", "source_id"}
)


def _unavailable() -> dict[str, Any]:
    return {
        "status": "directory_unavailable",
        "claims": [],
        "sources": [],
        "sync_completed_at": None,
        "stale": False,
    }


class PersonioDirectoryClient:
    """Call the private directory API without exposing request data in logs."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float = 5.0,
        session_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._base_url = str(
            base_url or os.getenv("PERSONIO_DIRECTORY_URL") or "http://personio-directory:8094"
        ).rstrip("/")
        self._api_key = str(
            api_key or os.getenv("PERSONIO_DIRECTORY_API_KEY") or ""
        )
        self._timeout_seconds = min(15.0, max(0.5, float(timeout_seconds)))
        self._session_factory = session_factory

    async def search(
        self,
        query: str,
        intent: str,
        user_id: str,
        user_role: str,
    ) -> dict[str, Any]:
        if (
            not self._api_key
            or not str(query or "").strip()
            or intent not in _ALLOWED_INTENTS
            or not str(user_id or "").strip()
            or user_role not in {"user", "admin"}
        ):
            return _unavailable()

        payload = {
            "query": str(query).strip(),
            "intent": intent,
            "user_id": str(user_id).strip(),
            "user_role": user_role,
        }
        try:
            session_factory = self._session_factory
            session_options: dict[str, Any] = {}
            if session_factory is None:
                import aiohttp

                session_factory = aiohttp.ClientSession
                session_options["timeout"] = aiohttp.ClientTimeout(
                    total=self._timeout_seconds
                )
            async with session_factory(**session_options) as session:
                async with session.post(
                    f"{self._base_url}/internal/search",
                    json=payload,
                    headers={"X-API-Key": self._api_key},
                ) as response:
                    if response.status != 200:
                        return _unavailable()
                    data = await response.json()
            return self._validated(data, intent=intent)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Deliberately do not log the exception: HTTP libraries can include
            # request payloads and headers in their error strings.
            return _unavailable()

    @staticmethod
    def _validated(data: Any, *, intent: str) -> dict[str, Any]:
        if not isinstance(data, dict):
            return _unavailable()
        status = data.get("status")
        claims = data.get("claims")
        sources = data.get("sources")
        sync_completed_at = data.get("sync_completed_at")
        stale = data.get("stale")
        if (
            status not in _ALLOWED_STATUSES
            or not isinstance(claims, list)
            or not all(isinstance(claim, dict) for claim in claims)
            or not isinstance(sources, list)
            or not all(isinstance(source, dict) for source in sources)
            or not (
                sync_completed_at is None
                or (
                    isinstance(sync_completed_at, str)
                    and _SYNC_TIMESTAMP.fullmatch(sync_completed_at)
                )
            )
            or not isinstance(stale, bool)
        ):
            return _unavailable()
        if status in {"ok", "not_found"} and sync_completed_at is None:
            return _unavailable()

        source_ids = set()
        controlled_sources = []
        for source in sources:
            source_id = source.get("id")
            if (
                not isinstance(source_id, str)
                or not _SOURCE_ID.fullmatch(source_id)
                or source.get("kind") != "personio_directory"
            ):
                return _unavailable()
            source_ids.add(source_id)
            controlled_sources.append(
                {"id": source_id, "kind": "personio_directory"}
            )

        controlled_claims = []
        allowed_claim_fields = (
            _ONBOARDING_CLAIM_FIELDS
            if intent == "onboarding_search"
            else _DIRECTORY_CLAIM_FIELDS
        )
        for claim in claims:
            source_id = claim.get("source_id")
            if (
                not isinstance(source_id, str)
                or source_id not in source_ids
                or not set(claim).issubset(allowed_claim_fields)
                or not all(isinstance(value, str) for value in claim.values())
            ):
                return _unavailable()
            controlled_claims.append(dict(claim))

        if status == "ok" and not controlled_claims:
            return _unavailable()
        if status != "ok" and (controlled_claims or controlled_sources):
            return _unavailable()
        return {
            "status": status,
            "claims": controlled_claims,
            "sources": controlled_sources,
            "sync_completed_at": sync_completed_at,
            "stale": stale,
        }
