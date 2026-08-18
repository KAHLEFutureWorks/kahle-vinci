# LearningSuite Academy-Provisioning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Einen internen Worker bereitstellen, der berechtigte KAHLE-Vinci-Nutzer einmalig in LearningSuite anlegt und ihnen den Kurs „Einführung in die KAHLE-Vinci Nutzung“ freischaltet.

**Architecture:** Der neue, nicht öffentlich erreichbare Docker-Dienst `academy-provisioner` liest die OpenWebUI-SQLite-Datenbank als Read-only-Quelle und speichert seinen eigenen Bearbeitungsstatus separat. Ein tiefes Modul `AcademyProvisioner` kapselt die Rollenprüfung, Namensvalidierung, LearningSuite-Anlage, Kurszugangsprüfung und Idempotenz hinter `run_once()`.

**Tech Stack:** Python 3.11, SQLite aus der Standardbibliothek, `requests==2.32.4`, Docker Compose, Pytest.

**Spec:** `docs/superpowers/specs/2026-08-18-learningsuite-academy-provisioning-design.md`

## Global Constraints

- Ausschließlich die OpenWebUI-Rollen `user` und `admin` sind berechtigt. `pending` wird nie an LearningSuite übertragen.
- Zielkurs: exakter veröffentlichter Kursname `Einführung in die KAHLE-Vinci Nutzung`; null oder mehrere Treffer sind ein fachlicher Fehler ohne Zugangsvergabe.
- Die erste Ausbaustufe führt keine Deaktivierung, Löschung, Entziehung oder Stammdaten-Synchronisierung für bereits erfolgreiche Nutzer aus.
- Pro neuem Nutzer wird genau eine Kurszugangs-E-Mail inklusive Login-Link ausgelöst. Die allgemeine LearningSuite-Willkommens-E-Mail wird unterdrückt.
- `LEARNINGSUITE_API_KEY` bleibt ausschließlich in `stack/.env.production`; weder Tests, Logs noch Git-Dateien enthalten reale Secrets.
- Der Dienst erhält das `open-webui`-Volume nur als `:ro`, veröffentlicht keinen Port und schreibt nur in sein eigenes Statusvolume.
- Protokolle enthalten keine Namen, E-Mail-Adressen, API-Keys oder vollständigen externen Antworten.

---

## Zielstruktur

| Datei | Verantwortung |
| --- | --- |
| `stack/academy-provisioner/Dockerfile` | Reproduzierbares Python-3.11-Image ohne Laufzeit-Extras. |
| `stack/academy-provisioner/requirements.txt` | Genau die HTTP-Abhängigkeit `requests==2.32.4`. |
| `stack/academy-provisioner/app/models.py` | Unveränderliche Datenträger für OpenWebUI-Nutzer und Provisionierungsergebnisse. |
| `stack/academy-provisioner/app/config.py` | Vollständige, fail-closed Konfigurationsvalidierung. |
| `stack/academy-provisioner/app/openwebui.py` | Read-only-SQLite-Abfrage und Name-zu-Vor-/Nachname-Aufteilung. |
| `stack/academy-provisioner/app/learningsuite.py` | LearningSuite-Adapter mit `X-API-KEY`, Timeout und fachlichen Fehlern. |
| `stack/academy-provisioner/app/state.py` | Eigene SQLite-Tabelle für Erfolg, Fehler und Herzschlag. |
| `stack/academy-provisioner/app/provisioner.py` | `AcademyProvisioner.run_once()` als tiefe fachliche Schnittstelle. |
| `stack/academy-provisioner/app/worker.py` | Startschleife, strukturiertes Logging und Herzschlag. |
| `stack/academy-provisioner/app/healthcheck.py` | Prüft den frischen Herzschlag ohne Netzwerkanfrage. |
| `stack/academy-provisioner/tests/` | Isolierte Tests mit Fake-Adaptern, ohne echte Secrets oder HTTP-Aufrufe. |
| `stack/docker-compose.yml` | Interner Dienst, Read-only-Mount und eigenes Named Volume. |
| `stack/docker-compose.prod.yml` | Ressourcen- und Prozessgrenzen für den neuen Dienst. |
| `stack/env.production.template` | Dokumentiert die serverseitigen LearningSuite-Variablen ohne Geheimwert. |
| `stack/tests/test_academy_provisioner_contracts.py` | Statischer Compose- und Secret-Vertrag. |
| `docs/operations/learningsuite-academy-provisioning.md` | Rollout, Testlauf und Störungsbehebung für den Betrieb. |

## Gemeinsame Interfaces

Alle späteren Aufgaben verwenden diese Namen unverändert:

```python
@dataclass(frozen=True)
class EligibleUser:
    openwebui_id: str
    email: str
    first_name: str
    last_name: str
    role: str

class OpenWebUIUserReader(Protocol):
    def eligible_users(self) -> list[EligibleUser]: ...
    def invalid_user_ids(self) -> list[str]: ...

class LearningSuiteClient(Protocol):
    def resolve_course_id(self, course_name: str) -> str: ...
    def find_or_create_member(self, user: EligibleUser) -> str: ...
    def has_course_access(self, member_id: str, course_id: str) -> bool: ...
    def grant_course_access(self, member_id: str, course_id: str) -> None: ...

class ProvisioningStateStore(Protocol):
    def was_completed(self, openwebui_id: str) -> bool: ...
    def record_completed(self, openwebui_id: str, member_id: str) -> None: ...
    def record_failure(self, openwebui_id: str, error_code: str) -> None: ...
    def record_heartbeat(self, epoch_seconds: int) -> None: ...

class AcademyProvisioner:
    def run_once(self) -> dict[str, int]: ...
```

### Task 1: Konfiguration, Datenmodell und LearningSuite-Adapter

**Files:**

- Create: `stack/academy-provisioner/requirements.txt`
- Create: `stack/academy-provisioner/app/__init__.py`
- Create: `stack/academy-provisioner/app/models.py`
- Create: `stack/academy-provisioner/app/config.py`
- Create: `stack/academy-provisioner/app/learningsuite.py`
- Create: `stack/academy-provisioner/tests/conftest.py`
- Create: `stack/academy-provisioner/tests/test_config_and_learningsuite.py`

**Interfaces:**

- Consumes: Umgebungsvariablen `LEARNINGSUITE_API_KEY`, `LEARNINGSUITE_API_BASE_URL`, `LEARNINGSUITE_COURSE_NAME` und `LEARNINGSUITE_PROVISION_INTERVAL_SECONDS`.
- Produces: `EligibleUser`, `ProvisioningError`, `ProvisioningConfig` und den konkreten Adapter `RequestsLearningSuiteClient`.

- [ ] **Step 1: Die fehlschlagenden Konfigurations- und Adaptertests schreiben**

```python
def test_config_rejects_missing_api_key(monkeypatch):
    monkeypatch.delenv("LEARNINGSUITE_API_KEY", raising=False)
    with pytest.raises(ConfigError, match="learningsuite_api_key_required"):
        ProvisioningConfig.from_env()

def test_resolve_course_id_requires_exactly_one_published_title(fake_session):
    fake_session.get.return_value.json.return_value = [
        {"id": "course-1", "name": "Einführung in die KAHLE-Vinci Nutzung"},
        {"id": "course-2", "name": "Einführung in die KAHLE-Vinci Nutzung"},
    ]
    client = RequestsLearningSuiteClient("https://api.test/api/v1", "secret", fake_session)
    with pytest.raises(ProvisioningError, match="course_name_ambiguous"):
        client.resolve_course_id("Einführung in die KAHLE-Vinci Nutzung")

def test_new_member_uses_course_email_instead_of_welcome_email(fake_session):
    client = RequestsLearningSuiteClient("https://api.test/api/v1", "secret", fake_session)
    member_id = client.find_or_create_member(EligibleUser("u-1", "a@kahle.de", "Amal", "Remo", "user"))
    client.grant_course_access(member_id, "course-1")
    assert fake_session.post.call_args.kwargs["json"]["disableLoginEmail"] is True
    assert fake_session.put.call_args.kwargs["json"] == {
        "courseIds": ["course-1"],
        "disableAccessNotificationEmail": False,
        "sendLoginLinkInCourseEmail": True,
    }
```

- [ ] **Step 2: Tests rot ausführen**

Run: `python -m pytest stack/academy-provisioner/tests/test_config_and_learningsuite.py -q`

Expected: FAIL, weil das Paket und die importierten Typen noch nicht existieren.

- [ ] **Step 3: Minimalen Konfigurations- und HTTP-Adapter implementieren**

```python
class ProvisioningError(RuntimeError):
    pass

@dataclass(frozen=True)
class ProvisioningConfig:
    api_key: str
    api_base_url: str
    course_name: str
    interval_seconds: int

    @classmethod
    def from_env(cls) -> "ProvisioningConfig":
        api_key = os.getenv("LEARNINGSUITE_API_KEY", "").strip()
        if not api_key:
            raise ConfigError("learningsuite_api_key_required")
        return cls(api_key, os.getenv("LEARNINGSUITE_API_BASE_URL", "https://api.learningsuite.io/api/v1").rstrip("/"),
                   os.getenv("LEARNINGSUITE_COURSE_NAME", "Einführung in die KAHLE-Vinci Nutzung").strip(),
                   max(60, int(os.getenv("LEARNINGSUITE_PROVISION_INTERVAL_SECONDS", "60"))))
```

Implement `RequestsLearningSuiteClient` mit festen 20-Sekunden-Timeouts und dem Header `X-API-KEY`. Es muss `GET /courses/published`, `GET /members/by-email`, `POST /members`, `GET /members/{memberId}/courses` und `PUT /members/{memberId}/courses` kapseln. Für `POST /members` sind `ignoreIfAlreadyExists: true`, `disableLoginEmail: true` und `locale: "de"` verbindlich. Der Adapter übersetzt 404 bei der Mitgliedersuche in „nicht vorhanden“ und alle anderen nicht erfolgreichen Antworten in einen fehlerklassifizierten `ProvisioningError`, ohne Response-Text in die Ausnahme aufzunehmen.

- [ ] **Step 4: Tests grün ausführen**

Run: `python -m pytest stack/academy-provisioner/tests/test_config_and_learningsuite.py -q`

Expected: PASS.

- [ ] **Step 5: Commit erstellen**

```bash
git add stack/academy-provisioner
git commit -m "feat: add learningsuite client"
```

### Task 2: Read-only-Nutzerleser und persistenter Bearbeitungsstatus

**Files:**

- Create: `stack/academy-provisioner/app/openwebui.py`
- Create: `stack/academy-provisioner/app/state.py`
- Create: `stack/academy-provisioner/tests/test_openwebui_and_state.py`

**Interfaces:**

- Consumes: `EligibleUser` aus `app.models` sowie die Pfade `OPENWEBUI_DB_PATH` und `LEARNINGSUITE_STATE_DB_PATH`.
- Produces: `SQLiteOpenWebUIUserReader` und `SQLiteProvisioningStateStore`, die die gemeinsamen Reader- und Store-Interfaces erfüllen.

- [ ] **Step 1: Die fehlschlagenden SQLite-Tests schreiben**

```python
def test_reader_returns_only_user_and_admin_with_split_names(tmp_path):
    db = make_webui_db(tmp_path, [
        ("pending-1", "Pending Person", "pending@kahle.de", "pending"),
        ("user-1", "Amal Remo", "amal@kahle.de", "user"),
        ("admin-1", "Jan Oltmanns", "jan@kahle.de", "admin"),
    ])
    assert SQLiteOpenWebUIUserReader(db).eligible_users() == [
        EligibleUser("user-1", "amal@kahle.de", "Amal", "Remo", "user"),
        EligibleUser("admin-1", "jan@kahle.de", "Jan", "Oltmanns", "admin"),
    ]

def test_reader_rejects_single_word_name_without_crashing(tmp_path):
    db = make_webui_db(tmp_path, [("user-1", "Amal", "amal@kahle.de", "user")])
    reader = SQLiteOpenWebUIUserReader(db)
    assert reader.eligible_users() == []
    assert reader.invalid_user_ids() == ["user-1"]

def test_state_records_completion_failure_and_heartbeat(tmp_path):
    state = SQLiteProvisioningStateStore(tmp_path / "state.sqlite3")
    state.record_completed("user-1", "member-1")
    state.record_failure("user-2", "invalid_name")
    state.record_heartbeat(1_786_000_000)
    assert state.was_completed("user-1")
    assert state.last_error("user-2") == "invalid_name"
    assert state.heartbeat_epoch() == 1_786_000_000
```

- [ ] **Step 2: Tests rot ausführen**

Run: `python -m pytest stack/academy-provisioner/tests/test_openwebui_and_state.py -q`

Expected: FAIL, weil Reader und Store noch nicht existieren.

- [ ] **Step 3: Read-only-Abfrage und Zustandsspeicher implementieren**

```python
SELECT id, name, email, role
FROM user
WHERE lower(coalesce(role, '')) IN ('user', 'admin')
ORDER BY id
```

Öffne die OpenWebUI-Datenbank mit SQLite-Lesezugriff und verwende keine DDL- oder DML-Anweisung gegen sie. Normalisiere E-Mail mit `strip().lower()`. Teile Namen ausschließlich bei mindestens zwei nichtleeren Bestandteilen in `first_name = parts[0]` und `last_name = " ".join(parts[1:])`. Überspringe unvollständige Namen im Reader und gib deren IDs über `invalid_user_ids()` an den Orchestrator zurück, damit dieser `invalid_name` im eigenen Zustand markieren kann.

Initialisiere den State Store mit einer Tabelle `provisioning_state(openwebui_id text primary key, member_id text, completed_at integer, last_error text, updated_at integer)` und einer Tabelle `worker_state(key text primary key, value text not null)`. Verwende Transaktionen für jede Änderung und speichere die Herzschlagzeit unter dem Schlüssel `heartbeat_epoch`.

- [ ] **Step 4: Tests grün ausführen**

Run: `python -m pytest stack/academy-provisioner/tests/test_openwebui_and_state.py -q`

Expected: PASS.

- [ ] **Step 5: Commit erstellen**

```bash
git add stack/academy-provisioner/app/openwebui.py stack/academy-provisioner/app/state.py stack/academy-provisioner/tests/test_openwebui_and_state.py
git commit -m "feat: read eligible openwebui users"
```

### Task 3: Idempotenter Provisionierungsablauf und Worker

**Files:**

- Create: `stack/academy-provisioner/app/provisioner.py`
- Create: `stack/academy-provisioner/app/worker.py`
- Create: `stack/academy-provisioner/app/healthcheck.py`
- Create: `stack/academy-provisioner/Dockerfile`
- Create: `stack/academy-provisioner/tests/test_provisioner.py`
- Create: `stack/academy-provisioner/tests/test_worker_and_healthcheck.py`

**Interfaces:**

- Consumes: `OpenWebUIUserReader`, `LearningSuiteClient`, `ProvisioningStateStore` und `ProvisioningConfig` aus den vorherigen Aufgaben.
- Produces: `AcademyProvisioner.run_once() -> dict[str, int]`, `run_forever()` sowie `healthcheck.main() -> int`.

- [ ] **Step 1: Die fehlschlagenden Orchestrierungs- und Resilienztests schreiben**

```python
def test_pending_is_never_sent_to_learningsuite():
    client = FakeClient()
    provisioner = AcademyProvisioner(FakeReader([]), client, FakeState(), "Einführung in die KAHLE-Vinci Nutzung")
    assert provisioner.run_once() == {"completed": 0, "failed": 0, "skipped": 0}
    assert client.calls == []

def test_existing_member_with_existing_access_sends_no_email_again():
    user = EligibleUser("u-1", "amal@kahle.de", "Amal", "Remo", "user")
    client = FakeClient(member_id="member-1", has_access=True)
    provisioner = AcademyProvisioner(FakeReader([user]), client, FakeState(), "Einführung in die KAHLE-Vinci Nutzung")
    provisioner.run_once()
    assert client.grants == []

def test_one_user_failure_does_not_block_next_user():
    users = [EligibleUser("u-1", "a@kahle.de", "A", "One", "user"), EligibleUser("u-2", "b@kahle.de", "B", "Two", "admin")]
    provisioner = AcademyProvisioner(FakeReader(users), FailingFirstClient(), FakeState(), "Einführung in die KAHLE-Vinci Nutzung")
    assert provisioner.run_once() == {"completed": 1, "failed": 1, "skipped": 0}

def test_healthcheck_rejects_stale_heartbeat(tmp_path):
    state = SQLiteProvisioningStateStore(tmp_path / "state.sqlite3")
    state.record_heartbeat(100)
    assert health_status(state, now_epoch=221, max_age_seconds=120) == 1
```

- [ ] **Step 2: Tests rot ausführen**

Run: `python -m pytest stack/academy-provisioner/tests/test_provisioner.py stack/academy-provisioner/tests/test_worker_and_healthcheck.py -q`

Expected: FAIL, weil Orchestrator, Worker und Healthcheck fehlen.

- [ ] **Step 3: Den tiefen Orchestrator und die Worker-Schleife implementieren**

```python
def run_once(self) -> dict[str, int]:
    result = {"completed": 0, "failed": 0, "skipped": 0}
    for openwebui_id in self.reader.invalid_user_ids():
        self.state.record_failure(openwebui_id, "invalid_name")
        result["failed"] += 1
    users = self.reader.eligible_users()
    if not users:
        return result
    course_id = self.client.resolve_course_id(self.course_name)
    for user in users:
        try:
            member_id = self.client.find_or_create_member(user)
            if not self.client.has_course_access(member_id, course_id):
                self.client.grant_course_access(member_id, course_id)
            self.state.record_completed(user.openwebui_id, member_id)
            result["completed"] += 1
        except ProvisioningError as error:
            self.state.record_failure(user.openwebui_id, error.code)
            result["failed"] += 1
    return result
```

Der tatsächliche Orchestrator darf bereits abgeschlossene Nutzer überspringen, nachdem er sicher weiß, dass sie nicht erneut verarbeitet werden müssen. Bei vorherigem Fehler oder unvollständigem Zustand muss er die tatsächliche Academy-Mitgliedschaft und den Kurszugang erneut prüfen. `worker.run_forever()` ruft `run_once()` auf, protokolliert nur Zähler und Fehlercode, schreibt nach einem vollständig beendeten Durchlauf den Herzschlag und schläft mindestens 60 Sekunden. Eine Ausnahme außerhalb einzelner Nutzervorgänge darf den Prozess nicht beenden.

Das Dockerfile basiert auf `python:3.11-slim`, installiert `requirements.txt`, kopiert ausschließlich `app/`, setzt `PYTHONDONTWRITEBYTECODE=1` und startet `python -m app.worker`. Der Container bleibt mit `read_only: true` nutzbar, weil SQLite-Staat und `/tmp` später als Mounts bereitstehen.

- [ ] **Step 4: Tests grün ausführen**

Run: `python -m pytest stack/academy-provisioner/tests -q`

Expected: PASS.

- [ ] **Step 5: Commit erstellen**

```bash
git add stack/academy-provisioner
git commit -m "feat: provision academy users"
```

### Task 4: Sichere Compose-Integration und Betriebsdokumentation

**Files:**

- Modify: `stack/docker-compose.yml`
- Modify: `stack/docker-compose.prod.yml`
- Modify: `stack/env.production.template`
- Create: `stack/tests/test_academy_provisioner_contracts.py`
- Create: `docs/operations/learningsuite-academy-provisioning.md`

**Interfaces:**

- Consumes: Das Image `stack/academy-provisioner`, die vier `LEARNINGSUITE_*`-Umgebungsvariablen und das benannte Volume `open-webui`.
- Produces: Einen internen, eingeschränkten Docker-Dienst sowie eine reproduzierbare Server-Abnahme.

- [ ] **Step 1: Die fehlschlagenden Compose- und Geheimnis-Vertragstests schreiben**

```python
def test_academy_provisioner_is_internal_and_reads_openwebui_read_only():
    compose = COMPOSE.read_text(encoding="utf-8")
    block = compose.split("  academy-provisioner:", 1)[1].split("\n  n8n:", 1)[0]
    assert "build:\n      context: ./academy-provisioner" in block
    assert "- open-webui:/open-webui-data:ro" in block
    assert "ports:" not in block
    assert "read_only: true" in block
    assert "cap_drop:\n      - ALL" in block
    assert "LEARNINGSUITE_API_KEY: ${LEARNINGSUITE_API_KEY:?LEARNINGSUITE_API_KEY is required}" in block

def test_production_template_documents_secret_without_real_value():
    template = TEMPLATE.read_text(encoding="utf-8")
    assert "LEARNINGSUITE_API_KEY=<secret>" in template
    assert "LEARNINGSUITE_COURSE_NAME=Einführung in die KAHLE-Vinci Nutzung" in template
    assert "LEARNINGSUITE_API_KEY=" not in "\n".join(line for line in template.splitlines() if "<secret>" not in line)
```

- [ ] **Step 2: Tests rot ausführen**

Run: `python -m pytest stack/tests/test_academy_provisioner_contracts.py -q`

Expected: FAIL, weil Dienst, Variablen und Betriebsdokumentation fehlen.

- [ ] **Step 3: Compose, Produktionslimits und Betriebsvorgehen ergänzen**

Füge in `stack/docker-compose.yml` den Dienst `academy-provisioner` vor `n8n` hinzu. Er baut aus `./academy-provisioner`, nutzt `restart: unless-stopped`, erhält die vier LearningSuite-Variablen, `OPENWEBUI_DB_PATH=/open-webui-data/webui.db` und `LEARNINGSUITE_STATE_DB_PATH=/state/provisioning.sqlite3`. Mounts sind exakt `open-webui:/open-webui-data:ro` und `academy_provisioner_state:/state`; außerdem `read_only: true`, `tmpfs: [/tmp]`, `security_opt: [no-new-privileges:true]`, `cap_drop: [ALL]`, Netzwerk `appnet` und ein Healthcheck über `python -m app.healthcheck`. Ergänze am Ende das Volume `academy_provisioner_state: {}`.

Füge in `stack/docker-compose.prod.yml` für den Dienst die Grenzen `mem_limit: 256m`, `cpus: 0.5` und `pids_limit: 128` hinzu. Ergänze die vier Konfigurationszeilen in `stack/env.production.template`, mit `<secret>` ausschließlich für den API-Key.

Die Betriebsdokumentation muss diese konkreten Schritte enthalten: API-Key mit `chmod 600` in `stack/.env.production` eintragen, Compose-Konfiguration ohne Start prüfen, Dienst bauen, Testkonto zunächst als `pending` beobachten, auf `user` setzen, genau eine Kursmail kontrollieren, Kurszugang in LearningSuite prüfen, Log ohne personenbezogene Daten kontrollieren und den Container erneut starten. Als Fehlerbilder dokumentieren: fehlender API-Key, kein oder mehrfacher Kursname, HTTP 429/5xx und fehlender Name in OpenWebUI.

- [ ] **Step 4: Tests und Compose-Validierung grün ausführen**

Run: `python -m pytest stack/tests/test_academy_provisioner_contracts.py -q; python stack/tests/compose_static_check.py; docker compose -f stack/docker-compose.yml -f stack/docker-compose.prod.yml config --quiet`

Expected: Alle drei Befehle enden erfolgreich; die Compose-Ausgabe enthält keinen veröffentlichten Port für `academy-provisioner`.

- [ ] **Step 5: Vollständige Suite ausführen und Commit erstellen**

Run: `python -m pytest stack/academy-provisioner/tests stack/tests/test_academy_provisioner_contracts.py -q`

Expected: PASS.

```bash
git add stack/docker-compose.yml stack/docker-compose.prod.yml stack/env.production.template stack/tests/test_academy_provisioner_contracts.py docs/operations/learningsuite-academy-provisioning.md
git commit -m "feat: deploy academy provisioner"
```

## Abschließende Produktionsabnahme

1. Den realen LearningSuite-API-Key ausschließlich in `stack/.env.production` auf dem Vinci-Server eintragen.
2. `academy-provisioner` starten und seine Gesundheit prüfen.
3. Einen dedizierten Testnutzer per Microsoft-SSO anmelden. Seine Rolle muss zunächst `pending` sein.
4. Bestätigen, dass für `pending` weder ein Academy-Mitglied noch eine E-Mail entsteht.
5. Die Rolle auf `user` ändern und höchstens 60 Sekunden warten.
6. Prüfen, dass der Academy-Nutzer mit Microsoft-E-Mail, Vor- und Nachname angelegt wurde und exakt der Kurs „Einführung in die KAHLE-Vinci Nutzung“ sichtbar ist.
7. Die eine Kurszugangs-E-Mail mit Login-Link prüfen.
8. Den Provisioner neu starten und mindestens einen weiteren Zyklus abwarten. Weder ein zweites Academy-Konto noch eine zweite E-Mail darf entstehen.
