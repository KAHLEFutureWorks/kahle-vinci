# Retrieval-Metadaten im Wissensportal betreiben

Stand: 25. August 2026

## Zweck und Speicherort

Das Wissensportal klassifiziert jede Dokumentversion zusätzlich nach Fachdomäne,
Dokumentart, Themen und Evidenzfähigkeit. Diese Angaben stehen ausschließlich in
der Portal-Datenbank in `document_retrieval_metadata`. Explizite Beziehungen
stehen mit ihrem wörtlichen Beleg in `document_evidence_relations`.

Die hochgeladene Originaldatei und `rag.md` werden für diese Klassifikation nicht
verändert. `content_sha256` dokumentiert, für welchen unveränderten Inhalt die
Klassifikation erzeugt wurde. Die Metadaten werden erst beim Indexieren als
Qdrant-Payload an jeden Chunk angehängt.

## Automatischer Bestands-Backfill

Beim Start von `kb-admin-api` wird ein idempotenter Backfill ausgeführt. Er liest
alle nicht gelöschten Portalversionen, klassifiziert vorhandene `rag.md`-Dateien
und schreibt nur die Sidecar-Tabellen. Der technische Ergebniszähler steht in
`RETRIEVAL_METADATA_BACKFILL` und enthält ausschließlich:

- `classified`
- `unchanged`
- `missing_files`

Dokumenttext, Namen und Evidenzspannen werden nicht protokolliert. Ein zweiter
Lauf mit derselben Klassifikationsversion und derselben Prüfsumme zählt die
Version unter `unchanged`.

Vor der ersten Aktivierung kann derselbe Lauf ohne Klassifikationsschreibzugriff
geprüft werden. Die Ausgabe enthält nur die drei Zähler:

```powershell
docker compose -f stack/docker-compose.yml -f stack/docker-compose.kahle-ui.yml -f stack/docker-compose.local-edge.yml exec -T kb-admin-api python -c "import os; from app.retrieval_metadata import RetrievalMetadataStore; print(RetrievalMetadataStore(os.environ['KB_PORTAL_DB_PATH']).backfill(os.environ['KB_PORTAL_FILES_ROOT'],dry_run=True))"
```

## Vertrauensstufen

- `inferred`: eindeutige deterministische Klassifikation mit hoher Konfidenz;
  sie darf vor dem Reranking als Filter wirken.
- `review_required`: uneindeutiger Inhalt; die Metadaten bleiben sichtbar,
  wirken aber nicht als harter Ausschluss.
- `confirmed`: durch Portal-Admin fachlich bestätigt; Konfidenz `1.0`.

Offene Prüfungen sind für Portal-Admins über
`GET /portal/admin/retrieval-metadata/review` abrufbar. Die Antwort enthält keine
Dokumenttexte. Bestätigt wird eine Version mit
`PUT /portal/admin/retrieval-metadata/{version_id}/confirm`. Kontrollierte Werte
für Domäne, Dokumentart, Themen und Evidenzfähigkeiten sind im Request nötig.
Eine Beziehung kann nicht bestätigt werden, wenn kein einzelner gespeicherter
`evidence_span` sie ausdrücklich belegt.

## Erstmalige lokale Aktivierung

Nach dem ersten Start müssen die aktiven Dokumente einmal vollständig neu
indexiert werden, damit alle bestehenden Qdrant-Punkte die neuen Payload-Felder
tragen:

```powershell
$composeArgs = @(
  '-f', 'stack/docker-compose.yml',
  '-f', 'stack/docker-compose.kahle-ui.yml',
  '-f', 'stack/docker-compose.local-edge.yml'
)

docker compose @composeArgs up -d --build kb-admin-api kb-sync open-webui
docker compose @composeArgs exec -T kb-admin-api python -c "import os,requests; r=requests.post('http://kb-sync:8093/reindex-all',headers={'X-API-Key':os.environ['KB_SYNC_INTERNAL_API_KEY']},timeout=300); print({'status_code':r.status_code,'ok':bool(r.json().get('ok'))})"
```

Die tatsächliche Neuindexierung wird über den vorhandenen administrativen
`reindex-all`-Wartungspfad gestartet. Währenddessen bleiben ACL, aktive Version,
Veröffentlichungsstatus und Gültigkeit unverändert harte Filter. Ein leerer
Staging-Index wird nicht aktiviert.

## Abnahme

1. Eine reine Systemübersicht bestätigt die Existenz eines Systems, aber keine
   Bedienungsanleitung.
2. Eine echte Arbeitsanweisung trägt `procedure`.
3. Software-Release-Unterlagen erfüllen keinen fachlichen Freigabeablauf einer
   Arbeitsanweisung.
4. Getrennte Person- und Systemmentions erzeugen keine Beziehung.
5. Eine ausdrückliche Zuständigkeit enthält genau einen wörtlichen
   `evidence_span`.
6. Claim-IDs sind eindeutig und jede Claim-Quellen-ID existiert im selben
   EvidenceBundle.
7. Dieselbe Frage erzeugt bei allen Vinci-Modellen denselben RetrievalPlan.

## Rollback

Ein Rollback der neuen Retrievalsteuerung benötigt keine Änderung an
Originaldateien. Vor einem Rollout wird die Portal-SQLite-Datei gesichert. Bei
einem Rückbau können die neuen Payloadfilter deaktiviert und der vorherige
Indexstand wieder aktiviert werden. Die additiven Sidecar-Tabellen können bis
zur Ursachenanalyse bestehen bleiben; sie verändern den Dokumentlebenszyklus
nicht.
