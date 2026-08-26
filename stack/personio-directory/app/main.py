"""Internal, privacy-preserving Personio directory API.

The module deliberately exposes no Personio API surface.  It accepts only the
already authenticated OpenWebUI user context and returns evidence-safe records.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

import requests
from fastapi import FastAPI, Header, HTTPException, Response
from pydantic import BaseModel, Field

from .config import PersonioConfig
from .index import QdrantDirectoryIndex
from .models import DirectoryQuery
from .personio import PersonioClient
from .search import DirectoryEvidence, DirectorySearch
from .state import SQLiteSyncState
from .sync import DirectorySync


LOGGER = logging.getLogger(__name__)
_ALLOWED_ROLES = frozenset({"user", "admin"})
_MAX_SYNC_AGE = timedelta(hours=48)
_ONBOARDING_FIELDS = ("display_name", "position", "department", "team", "office")
_SOURCE_ID = re.compile(r"^P[1-9][0-9]*$")


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    intent: Literal[
        "person_lookup", "directory_search", "coworker_lookup", "onboarding_search", "supervisor_lookup"
    ]
    user_id: str = Field(min_length=1, max_length=256)
    user_role: str = Field(min_length=1, max_length=32)


class SearchResponse(BaseModel):
    status: Literal["ok", "not_found", "not_ready"]
    claims: list[dict[str, object]]
    sources: list[dict[str, str]]
    sync_completed_at: str | None
    stale: bool


@dataclass
class DirectoryRuntime:
    search: DirectorySearch
    sync: DirectorySync
    state: SQLiteSyncState
    index: QdrantDirectoryIndex


def create_app(
    *,
    search: DirectorySearch | object | None = None,
    runtime: DirectoryRuntime | object | None = None,
    internal_api_key: str | None = None,
    start_background: bool = True,
    sync_interval_seconds: float | None = None,
) -> FastAPI:
    """Create a testable app; production dependencies are built only at startup."""

    configured_key = internal_api_key

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.runtime = runtime
        app.state.search = search or getattr(runtime, "search", None)
        app.state.startup_error = None
        app.state.sync_task = None
        if runtime is None and search is None and start_background:
            try:
                built_runtime = await asyncio.to_thread(_build_runtime)
                app.state.runtime = built_runtime
                app.state.search = built_runtime.search
                try:
                    await asyncio.to_thread(_sync_startup, built_runtime)
                except Exception as error:
                    # A Personio/Qdrant outage at boot must not disable the
                    # service's retry lifecycle. Health stays red until the
                    # first successful sync has committed state.
                    LOGGER.error("personio_directory_bootstrap_sync_failed code=%s", type(error).__name__)
                    app.state.sync_task = asyncio.create_task(
                        _bootstrap_retry_loop(
                            built_runtime, interval_seconds=sync_interval_seconds
                        )
                    )
                else:
                    app.state.sync_task = asyncio.create_task(
                        _sync_loop(built_runtime, interval_seconds=sync_interval_seconds)
                    )
            except Exception as error:
                # Never render raw API errors, names, response bodies or credentials.
                app.state.startup_error = "personio_directory_unavailable"
                LOGGER.error("personio_directory_startup_failed code=%s", type(error).__name__)
        try:
            yield
        finally:
            task = app.state.sync_task
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    app = FastAPI(title="KAHLE Vinci Personio Directory", docs_url=None, redoc_url=None, lifespan=lifespan)

    def require_internal_key(x_api_key: str | None) -> None:
        expected = configured_key or os.getenv("PERSONIO_DIRECTORY_INTERNAL_API_KEY", "")
        if not expected or not x_api_key or not hmac.compare_digest(x_api_key, expected):
            raise HTTPException(status_code=403, detail="forbidden")

    @app.get("/health")
    def health() -> Response:
        runtime = app.state.runtime
        if runtime is None:
            # An injected search is used only in isolated API tests.
            if app.state.search is not None and app.state.startup_error is None:
                return Response(status_code=200)
            return Response(status_code=503)
        try:
            completed_at = runtime.state.last_successful_at()
            runtime.state.indexed_people()  # checks the durable state database is readable
            if completed_at is None or _sync_age(completed_at) > _MAX_SYNC_AGE:
                return Response(status_code=503)
        except Exception:
            return Response(status_code=503)
        return Response(status_code=200)

    @app.post("/internal/search", response_model=SearchResponse)
    def directory_search(payload: SearchRequest, x_api_key: str | None = Header(default=None)) -> SearchResponse:
        require_internal_key(x_api_key)
        if payload.user_role not in _ALLOWED_ROLES:
            raise HTTPException(status_code=403, detail="forbidden")
        active_search = app.state.search
        if active_search is None:
            raise HTTPException(status_code=503, detail="directory_unavailable")
        evidence: DirectoryEvidence = active_search.search(
            DirectoryQuery(
                text=payload.query,
                intent=payload.intent,
                user_id=payload.user_id,
                user_role=payload.user_role,
            )
        )
        return _response_from_evidence(evidence, onboarding=payload.intent == "onboarding_search")

    return app


def _build_runtime() -> DirectoryRuntime:
    config = PersonioConfig.from_env()
    state = SQLiteSyncState(os.getenv("PERSONIO_DIRECTORY_STATE_DB_PATH", "/state/personio-directory.sqlite3"))
    index = QdrantDirectoryIndex(
        requests.Session(),
        base_url=os.getenv("PERSONIO_DIRECTORY_QDRANT_URL", "http://qdrant:6333"),
    )
    client = PersonioClient(config, requests.Session())
    sync = DirectorySync(client, index, state)
    search = DirectorySearch(
        index,
        sync_completed_at=state.last_successful_at,
        stale=lambda: _is_stale(state.last_successful_at()),
    )
    return DirectoryRuntime(search=search, sync=sync, state=state, index=index)


def _sync_startup(runtime: DirectoryRuntime) -> None:
    runtime.index.ensure_collection()
    completed_at = runtime.state.last_successful_at()
    expected_ids = set(runtime.state.indexed_people())
    try:
        index_valid = completed_at is not None and runtime.index.indexed_personio_ids() == expected_ids
    except Exception:
        index_valid = False
    if not index_valid or runtime.sync.full_sync_due(_utc_now()):
        runtime.sync.run_full()
    else:
        runtime.sync.run_delta()


async def _sync_loop(
    runtime: DirectoryRuntime, *, interval_seconds: float | None = None
) -> None:
    interval = _sync_interval(interval_seconds)
    while True:
        await asyncio.sleep(interval)
        try:
            await asyncio.to_thread(_sync_due, runtime)
        except Exception as error:
            LOGGER.error("personio_directory_sync_failed code=%s", type(error).__name__)


async def _bootstrap_retry_loop(
    runtime: DirectoryRuntime, *, interval_seconds: float | None = None
) -> None:
    """Retry collection preparation and initial sync before ordinary scheduling."""
    interval = _sync_interval(interval_seconds)
    while True:
        await asyncio.sleep(interval)
        try:
            await asyncio.to_thread(_sync_startup, runtime)
        except Exception as error:
            LOGGER.error("personio_directory_bootstrap_retry_failed code=%s", type(error).__name__)
            continue
        await _sync_loop(runtime, interval_seconds=interval_seconds)
        return


def _sync_due(runtime: DirectoryRuntime) -> None:
    if runtime.sync.full_sync_due(_utc_now()):
        runtime.sync.run_full()
    else:
        runtime.sync.run_delta()


def _sync_interval(interval_seconds: float | None) -> float:
    if interval_seconds is not None:
        return max(0.01, interval_seconds)
    return max(60, int(os.getenv("PERSONIO_DIRECTORY_SYNC_INTERVAL_SECONDS", "900")))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sync_age(value: str) -> timedelta:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    return datetime.now(timezone.utc) - parsed


def _is_stale(value: str | None) -> bool:
    return value is None or _sync_age(value) > timedelta(hours=24)


def _response_from_evidence(evidence: DirectoryEvidence, *, onboarding: bool) -> SearchResponse:
    """Keep the HTTP boundary safe even if a future search adapter regresses."""
    sources = _controlled_sources(evidence.sources)
    if onboarding:
        source_ids = {source["id"] for source in sources}
        claims = _onboarding_claims(evidence.claims, source_ids)
    else:
        claims = [dict(claim) for claim in evidence.claims]
    return SearchResponse(
        status=evidence.status,
        claims=claims,
        sources=sources,
        sync_completed_at=evidence.sync_completed_at,
        stale=evidence.stale,
    )


def _controlled_sources(sources: tuple[dict[str, str], ...]) -> list[dict[str, str]]:
    controlled: list[dict[str, str]] = []
    for source in sources:
        source_id = source.get("id")
        if isinstance(source_id, str) and _SOURCE_ID.fullmatch(source_id):
            controlled.append({"id": source_id, "kind": "personio_directory"})
    return controlled


def _onboarding_claims(
    claims: tuple[dict[str, object], ...], source_ids: set[str]
) -> list[dict[str, object]]:
    safe_claims: list[dict[str, object]] = []
    for claim in claims:
        safe = {
            field: value
            for field in _ONBOARDING_FIELDS
            if isinstance((value := claim.get(field)), str) and value
        }
        source_id = claim.get("source_id")
        if isinstance(source_id, str) and source_id in source_ids:
            safe["source_id"] = source_id
        if safe:
            safe_claims.append(safe)
    return safe_claims


app = create_app()
