# Personio Directory Harness Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** KAHLE-Vinci synchronisiert freigegebene Personio-Verzeichnisdaten in einen separaten Index und beantwortet reine sowie gemischte Mitarbeiterfragen über den gemeinsamen Knowledge Harness mit korrekter Quellenhoheit.

**Architecture:** Der neue interne Docker-Dienst `personio-directory` kapselt Personio-Authentifizierung, Sync-State, Datenschutzfilter, Qdrant-Index und Suche. Der vorhandene Knowledge Harness plant abhängig vom Informationsbedarf `personio_directory`, `rag_chat` oder beide; die OpenWebUI-Middleware führt gemischte Retrievals parallel aus und baut ein gemeinsames EvidenceBundle.

**Tech Stack:** Python 3.11, FastAPI, Uvicorn, Requests, SQLite, Qdrant REST API, Docker Compose, OpenWebUI-Middleware, Pytest

**Spec:** `docs/superpowers/specs/2026-08-24-personio-directory-harness-design.md`

## Global Constraints

- Personio ist für aktuelle Rolle, Team, Abteilung, Standort und dienstliche Kontaktdaten die führende Quelle.
- Der Personio-Adapter ist ausschließlich read-only; es werden keine POST-/PATCH-Aufrufe auf Mitarbeiterressourcen implementiert.
- Normale Suche umfasst `ACTIVE` und `LEAVE`; `ONBOARDING` ist ausschließlich bei explizitem Onboarding-Intent sichtbar.
- `INACTIVE`, `EXTERNAL` und nicht mehr gelieferte Personen werden aus der aktiven Collection entfernt.
- Onboarding-Evidenz enthält nur Name, Position, Abteilung, Team und Standort.
- Zugriff erhalten ausschließlich angemeldete OpenWebUI-Rollen `user` und `admin`; `pending` bleibt fail-closed.
- `PERSONIO_CLIENT_ID` und `PERSONIO_API` dürfen nicht geloggt, persistiert, in Test-Fixtures kopiert oder in Rolloutpakete aufgenommen werden.
- Technische Logs enthalten keine Namen, E-Mail-Adressen, Telefonnummern oder vollständigen Personio-Antworten.
- Reine Verzeichnisfragen verwenden nur `personio_directory`; reine Dokumentfragen nur `rag_chat`; gemischte Fragen verwenden beide Adapter parallel.
- Ein leerer Personio-Treffer fällt niemals auf alte Personaldaten in RAG oder Modellwissen zurück.
- Bestehende, nicht zu dieser Umsetzung gehörende Worktree-Änderungen werden weder überschrieben noch gemeinsam committed.

## File Structure

### Neuer Dienst `stack/personio-directory/`

- `Dockerfile`: minimales, unprivilegiertes Python-Laufzeitimage und Healthcheck-Abhängigkeiten.
- `requirements.txt`: fest gepinnte Laufzeitabhängigkeiten.
- `app/config.py`: validierte Umgebungsvariablen ohne Secret-Ausgabe.
- `app/models.py`: kanonische Personen-, Such- und Evidence-Datentypen.
- `app/policy.py`: Status-, Beschäftigungsart- und Feldfreigaben einschließlich Onboarding-Redaktion.
- `app/personio.py`: versionsgekapselter read-only Personio-Client und Attributerkennung.
- `app/state.py`: SQLite-Sync-State und atomarer Fortschrittszeiger.
- `app/index.py`: eigene Qdrant-Collection, Upsert, Suche und Löschung.
- `app/sync.py`: Voll-/Delta-Sync und Soll-Ist-Abgleich.
- `app/search.py`: Unter-Intent, exakte Filter, semantische Suche und Zusammenarbeit-Kaskade.
- `app/main.py`: interne FastAPI-Schnittstelle, Hintergrundsync und Health-Endpunkte.
- `tests/`: isolierte Unit- und Integrationstests ohne echte Secrets oder Personaldaten.

### Bestehende Integrationspunkte

- `stack/docker-compose.yml`: Dienst, Volumes, interne URL und Environment-Vertrag.
- `stack/docker-compose.prod.yml`: Produktionsressourcen.
- `stack/env.production.template`: Namen der Personio-Variablen ohne Werte.
- `stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py`: Mehrquellen-Retrievalplan und EvidenceBundle.
- `stack/open-webui-overrides/open_webui/utils/personio_directory_client.py`: interner, authentifizierter Client für OpenWebUI.
- `stack/open-webui-overrides/open_webui/utils/middleware.py`: deterministische Planung, parallele Aufrufe und Ergebniseinbindung.
- `scripts/openwebui/kahle-harness-acceptance-matrix.json`: Personio- und Mischfälle.
- `scripts/personio/probe.py`: read-only Feld-/API-Probe mit redigierter Ausgabe.
- `stack/tests/`: Compose-, Harness-, Middleware-, Secret- und Akzeptanzverträge.
- `docs/operations/personio-directory.md`: Einrichtung, Betrieb, Test und Rollback.

---

### Task 1: Kanonischer Daten- und Datenschutzvertrag

**Files:**
- Create: `stack/personio-directory/app/__init__.py`
- Create: `stack/personio-directory/app/models.py`
- Create: `stack/personio-directory/app/policy.py`
- Create: `stack/personio-directory/tests/conftest.py`
- Create: `stack/personio-directory/tests/test_policy.py`

**Interfaces:**
- Produces: `PersonRecord`, `DirectoryQuery`, `DirectoryHit`, `filter_person(raw, mapping) -> PersonRecord | None`, `public_payload(person, onboarding_requested) -> dict[str, object]`.
- Consumes: keine Anwendungskomponenten; Tests verwenden ausschließlich synthetische Datensätze.

- [ ] **Step 1: Write the failing status and field-policy tests**

```python
def test_policy_keeps_active_and_leave_but_hides_onboarding_by_default():
    assert filter_person(raw_person("ACTIVE", "INTERNAL"), MAPPING) is not None
    assert filter_person(raw_person("LEAVE", "INTERNAL"), MAPPING) is not None
    onboarding = filter_person(raw_person("ONBOARDING", "INTERNAL"), MAPPING)
    assert onboarding is not None
    assert public_payload(onboarding, onboarding_requested=False) == {}


def test_onboarding_payload_is_reduced_before_evidence_creation():
    person = filter_person(raw_person("ONBOARDING", "INTERNAL"), MAPPING)
    assert public_payload(person, onboarding_requested=True) == {
        "personio_id": "person-1",
        "display_name": "Erika Beispiel",
        "position": "Serviceberaterin",
        "department": "Service",
        "team": "Service Hannover",
        "office": "Hannover",
        "employment_status": "ONBOARDING",
    }


def test_policy_rejects_inactive_and_external_people():
    assert filter_person(raw_person("INACTIVE", "INTERNAL"), MAPPING) is None
    assert filter_person(raw_person("ACTIVE", "EXTERNAL"), MAPPING) is None
```

- [ ] **Step 2: Run the policy tests and verify RED**

Run:

```powershell
C:\kahle-vinci\.venv-test\Scripts\python.exe -m pytest stack/personio-directory/tests/test_policy.py -q
```

Expected: collection fails because `app.models` and `app.policy` do not exist.

- [ ] **Step 3: Implement immutable models and fail-closed policy**

Implement these exact public types:

```python
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
    employment_type: Literal["INTERNAL"]
    source_updated_at: str


@dataclass(frozen=True)
class DirectoryQuery:
    text: str
    intent: Literal["person_lookup", "directory_search", "coworker_lookup", "onboarding_search"]
    user_id: str
    user_role: str


@dataclass(frozen=True)
class DirectoryHit:
    personio_id: str
    score: float
    fields: dict[str, object]
```

`filter_person` rejects missing IDs, malformed names, unknown status values,
non-`INTERNAL` employment and private contact mappings. `public_payload`
returns `{}` for onboarding records unless `onboarding_requested=True` and
never includes contact or date fields for onboarding.

- [ ] **Step 4: Run the policy tests and verify GREEN**

Run the command from Step 2. Expected: PASS.

- [ ] **Step 5: Commit the policy slice**

```bash
git add stack/personio-directory/app stack/personio-directory/tests
git commit -m "feat: define Personio directory privacy policy"
```

---

### Task 2: Konfiguration und read-only Personio API-Probe

**Files:**
- Create: `stack/personio-directory/app/config.py`
- Create: `stack/personio-directory/app/personio.py`
- Create: `stack/personio-directory/tests/test_config.py`
- Create: `stack/personio-directory/tests/test_personio_client.py`
- Create: `scripts/personio/probe.py`

**Interfaces:**
- Consumes: `PersonRecord` and `filter_person` from Task 1.
- Produces: `PersonioConfig.from_env()`, `PersonioClient.discover_attributes()`, `PersonioClient.iter_people(updated_since=None)`, `ApiAssessment` with selected API version and field mapping.

- [ ] **Step 1: Write failing configuration and secret-redaction tests**

```python
def test_config_requires_both_credentials_without_echoing_values(monkeypatch):
    monkeypatch.setenv("PERSONIO_CLIENT_ID", "client-visible-only-to-process")
    monkeypatch.delenv("PERSONIO_API", raising=False)
    with pytest.raises(ConfigError, match="personio_api_required") as error:
        PersonioConfig.from_env()
    assert "client-visible-only-to-process" not in str(error.value)


def test_config_uses_expected_urls_and_read_only_timeout(monkeypatch):
    monkeypatch.setenv("PERSONIO_CLIENT_ID", "client")
    monkeypatch.setenv("PERSONIO_API", "secret")
    config = PersonioConfig.from_env()
    assert config.api_base_url == "https://api.personio.de"
    assert config.timeout_seconds == 20
```

- [ ] **Step 2: Write failing v1/v2 assessment and no-write HTTP tests**

Use a fake session that records methods. Cover:

```python
assessment = client.assess_api()
assert assessment.version in {"v1", "v2"}
assert assessment.mapping["business_email"]
assert all(call.method.lower() == "get" or call.url.endswith("/auth/token") for call in session.calls)
assert not any(call.method.lower() in {"patch", "put", "delete"} for call in session.calls)
```

V2 wins only when identity, status, employment type, position, department,
team, office, business e-mail and business phone can be resolved to useful
values. Otherwise the assessment selects v1 and records sanitized reason codes
such as `v2_team_unresolved`, never response bodies.

- [ ] **Step 3: Run focused tests and verify RED**

```powershell
C:\kahle-vinci\.venv-test\Scripts\python.exe -m pytest stack/personio-directory/tests/test_config.py stack/personio-directory/tests/test_personio_client.py -q
```

Expected: FAIL because configuration and client classes do not exist.

- [ ] **Step 4: Implement token handling, pagination and API assessment**

Implement the public methods `assess_api() -> ApiAssessment`,
`discover_attributes() -> dict[str, str]` and
`iter_people(updated_since: str | None = None) -> Iterator[dict[str, object]]`
on `PersonioClient`.

Requirements:

- token cached until five minutes before expiry;
- v1 pagination uses `limit=100` and increasing `offset`;
- v2 uses `limit=50` and follows cursor links;
- maximum response size and JSON shape are validated;
- 429 honors `Retry-After`, otherwise bounded exponential backoff with jitter;
- no employee write method exists on the public client;
- exceptions contain sanitized codes only.

- [ ] **Step 5: Implement the safe probe command**

`scripts/personio/probe.py` imports the client, performs `assess_api()` and
prints only:

```text
personio_probe_ok=true
selected_api=v1|v2
available_field_labels=<comma-separated labels without values>
mapped_fields=<comma-separated canonical field names>
eligible_count=<integer>
excluded_counts=INACTIVE:<n>,EXTERNAL:<n>,INVALID:<n>
```

It must never print credentials, tokens, headers, person names, e-mails,
telephone numbers, raw JSON or Personio IDs.

- [ ] **Step 6: Run focused tests and static secret scan**

```powershell
C:\kahle-vinci\.venv-test\Scripts\python.exe -m pytest stack/personio-directory/tests/test_config.py stack/personio-directory/tests/test_personio_client.py -q
rg -n "client-visible-only-to-process|Authorization.*Bearer|PERSONIO_API=" stack/personio-directory scripts/personio
```

Expected: tests PASS; scan finds no hard-coded secret or rendered bearer token.

- [ ] **Step 7: Commit the API slice**

```bash
git add stack/personio-directory/app/config.py stack/personio-directory/app/personio.py stack/personio-directory/tests scripts/personio/probe.py
git commit -m "feat: add read-only Personio API assessment"
```

---

### Task 3: Atomarer Sync-State und separate Qdrant-Collection

**Files:**
- Create: `stack/personio-directory/app/state.py`
- Create: `stack/personio-directory/app/index.py`
- Create: `stack/personio-directory/app/sync.py`
- Create: `stack/personio-directory/tests/test_state.py`
- Create: `stack/personio-directory/tests/test_sync.py`
- Create: `stack/personio-directory/tests/test_index.py`

**Interfaces:**
- Consumes: `PersonioClient.iter_people`, `filter_person`, `PersonRecord`.
- Produces: `SQLiteSyncState`, `QdrantDirectoryIndex`, `DirectorySync.run_delta()`, `DirectorySync.run_full()`.

- [ ] **Step 1: Write failing atomic-progress and full-reconciliation tests**

```python
def test_failed_delta_does_not_advance_success_cursor(tmp_path):
    state = SQLiteSyncState(tmp_path / "personio.sqlite3")
    sync = DirectorySync(FailingAfterOneClient(), FakeIndex(), state, now=clock)
    with pytest.raises(SyncError, match="personio_delta_failed"):
        sync.run_delta()
    assert state.last_successful_delta_at() is None


def test_full_sync_deletes_people_missing_from_personio(tmp_path):
    index = FakeIndex(existing_ids={"person-1", "person-removed"})
    report = DirectorySync(Client([active_person("person-1")]), index, state).run_full()
    assert index.deleted_ids == {"person-removed"}
    assert report.upserted == 1
    assert report.deleted == 1
```

- [ ] **Step 2: Write failing Qdrant payload and collection-isolation tests**

Assert collection name `vinci_personio_directory`, deterministic UUID5 point IDs,
payloads without private fields, and physical deletion by Personio ID. Assert no
request targets `vinci_knowledge`.

- [ ] **Step 3: Run tests and verify RED**

```powershell
C:\kahle-vinci\.venv-test\Scripts\python.exe -m pytest stack/personio-directory/tests/test_state.py stack/personio-directory/tests/test_sync.py stack/personio-directory/tests/test_index.py -q
```

- [ ] **Step 4: Implement SQLite state and Qdrant index**

SQLite tables:

```sql
CREATE TABLE sync_state(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE indexed_person(personio_id TEXT PRIMARY KEY, source_updated_at TEXT NOT NULL);
CREATE TABLE sync_run(id INTEGER PRIMARY KEY, kind TEXT NOT NULL, started_at INTEGER NOT NULL,
                      completed_at INTEGER, status TEXT NOT NULL, error_code TEXT);
```

Only a completed transaction updates `last_successful_delta_at`,
`last_successful_full_at` and the indexed-ID snapshot. Qdrant payloads contain
only fields from `PersonRecord` plus normalized exact-search fields and a
compact `search_text`.

- [ ] **Step 5: Implement delta overlap and daily full-sync decision**

`run_delta()` subtracts five minutes from the last successful cursor and uses
idempotent upserts. `full_sync_due(now)` returns true when no full sync exists
or it is at least 24 hours old. Individual invalid records increment sanitized
error counters and do not log field values.

- [ ] **Step 6: Run tests and verify GREEN**

Run the command from Step 3. Expected: PASS.

- [ ] **Step 7: Commit the sync slice**

```bash
git add stack/personio-directory/app/state.py stack/personio-directory/app/index.py stack/personio-directory/app/sync.py stack/personio-directory/tests
git commit -m "feat: synchronize Personio directory into Qdrant"
```

---

### Task 4: Verzeichnissuche und Zusammenarbeitskaskade

**Files:**
- Create: `stack/personio-directory/app/search.py`
- Create: `stack/personio-directory/tests/test_search.py`

**Interfaces:**
- Consumes: `DirectoryQuery`, `DirectoryHit`, `QdrantDirectoryIndex`.
- Produces: `DirectorySearch.search(query) -> DirectoryEvidence` and deterministic `classify_directory_query(text) -> str`.

- [ ] **Step 1: Write failing intent and onboarding-trigger tests**

```python
@pytest.mark.parametrize("text", [
    "Wer ist aktuell im Onboarding?",
    "Welche neuen Serviceberater sind im Onboarding?",
])
def test_explicit_onboarding_queries_select_onboarding_search(text):
    assert classify_directory_query(text) == "onboarding_search"


def test_new_alone_does_not_expose_onboarding():
    assert classify_directory_query("Welche neuen Kollegen arbeiten in Hannover?") != "onboarding_search"
```

- [ ] **Step 2: Write failing natural-person and coworker tests**

Cover „Was weißt du über …?“, „Wo arbeitet …?“, „Was macht …?“ and
„Mit wem arbeitet … zusammen?“. For coworker lookup assert the exact cascade:

```python
assert search.coworkers(person_with_team).basis == "team"
assert search.coworkers(person_without_team).basis == "position_and_office"
assert search.coworkers(person_without_team_or_position).basis == "department_and_office"
```

Assert office alone never returns coworkers.

- [ ] **Step 3: Run tests and verify RED**

```powershell
C:\kahle-vinci\.venv-test\Scripts\python.exe -m pytest stack/personio-directory/tests/test_search.py -q
```

- [ ] **Step 4: Implement exact filters plus semantic candidates**

Normalize Unicode, case, punctuation, phone digits and e-mail addresses.
Named-person queries require an exact normalized full-name or e-mail match
before semantic expansion. Directory list queries combine explicit status,
position, department, team and office filters with dense/sparse candidate
search. Results use stable ordering by relevance, display name and Personio ID.

- [ ] **Step 5: Implement redacted EvidenceBundle output**

`DirectoryEvidence` contains `status`, `claims`, `sources`, `sync_completed_at`
and `stale`. Personio source IDs use `P1`, `P2`, etc. Onboarding claims call
`public_payload(person, onboarding_requested=True)` and reject an empty result.

- [ ] **Step 6: Run tests and verify GREEN**

Run the command from Step 3. Expected: PASS.

- [ ] **Step 7: Commit the search slice**

```bash
git add stack/personio-directory/app/search.py stack/personio-directory/tests/test_search.py
git commit -m "feat: search Personio directory with privacy-aware intents"
```

---

### Task 5: Interne API, Hintergrundlauf und Compose-Vertrag

**Files:**
- Create: `stack/personio-directory/app/main.py`
- Create: `stack/personio-directory/Dockerfile`
- Create: `stack/personio-directory/requirements.txt`
- Create: `stack/personio-directory/tests/test_api.py`
- Modify: `stack/docker-compose.yml`
- Modify: `stack/docker-compose.prod.yml`
- Modify: `stack/env.production.template`
- Create: `stack/tests/test_personio_directory_contracts.py`

**Interfaces:**
- Consumes: `DirectorySync`, `DirectorySearch`, `PersonioConfig`.
- Produces: `GET /health`, `POST /internal/search`, periodic sync lifecycle.

- [ ] **Step 1: Write failing authorization and response-contract tests**

```python
def test_search_accepts_user_and_admin_but_rejects_pending(client):
    assert client.post("/internal/search", json=request(role="user")).status_code == 200
    assert client.post("/internal/search", json=request(role="admin")).status_code == 200
    assert client.post("/internal/search", json=request(role="pending")).status_code == 403


def test_onboarding_api_never_serializes_contact_fields(client):
    response = client.post("/internal/search", json=onboarding_request()).json()
    rendered = json.dumps(response)
    assert "business_email" not in rendered
    assert "business_phone" not in rendered
```

- [ ] **Step 2: Write failing Compose security tests**

Assert:

- no `ports:` on `personio-directory`;
- internal network only;
- read-only root filesystem, `cap_drop: ALL`, `no-new-privileges`;
- dedicated state volume;
- credentials passed only to this service;
- `PERSONIO_CLIENT_ID` and `PERSONIO_API` are required;
- OpenWebUI receives only `PERSONIO_DIRECTORY_URL` and the existing internal API key;
- healthcheck exists;
- production resources are 512 MiB, 1 CPU and 128 PIDs.

- [ ] **Step 3: Run API and Compose tests and verify RED**

```powershell
C:\kahle-vinci\.venv-test\Scripts\python.exe -m pytest stack/personio-directory/tests/test_api.py stack/tests/test_personio_directory_contracts.py -q
```

- [ ] **Step 4: Implement FastAPI endpoints and background loop**

`POST /internal/search` accepts:

```json
{"query":"Wo arbeitet Erika Beispiel?","intent":"person_lookup","user_id":"local-user-1","user_role":"user"}
```

It requires the existing internal `X-API-Key`, validates role and bounded input
length, and returns `DirectoryEvidence`. Startup performs an initial sync if no
valid index exists; afterward the loop wakes every 15 minutes and runs a full
sync when due. `/health` is healthy only with a readable state DB and at least
one successful sync no older than 48 hours.

- [ ] **Step 5: Add Docker and Compose configuration**

Pin `fastapi==0.116.1`, `uvicorn[standard]==0.35.0` and
`requests==2.32.4`, matching the existing backend runtime. Mount state at `/state`, use Qdrant at
`http://qdrant:6333`, and set collection `vinci_personio_directory`. Document
variable names without values in `env.production.template`.

- [ ] **Step 6: Run tests and rendered Compose validation**

```powershell
C:\kahle-vinci\.venv-test\Scripts\python.exe -m pytest stack/personio-directory/tests stack/tests/test_personio_directory_contracts.py -q
docker compose --env-file stack/.env.test -f stack/docker-compose.yml config --quiet
```

If `.env.test` is absent, use the repository's existing Compose contract test
fixture rather than introducing real credentials.

- [ ] **Step 7: Commit the service slice**

```bash
git add stack/personio-directory stack/docker-compose.yml stack/docker-compose.prod.yml stack/env.production.template stack/tests/test_personio_directory_contracts.py
git commit -m "feat: run internal Personio directory service"
```

---

### Task 6: Mehrquellenplanung im Knowledge Harness

**Files:**
- Modify: `stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py`
- Modify: `stack/tests/test_kahle_knowledge_harness.py`
- Modify: `stack/tests/test_kahle_harness_reference_matrix.py`

**Interfaces:**
- Consumes: vorhandene `UserIntent`, `ResolvedContext`, `RetrievalPlan`, `EvidenceBundle`.
- Produces: `plan_retrieval(query, resolved_query, messages, model_id, permission_scope) -> RetrievalPlan`, `merge_evidence(rag_result, personio_result) -> EvidenceBundle`.

- [ ] **Step 1: Write failing pure and mixed routing tests**

```python
@pytest.mark.parametrize((query, tools), [
    ("Wo arbeitet Max Mustermann?", ("personio_directory",)),
    ("Welche Arbeitsanweisung gilt im Service?", ("rag_chat",)),
    ("Was hat Stefan Schrader mit VSX zu tun?", ("personio_directory", "rag_chat")),
    ("Wie hängen Jan Oltmanns und KAHLE-Vinci zusammen?", ("personio_directory", "rag_chat")),
])
def test_retrieval_plan_uses_required_evidence_sources(query, tools):
    assert plan_retrieval(query, query, [], "kahle-vinci", SCOPE).required_tools == tools
```

Assert the same plan for Vinci, Thinking, Max-Thinking and a future Vinci model.

- [ ] **Step 2: Write failing source-authority and merged-citation tests**

Create synthetic Personio `[P1]` and RAG `[R1]` claims. Assert current role,
team and contact conflicts select `[P1]`, while a documented project relation
remains `[R1]`. Assert unknown `[P9]` and `[R9]` fail validation.

- [ ] **Step 3: Run harness tests and verify RED**

```powershell
C:\kahle-vinci\.venv-test\Scripts\python.exe -m pytest stack/tests/test_kahle_knowledge_harness.py stack/tests/test_kahle_harness_reference_matrix.py -q
```

- [ ] **Step 4: Extend RetrievalPlan compatibly**

Add `required_tools: tuple[str, ...]` and retain a read-only compatibility
property `required_tool` returning the single tool or `multi_source`. Move the
side-effect-free classification ahead of retrieval into `plan_retrieval`.
`build_decision` accepts both `rag_result` and `personio_result`, merges
evidence, and retains existing behavior for callers that provide only RAG.

- [ ] **Step 5: Implement deterministic information-need rules**

Directory-only markers cover current identity, role, position, contact, team,
department, office, colleague lists and explicit onboarding. RAG need markers
cover relationships expressed with „mit … zu tun“, „zusammenhängen“, projects,
systems, processes, responsibilities and work instructions. A query containing
both needs returns both tools. Web retrieval is never added by this classifier.

- [ ] **Step 6: Run harness tests and verify GREEN**

Run the command from Step 3. Expected: PASS including all pre-existing harness tests.

- [ ] **Step 7: Commit the harness slice**

```bash
git add stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py stack/tests/test_kahle_knowledge_harness.py stack/tests/test_kahle_harness_reference_matrix.py
git commit -m "feat: plan Personio and RAG evidence sources"
```

---

### Task 7: Parallele Retrievalausführung in OpenWebUI

**Files:**
- Create: `stack/open-webui-overrides/open_webui/utils/personio_directory_client.py`
- Modify: `stack/open-webui-overrides/open_webui/utils/middleware.py`
- Modify: `stack/docker-compose.yml`
- Modify: `stack/tests/test_middleware_internal_rag_routing.py`
- Modify: `stack/tests/test_kahle_toolcall_guard.py`

**Interfaces:**
- Consumes: `plan_retrieval`, internal `POST /internal/search`, existing RAG pre-route.
- Produces: one merged Harness decision plus observable `tool_called` values.

- [ ] **Step 1: Write failing no-RAG-fallback and role tests**

For „Wo arbeitet Max Mustermann?“ assert exactly one Personio client call, zero
RAG calls, and a stable unsupported result when Personio returns no hits. Assert
`pending` invokes neither backend.

- [ ] **Step 2: Write failing parallel mixed-query test**

Use two async fakes gated by events. Assert both calls start before either is
released for „Was hat Stefan Schrader mit VSX zu tun?“. Assert merged metadata:

```python
assert metadata["kahle_retrieval_tools"] == ["personio_directory", "rag_chat"]
assert metadata["kahle_knowledge_harness_shadow"]["evidence_bundle"]["sources"] == [P1, R1]
```

- [ ] **Step 3: Run middleware tests and verify RED**

```powershell
C:\kahle-vinci\.venv-test\Scripts\python.exe -m pytest stack/tests/test_middleware_internal_rag_routing.py stack/tests/test_kahle_toolcall_guard.py -q
```

- [ ] **Step 4: Implement the internal Personio client**

`PersonioDirectoryClient.search(query, intent, user_id, user_role)` sends user ID, role, query and directory
sub-intent with the internal API key. It validates response schema, has a short
timeout and returns sanitized `directory_unavailable` errors. No credentials or
payload values are logged.

- [ ] **Step 5: Reorder middleware into plan, execute, merge**

Build the retrieval plan before invoking either adapter. Use `asyncio.gather`
only when both tools are required; keep single-tool paths single-call. Preserve
native RAG sources, Personio source IDs, feedback link, active answer contract,
timeout and retry behavior. Personio outages yield partial evidence only when a
separate RAG need exists; a pure directory query fails closed.

- [ ] **Step 6: Run middleware and full stack contract tests**

```powershell
C:\kahle-vinci\.venv-test\Scripts\python.exe -m pytest stack/tests -q -p no:cacheprovider
```

Expected: all existing and new stack tests PASS.

- [ ] **Step 7: Commit the OpenWebUI slice**

```bash
git add stack/open-webui-overrides/open_webui/utils/personio_directory_client.py stack/open-webui-overrides/open_webui/utils/middleware.py stack/docker-compose.yml stack/tests
git commit -m "feat: retrieve Personio and RAG evidence in parallel"
```

---

### Task 8: Akzeptanzmatrix, Dokumentation und lokaler Real-API-Test

**Files:**
- Modify: `scripts/openwebui/kahle-harness-acceptance-matrix.json`
- Modify: `scripts/openwebui/kahle-harness-acceptance.py`
- Create: `docs/operations/personio-directory.md`
- Modify: `docs/research/2026-08-19-kahle-wissens-harness-audit.md`
- Test: `stack/tests/test_kahle_harness_acceptance_report.py`

**Interfaces:**
- Consumes: laufender lokaler Compose-Stack, probe command, Harness metadata.
- Produces: reproduzierbare lokale Abnahme ohne gespeicherte Personaldaten.

- [ ] **Step 1: Write failing acceptance-contract tests**

Add matrix cases for pure person lookup, directory filtering, onboarding
visibility, coworker cascade, pure RAG, and mixed Personio/RAG. Each case
declares exact `expected_tools`, intent, evidence status and forbidden fields.
The report test fails when a pure directory case contains `rag_chat` or a mixed
case lacks either tool.

- [ ] **Step 2: Run report tests and verify RED**

```powershell
C:\kahle-vinci\.venv-test\Scripts\python.exe -m pytest stack/tests/test_kahle_harness_acceptance_report.py -q
```

- [ ] **Step 3: Extend the acceptance report without PII persistence**

Store only case ID, model ID, expected/actual tools, intent, evidence status,
source kinds, validation status, latency and boolean assertions. Do not persist
questions containing real names, answer text, Personio IDs, contact values or
raw evidence.

- [ ] **Step 4: Document exact local preflight**

The runbook must instruct the operator to open a fresh PowerShell after setting
Windows variables, then verify presence without printing values:

```powershell
@('PERSONIO_CLIENT_ID','PERSONIO_API') | ForEach-Object {
  [pscustomobject]@{ Name = $_; Present = -not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($_)) }
}
```

Both values must show `Present=True`. If not, restart Codex and the PowerShell
session before proceeding.

- [ ] **Step 5: Run the real read-only probe**

From the fresh PowerShell:

```powershell
C:\kahle-vinci\.venv-test\Scripts\python.exe scripts/personio/probe.py
```

Expected: sanitized `personio_probe_ok=true`, selected API version, mapped field
names and counts only. Stop if required business fields are unmapped; adjust the
explicit label mapping in configuration, never by logging sample values.

- [ ] **Step 6: Start the local service and perform controlled sync**

Pass the two process variables to Compose without writing them to a tracked
file, build `personio-directory`, wait for healthy status, and inspect sanitized
cycle counters. Verify Qdrant collection count without scrolling payloads to the
terminal.

- [ ] **Step 7: Run automated suites**

```powershell
C:\kahle-vinci\.venv-test\Scripts\python.exe -m pytest stack/personio-directory/tests -q -p no:cacheprovider
C:\kahle-vinci\.venv-test\Scripts\python.exe -m pytest stack/tests -q -p no:cacheprovider
C:\kahle-vinci\.venv-test\Scripts\python.exe -m pytest stack/kb-admin-api/tests -q -p no:cacheprovider
C:\kahle-vinci\.venv-test\Scripts\python.exe -m pytest stack/kb-sync/tests -q -p no:cacheprovider
```

- [ ] **Step 8: Perform interactive `localhost:3004` acceptance**

With a `user` account and an `admin` account, run the 14 mandatory scenarios
from the spec. Use real names only interactively and do not save screenshots or
reports containing contact values. Inspect Harness metadata to prove pure and
mixed tool routes. Verify a `pending` account receives no directory result.

- [ ] **Step 9: Commit acceptance and operations documentation**

```bash
git add scripts/openwebui/kahle-harness-acceptance-matrix.json scripts/openwebui/kahle-harness-acceptance.py docs/operations/personio-directory.md docs/research/2026-08-19-kahle-wissens-harness-audit.md stack/tests/test_kahle_harness_acceptance_report.py
git commit -m "test: verify Personio directory harness end to end"
```

---

### Task 9: Review, Serverpaket und Produktionsfreigabe

**Files:**
- Create: `deploy/personio-directory-20260824/install.sh`
- Create: `deploy/personio-directory-20260824/payload/stack/personio-directory/`
- Create: `deploy/personio-directory-20260824/payload/stack/docker-compose.yml`
- Create: `deploy/personio-directory-20260824/payload/stack/docker-compose.prod.yml`
- Create: `deploy/personio-directory-20260824/payload/stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py`
- Create: `deploy/personio-directory-20260824/payload/stack/open-webui-overrides/open_webui/utils/personio_directory_client.py`
- Create: `deploy/personio-directory-20260824/payload/stack/open-webui-overrides/open_webui/utils/middleware.py`
- Create: `deploy/personio-directory-20260824.tar.gz`
- Modify: `docs/operations/personio-directory.md`

**Interfaces:**
- Consumes: vollständig getesteter und reviewter lokaler Stand.
- Produces: prüfsummenvalidiertes, rückrollbares SSH-Rolloutpaket ohne Secrets.

- [ ] **Step 1: Request code review against the spec**

Use `superpowers:requesting-code-review` and review all commits since
`ccec16a`. Resolve every correctness, privacy, authorization and rollback issue
before packaging.

- [ ] **Step 2: Run final verification from clean process contexts**

Run all Task-8 test commands, `git diff --check`, tool bundle checks if touched,
and rendered Compose validation. Record only test counts and command exit codes.

- [ ] **Step 3: Build a minimal rollback-capable package**

Package only the new service, exact modified Compose/OpenWebUI/Harness files,
tests excluded from production payload, and an `install.sh` at archive root.
The installer:

- requires root;
- checks that `PERSONIO_CLIENT_ID` and `PERSONIO_API` exist and are non-empty in
  `/opt/kahle-vinci/stack/.env.production` without displaying them;
- backs up every replaced target under
  `/opt/kahle-vinci/.rollout-backups/personio-directory-<UTC timestamp>`;
- validates Python syntax and `docker compose config --quiet`;
- builds and starts only affected services;
- rolls back files and restarts the previous services on any error.

- [ ] **Step 4: Verify package structure and checksum locally**

Use Git Bash `bash -n`, list the archive, and compute SHA-256. Assert no `.env`,
SQLite, JSON response, log, token or credential file is present.

- [ ] **Step 5: Commit and push the final reviewed application state**

Stage only Personio feature files and intentional Harness integration changes.
Do not include unrelated worktree changes. Push only after the user authorizes
the final production update.

- [ ] **Step 6: Transfer through the established KAHLE-Vinci SSH path**

Use:

```powershell
scp `
  -i "$env:USERPROFILE\.ssh\kahle-vinci-admin" `
  -o IdentitiesOnly=yes `
  "C:\kahle-vinci\deploy\personio-directory-20260824.tar.gz" `
  joltmanns@152.53.158.166:/tmp/personio-directory-20260824.tar.gz
```

The operator adds the two secret values manually to `.env.production`, verifies
the published SHA-256, extracts under `/tmp/personio-directory-20260824`, and
runs `sudo bash install.sh`.

- [ ] **Step 7: Perform production smoke tests without exposing PII**

Verify container health, sanitized sync counters, collection count, pure
Personio tool routing, pure RAG routing and one mixed query. Confirm no secret or
personal value appears in Docker logs. Do not mark production complete until
all checks pass.
