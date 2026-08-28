# Security

## Security Scope

KAHLE-Vinci verarbeitet Benutzeridentitäten, Chats und Dateien aus Open WebUI,
interne Wissensdokumente, Portalrollen und Berechtigungen sowie ausgewählte
Personio- und Academy-Daten. Diese Inhalte sind sicherheitsrelevant und können
personenbezogen oder intern vertraulich sein. Aus dem Repository allein werden
keine rechtlichen Klassifizierungen abgeleitet.

Dieses Dokument beschreibt den aktuell belegten Sicherheitsaufbau. Es ersetzt
keine produktive Risikoanalyse und behauptet keinen aktuellen Live-Nachweis.

## Trust Boundaries

| Grenze | Aktuelle Kontrolle |
| --- | --- |
| Browser zu Caddy | HTTPS und Routing in der Produktionskonfiguration |
| Caddy zu Open WebUI | Weiterleitung des allgemeinen Chatverkehrs |
| Caddy zu Wissensportal | `forward_auth` und Weiterleitung an Portal-UI und Portal-API |
| Portal-API zu Open WebUI | Validierung der weitergereichten Sitzung über `/api/v1/auths/` |
| Portal-API zu Portalbestand | Rollen-, Rechte-, Lifecycle- und Auditlogik |
| API-Key-geschützte interne HTTP-Dienste | `owui-file-proxy`, `document-worker`, `kb-sync`, `personio-directory` und interne Endpunkte der `kb-admin-api` prüfen dienstspezifische Schlüssel |
| Qdrant, ClamAV und SearxNG | keine dienstseitige Request-Authentifizierung in der aktuellen Compose-Konfiguration; Schutz durch fehlende öffentliche Caddy-Routen, begrenzte Host-Exposition sowie Container- und Netzwerkgrenzen |
| n8n zu gemeinsam genutzten Daten | n8n besitzt für Retention- und Cleanup-Abläufe Schreibzugriff auf `open-webui` und `document_worker_data`; `knowledgebases` ist nur lesbar eingebunden |
| Dienste zu externen Providern | separate Credentials aus nicht versionierter Konfiguration |
| Persistenz zu Qdrant | Qdrant ist abgeleiteter Index, nicht führende Quelle |

## Authentication

In Produktion erfolgt die Benutzeranmeldung über Microsoft Entra und Open
WebUI. Der registrierte Rücksprung ist der Open-WebUI-Pfad
`/oauth/microsoft/callback`. Das Wissensportal besitzt keinen separaten OAuth-
oder Step-up-Callback.

Die Portal-API reicht vorhandene `Authorization`-, Cookie- und User-Agent-
Header an Open WebUI weiter. Nur eine erfolgreiche Antwort des
Open-WebUI-Authentifizierungsendpunkts liefert die Identität. Fehlende oder
unvollständige Identitäten werden abgewiesen.

`KB_ADMIN_DEV_AUTH_BYPASS` existiert für lokale Entwicklung und isolierte
Tests. Er ist kein Produktions-Authentifizierungsmodell und darf nicht in eine
produktive Konfiguration übernommen werden.

## Authorization

### Knowledge portal

Nach der Open-WebUI-Anmeldung prüft die Portal-API:

1. stabile Benutzer-ID und E-Mail-Adresse;
2. eine Domain aus `PORTAL_ALLOWED_EMAIL_DOMAINS`;
3. eine synchronisierte, aktive Portalidentität;
4. die Portalrolle;
5. das erforderliche Lese-, Upload-, Freigabe- oder Administrationsrecht.

Das Portal verwendet die Rollen `employee`, `manager`, `admin` und
`portal_admin`.

- `employee` und `manager` erhalten `can_read` und `can_upload` getrennt pro
  Wissensbereich.
- `manager` besitzt zusätzliche Freigabefunktionen nur für die technisch
  zugeordneten Mitarbeiter oder gültige Vertretungen.
- `admin` besitzt rollenbasierte Portalverwaltungsrechte.
- `portal_admin` verwaltet auch geschützte Rollen und Einstellungen. Mindestens
  ein aktiver Portal-Admin bleibt technisch erzwungen.

Kritische Portalaktionen verlangen eine ausdrückliche Bestätigung im Request
und in der vorgesehenen Oberfläche. Diese Bestätigung ist keine neue Anmeldung
und kein Fresh-Authentication-Schritt.

### Classic Vector administration

Die klassischen Vector-Endpunkte verwenden ein getrenntes Sicherheitsmodell:

1. gültige Open-WebUI-Sitzung;
2. Open-WebUI-Rolle `admin`;
3. zusätzlicher Vector-Freigabecode.

Der Code liegt nicht im Klartext vor. Die Konfiguration verwendet einen
PBKDF2-SHA256-Hash und ein separates Session-Geheimnis. Die Freigabe wird in
einem signierten, benutzergebundenen Cookie gehalten. Fehlversuche werden
begrenzt und zeitweise blockiert.

Portalrollen, Portal-ACLs und ausdrückliche Portalbestätigungen ersetzen den
klassischen Vector-Freigabecode nicht. Umgekehrt erteilt der Vector-Code keine
Portalrolle.

## Secure Document Ingest

Portal-Uploads durchlaufen den bestehenden Secure-Ingest-Pfad:

- Dateityp-, Dateiname-, Größen- und Inhaltsprüfung;
- kontrollierte Pfadauflösung innerhalb des Quarantänespeichers;
- Grenzen für Einträge, unkomprimierte Größe und Kompressionsverhältnis von
  Office-Archiven;
- ClamAV-Prüfung;
- Prompt-Injection-Prüfung;
- dokumentbezogene Konvertierung über den Document Worker;
- persistierte Job- und Fehlerzustände für Wiederholung und Nacharbeit.

Ein Ausfall eines als erforderlich konfigurierten Scanners schlägt geschlossen
fehl. Ungeprüfte Dateien dürfen dadurch nicht stillschweigend veröffentlicht
werden. Originaldatei, aufbereitete Fassung und Veröffentlichungsstatus bleiben
im Portal-Lifecycle getrennt nachvollziehbar.

## Sensitive Data

Sicherheitsrelevante Daten umfassen insbesondere:

- Open-WebUI-Benutzer, Sitzungen, Chats, Uploads und generierte Dateien;
- interne Knowledge-Base- und Portaldateien;
- Rollen, ACLs, Delegationen, Abwesenheiten und Auditereignisse;
- aus Personio synchronisierte Namen, Rollen-, Team-, Standort-, Telefon-,
  Onboarding- und Vorgesetztenfelder, soweit verfügbar und freigegeben;
- Academy-Mitglieds-, Kurs- und Zustandsdaten;
- OAuth-, Provider-, Mail-, internen API- und Backup-Credentials.

Tests, Fehlerberichte und Chat-Ausgaben sollen nur technische Statuswerte,
Fehlercodes, Feldbezeichnungen und datensparsame Summen enthalten. Reale
Mitarbeiterdaten oder Secrets dürfen nicht als Debug-Hilfe ausgegeben oder
gespeichert werden.

Für Personio-Ausgaben gelten zusätzlich Datenminimierung und Zweckbindung. Nur
geschäftliche E-Mail-Adressen mit exakt `@kahle.de` werden indexiert; andere
Adressen bleiben leer, ohne die Auffindbarkeit der Person zu entfernen.
Onboardingdaten werden nur bei ausdrücklich formulierten Onboardingfragen
ausgegeben. Supervisor-Beziehungen werden ausschließlich als stabile
Personio-ID verarbeitet und nicht für Portal- oder Wissensrechte verwendet.

## Data Storage

| Speicher | Sicherheitsrelevante Eigenschaft |
| --- | --- |
| `open-webui`-Volume | enthält Open-WebUI-Datenbank, Uploads und generierte Dateien; ist auch in n8n read/write eingebunden |
| `kb-portal-data` | führende Portal-SQLite-Datenbank, Originale, Markdown, Quarantäne und Upload-Spool |
| `knowledgebases` | klassische interne Wissensquellen und kontrollierte Migrationsquelle |
| `personio_directory_state` | lokale Personio-Synchronisationsdatenbank |
| `academy_provisioner_state` | idempotenter Academy-Provisionierungsstatus |
| `qdrant_data` | abgeleitete Suchindizes, keine führende Quelle |
| `${KAHLE_ROOT}/n8n` | n8n-Konfiguration, Runtime-Datenbank, verschlüsselte Credential-Daten und importierte Workflows |
| `backups` | Ziel für verschlüsselte Portal-Backups |

Die technischen Read-/Write-Modi aller Mounts stehen in
`docs/operations/data-paths.md`. Änderungen an Mounts dürfen nicht allein aus
fachlich angenommener Nutzung abgeleitet werden.

## External Services and Data Egress

| Dienst | Aktuell vorgesehener Datenfluss |
| --- | --- |
| Microsoft Entra | Authentifizierungsdaten für Open WebUI |
| Microsoft Graph | Portal-Mail- und Abwesenheitsfunktionen; der `academy-provisioner` sendet Willkommensmails an freigegebene Nutzer und Zugriffsanfragen mit Name und E-Mail-Adresse des Antragstellers an aktuelle Open-WebUI-Admins |
| IONOS | Prompts, Retrieval-Kontext oder Inhalte für Modell-, Embedding- und Rerank-Aufrufe gemäß aufrufendem Pfad |
| Personio | lesender Abruf freigegebener Mitarbeiterfelder durch `personio-directory` |
| LearningSuite | Name und E-Mail-Adresse freigegebener Benutzer sowie Kursdaten für die Provisionierung; die Kursfreigabe löst eine Kurszugangs-E-Mail mit Login-Link aus |
| SearxNG | Suchanfragen über den vorgesehenen n8n-Websuchpfad |

Neue Egress-Pfade dürfen nicht durch direkte Browseraufrufe oder fachfremde
Servicezugriffe entstehen. Sie gehören in die vorhandene Integration und
benötigen eine Security- und Datenschutzprüfung.

## Secrets and Configuration

`stack/env.production.template` ist die einzige kanonische eingecheckte
Produktionsvorlage. Die reale `stack/.env.production` bleibt unversioniert und
wird auf dem Server geschützt abgelegt.

Secrets dürfen nicht in folgenden Bereichen landen:

- Git oder Beispielkonfigurationen mit echten Werten;
- Frontend-Quelltext oder Browser-Bundles;
- Compose-Ausgaben, Logs, Testberichte oder Chat-Ausgaben;
- n8n-Workflow-Exporte;
- lokale Rollout- oder Übergabeartefakte, die später versehentlich versioniert
  werden könnten.

Produktive Compose-Prüfungen verwenden das dafür vorgesehene Skript mit
`--check-only`. Eine vollständige `docker compose config`-Ausgabe darf wegen
möglicher Secret-Auflösung nicht protokolliert werden.

## Logging and Observability

Die Portal- und klassische Administration schreiben Auditereignisse ohne den
Freigabecode. Worker und Integrationsdienste verwenden technische Fehlercodes
für erwartete Störungen. Insbesondere der Personio-Dienst darf keine rohen
Providerantworten, Namen oder Credentials in Fehlerlogs übernehmen.

Neue Logs müssen auf das betriebliche Minimum begrenzt bleiben. Inhalte aus
Dokumenten, Chats, Personio oder Academy sind keine allgemeinen Debugdaten.

## Security-Sensitive Components

- `stack/kb-admin-api/app/main.py`
- `stack/kb-admin-api/app/portal_governance.py`
- `stack/kb-admin-api/app/secure_ingest.py`
- `stack/kb-admin-api/app/backup_restore.py`
- `stack/open-webui-overrides/open_webui/utils/middleware.py`
- `stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py`
- `stack/open-webui-overrides/open_webui/utils/personio_directory_client.py`
- `stack/personio-directory/app/`
- `stack/academy-provisioner/app/`
- `stack/owui-file-proxy/app/`
- `stack/document-worker/app/`
- `stack/caddy/`
- `stack/docker-compose*.yml`
- `stack/env.production.template`

## Security Invariants

- Portalzugriffe benötigen eine validierte Open-WebUI-Identität, sofern kein
  ausdrücklich lokaler Test-Bypass aktiv ist.
- Domain, aktiver Status, Rolle und erforderliche ACL werden serverseitig
  geprüft.
- `can_read` erteilt nicht automatisch `can_upload`.
- Kritische Portalaktionen behalten ihre ausdrückliche Bestätigung.
- Klassische Vector-Endpunkte behalten Adminrolle und separaten Freigabecode.
- Ein erforderlicher Malware- oder Ingest-Check darf nicht offen fehlschlagen.
- Qdrant ersetzt keine führende Dokument- oder Metadatenquelle.
- Qdrant, ClamAV und SearxNG erhalten keine öffentliche Caddy-Route. Qdrant
  bindet am Host ausschließlich an Loopback; ClamAV und SearxNG werden nur im
  Compose-Netz exponiert.
- Interne API-Keys und Provider-Credentials gelangen nicht in Frontend oder
  Logs.
- Personio bleibt eine lesende Integration.
- Personio ist für aktuelle Mitarbeiterstammdaten autoritativ. RAG darf Namen,
  Rollen, Standorte, Kontaktdaten oder Supervisor-Beziehungen weder ersetzen
  noch ergänzend erfinden.
- Führungskräfte werden nur aus eindeutig auflösbarer Supervisor-Evidenz
  beantwortet. Bei fehlender, unbekannter oder mehrdeutiger Evidenz bleibt die
  Antwort fail-closed.

## Known Risks and Unknowns

- Das Repository belegt lokale Contracts und Konfiguration, aber nicht den
  aktuellen Zustand aller produktiven Identitäten, Secrets, Providerrechte oder
  Netzwerkregeln.
- Open-WebUI-Overrides sind an die gepinnte Upstream-Version gekoppelt. Ein
  Upgrade benötigt Contract-, Security- und Frontend-Prüfungen.
- Mehrere große Integrationsmodule erhöhen die Auswirkung kleiner Änderungen.
- Die parallele klassische und Portal-Administration besitzt unterschiedliche
  Sicherheitsmodelle. Änderungen müssen beide Pfade bewusst getrennt prüfen.
- Qdrant, ClamAV und SearxNG besitzen aktuell keine eigene
  Request-Authentifizierung. Ein Zugriff aus einem kompromittierten Container
  im gemeinsamen `appnet` würde daher nicht durch einen zusätzlichen
  Dienstschlüssel abgefangen.
- n8n besitzt für die bestehenden Retention- und Cleanup-Abläufe
  Schreibzugriff auf Open-WebUI- und Document-Worker-Daten. Ein kompromittierter
  n8n-Container läge damit innerhalb dieser Dateisystem-Trust-Boundary.
- Das lokale Verification-Gate hat keine eingecheckte CI-Ausführung.

## Rules for Coding Agents

- Keine Authentifizierungs-, Rollen-, ACL-, Confirmation- oder Unlock-Prüfung
  entfernen, abschwächen oder in das Frontend verlagern.
- Keine echten Secrets oder personenbezogenen Daten in Tests, Fixtures, Logs
  oder Antworten verwenden.
- Für Security-, Datenmodell-, Integrations- und Infrastrukturänderungen Full
  Verify ausführen und die betroffene Specialized Verification ergänzen.
- Externe Live-Probes nur mit ausdrücklichem Auftrag und datensparsamer Ausgabe
  durchführen.
- Produktionszugriff, Deployment und Rollenänderungen nicht aus lokalem
  Testerfolg ableiten.
