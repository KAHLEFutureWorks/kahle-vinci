# Task 7 report — Parallele Retrievalausführung in OpenWebUI

## Implementierung

- Ein interner `PersonioDirectoryClient` sendet ausschließlich Query,
  Directory-Unterintent sowie gebundene OpenWebUI-Nutzer-ID und -Rolle an
  `POST /internal/search`. Der Client verwendet einen kurzen Timeout,
  akzeptiert nur das freigegebene Antwortschema und gibt bei HTTP-, Timeout-
  oder Schemafehlern ausschließlich `directory_unavailable` ohne Payload- oder
  Credential-Logging zurück.
- Die Middleware plant den Retrievalpfad vor dem ersten Adapteraufruf. Reine
  Personenfragen rufen genau einmal Personio und niemals RAG auf. Reine
  Wissensfragen behalten den vorhandenen RAG-Pfad. Echte Mischfragen starten
  Personio und RAG über `asyncio.gather` gleichzeitig.
- Die reale Ausführung wird als `kahle_retrieval_tools` und im bestehenden
  Harness-Metrikfeld `tool_called` beobachtbar. Zusammengeführte Entscheidungen
  enthalten Personio-Quellen als `P`-IDs und Dokumentquellen als `R`-IDs.
- `pending` ruft keinen der beiden Backends auf. Der Zugriffszustand sperrt
  zusätzlich den späteren nativen beziehungsweise Outlet-RAG-Fallback.
- Reine Personio-Anfragen bleiben bei leerem Treffer oder Ausfall geschlossen
  und erhalten die stabile Verzeichnisantwort. Bei einer echten Mischfrage kann
  der unabhängig belegte RAG-Teil weiterhin als partielle Evidenz verwendet
  werden.
- Native RAG-Quellen, Feedback-Link, AnswerContract, Streaming-Timeout und
  bestehende Retry-/Fallback-Grenzen bleiben erhalten. Der Outlet-Guard erkennt
  jetzt auch Personio-only-Harnessantworten als abschließend verarbeitet.
- OpenWebUI erhält ausschließlich URL und internen API-Key des Verzeichnisdiensts,
  den schreibgeschützten Client-Mount und eine reine Start-Abhängigkeit. Ein
  nicht verfügbarer Verzeichnisdienst blockiert deshalb weder OpenWebUI noch
  den unabhängigen RAG-Pfad. Personio-Credentials verbleiben ausschließlich im
  `personio-directory`-Dienst.

## Reviewkorrektur

- Der reale Middleware-Einstieg plant Personen- und Mischfragen jetzt vor dem
  engeren Legacy-RAG-Gate. Damit erreichen auch Formulierungen wie „Wo arbeitet
  …?“ und „Was hat … mit VSX zu tun?“ zuverlässig den vorgesehenen Retrievalpfad.
- Der Standard- und Produktions-Compose aktiviert den Harness. Ein explizites
  `KAHLE_KNOWLEDGE_HARNESS_MODE=off` bleibt als Not-Aus erhalten und lässt den
  vorhandenen Legacy-RAG-Pfad unangetastet.
- Persistente technische Harness-Metadaten enthalten ausschließlich Werkzeug-
  und Evidenzstatus, kontrollierte Quellen-IDs und -Arten, boolesche
  Validierungsfelder sowie `stale` und den geprüften Sync-Zeitpunkt. Query,
  Claims, Namen, E-Mail-Adressen und Telefonnummern bleiben ausschließlich im
  flüchtigen Request-Kontext.
- `sync_completed_at` und `stale` bleiben beim Zusammenführen von Personio- und
  RAG-Evidenz erhalten und werden dem AnswerContract samt ausdrücklicher
  Veraltet-Kennzeichnung übergeben. Ungeprüfte Zeitstempel werden bereits am
  Client-Rand verworfen.

## Testgetriebene Nachweise

- Reine Personenfrage: ein Personio-Aufruf, null RAG-Aufrufe, stabiler
  `not_found`-Pfad.
- `pending`: null Personio- und null RAG-Aufrufe.
- Mischfrage: beide Async-Fakes starten vor Freigabe ihrer Gates; das
  EvidenceBundle enthält `P1` und `R1` in stabiler Reihenfolge.
- Interner Client: gebundener Nutzerkontext und API-Key-Header, kontrollierte
  Antwortvalidierung, Ablehnung unbekannter beziehungsweise privater Claim-
  Felder.
- Outlet: aktive Personio-only-Antworten lösen keinen nachträglichen RAG-Aufruf
  aus.
- Compose: interner Client-Mount, keine Personio-Credentials in OpenWebUI und
  gerenderte Standard-/Produktionskonfiguration mit aktivem Harness,
  funktionsfähigem `off`-Schalter und `service_started`-Abhängigkeit.
- Reale Middleware-Steuerung: Personen- und Mischfragen umgehen korrekt das
  engere Legacy-RAG-Gate; `off` verhindert Personio-Aufrufe, ohne Legacy-RAG zu
  deaktivieren.
- Metadaten-Negativtest: keine Query, Claims, Namen, Nutzer-ID oder
  Dokumenttitel/-URL im technischen Summary; vollständige Evidenz bleibt für
  die Antwortvalidierung flüchtig verfügbar.
- Freshness: Sync-Zeitpunkt und `stale` überstehen Merge und Decision-Aufbau und
  erreichen die Antwortanweisung.

## Verifikation

```text
C:\kahle-vinci\.venv-test\Scripts\python.exe -m pytest \
  stack/tests/test_middleware_internal_rag_routing.py \
  stack/tests/test_kahle_knowledge_harness.py \
  stack/tests/test_personio_directory_contracts.py \
  stack/tests/test_kahle_toolcall_guard.py -q -p no:cacheprovider
158 passed

C:\kahle-vinci\.venv-test\Scripts\python.exe -m pytest \
  stack/tests -q -p no:cacheprovider
417 passed

C:\kahle-vinci\.venv-test\Scripts\python.exe stack/tests/compose_static_check.py
Compose static check passed.

python -m py_compile (Client, Middleware und Outlet-Guard)
exit 0

git diff --check
exit 0
```

Es wurden keine echten Personio-Credentials, keine Windows-Umgebungsvariablen
und keine Live-API verwendet oder ausgelesen.
