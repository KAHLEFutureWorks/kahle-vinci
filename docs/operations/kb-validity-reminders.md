# Knowledgebase-Gültigkeitserinnerungen

## Ziel

Die erste Ausbaustufe benötigt weder Microsoft Graph noch einen externen
Benachrichtigungsdienst. Ein täglicher n8n-Lauf synchronisiert persönliche
Wissenspflege-Aufgaben für alle Open-WebUI-Nutzer mit der Rolle `admin`.
Der Lauf startet täglich um 10:30 Uhr in der Zeitzone `Europe/Berlin`.

Beim ersten Chat des Tages sieht jeder betroffene Admin zusätzlich einen
kompakten Hinweis. Die Details sind über „Zeige meine offenen Aufgaben“
abrufbar.

## Unterstützte Gültigkeitsangaben

Bevorzugt wird YAML-Frontmatter in Markdown-Dateien:

```yaml
---
title: Öffnungszeiten Hannover
document_id: KB-LOC-HAN-OEFFNUNGSZEITEN
owner_name: Standortleitung Hannover
owner_email: hannover@kahle.de
status: active
valid_until: 2026-12-31
notify_before_days: 14
rag_index: true
---
```

Für PDF-, DOCX-, TXT- und CSV-Dateien sowie für die Übergangszeit wird auch
ein Datum im Dateinamen erkannt:

```text
Preisliste_gueltig-bis_2026-12-31.pdf
Preisliste_gültig bis 31.12.2026.pdf
```

Dateien ohne Gültigkeitsangabe lösen keine Aufgabe aus. Dateien mit
`rag_index: false` oder einem Status wie `draft`, `inactive` oder `archived`
werden ignoriert.

## Verhalten

- Standardvorlauf: 14 Tage.
- Bis sieben Tage vor Ablauf: Priorität `high`.
- Am Ablaufdatum und danach: Priorität `urgent`.
- Pro Admin und Dokument existiert höchstens eine Systemaufgabe.
- Solange die Datei nicht aktualisiert wurde, wird eine erledigte Aufgabe beim
  nächsten Lauf wieder geöffnet.
- Wird die Gültigkeit verlängert oder die Datei aus dem RAG genommen, wird die
  offene Systemaufgabe auf `cancelled` gesetzt.
- Dateien werden niemals automatisch gelöscht oder aus dem RAG entfernt.

## Technische Komponenten

- Scanner und Task-Synchronisierung:
  `stack/owui-file-proxy/app/kb_expiry.py`
- Geschützter interner Endpoint:
  `POST /maintenance/kb_expiry_sync`
- n8n-Workflow:
  `n8n/workflows/knowledgebase/kb-validity-reminders.json`
- Open-WebUI-Tageshinweis:
  `stack/open-webui-functions/kahle_toolcall_guard.py`

Der File-Proxy erhält die Knowledgebases ausschließlich read-only. Er schreibt
nur in die separate KAHLE-Tasks-Datenbank im bestehenden Open-WebUI-Volume.
Die Open-WebUI-Hauptdatenbank wird nur lesend verwendet, um Admin-Nutzer zu
ermitteln.

## Rollout

1. Änderungen auf den Server nach `/opt/kahle-vinci` übertragen.
2. Vorhandenes verschlüsseltes Backup prüfen.
3. File-Proxy neu bauen und starten.
4. Open-WebUI-Tools und Funktionen mit
   `scripts/openwebui/register-kahle-workflow-tool.py` aktualisieren.
5. Workflow in n8n importieren und zunächst deaktiviert lassen.
6. Eine Testdatei mit einem Ablaufdatum innerhalb der nächsten 14 Tage anlegen.
7. Endpoint zuerst im Dry-Run ausführen:

   ```bash
   curl -sS \
     -H "Authorization: Bearer <OWUI_FILE_PROXY_API_KEY>" \
     -H "Content-Type: application/json" \
     -d '{"dry_run":true}' \
     http://127.0.0.1:8091/maintenance/kb_expiry_sync
   ```

8. Danach einmal mit `{"dry_run":false}` ausführen und im Admin-Konto
   „Zeige meine offenen Aufgaben“ testen.
9. Erst nach erfolgreichem Test den n8n-Workflow aktivieren.

## Spätere optionale Kanäle

Der Endpoint liefert eine strukturierte Liste der ablaufenden Dokumente.
Später kann derselbe n8n-Workflow ohne Änderung am Scanner zusätzlich
E-Mail, einen Teams-Webhook oder einen selbst gehosteten Push-Dienst wie ntfy
bedienen.
