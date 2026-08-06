# KAHLE-Vinci Wissensportal – Betrieb und Administration

Stand: 6. August 2026. Diese Anleitung beschreibt den lokalen Abnahmebetrieb. Eine Aktivierung auf dem Produktionsserver ist erst nach bestandenem Go-live-Gate zulässig.

## 1. Rollen und Verantwortungen

- Mitarbeiter laden Dokumente nur in freigegebene Wissensbereiche, prüfen Treffer und wählen die gewünschte Aktion.
- Führungskräfte prüfen Inhalt, erkannte Ähnlichkeiten und die vorgeschlagene Aktion ihrer zugeordneten Mitarbeiter. Sie können unklare Fälle an einen Admin weiterleiten.
- Admins bearbeiten Freigaben, Qualitätsfälle, Benutzerzuordnungen und Knowledge Bases. Änderungen an Knowledge Bases benötigen die Freigabe eines Portal-Admins.
- Portal-Admins besitzen sämtliche Rechte und dürfen Knowledge-Base- sowie Adminänderungen direkt ausführen. Kritische Aktionen verlangen eine frische Microsoft-Anmeldung.

Mindestens ein aktiver Portal-Admin bleibt technisch erzwungen. Deaktivierte Nutzer erhalten keinen Portal- oder Quellenzugriff.

## 2. Täglicher Betrieb

Im Qualitätsdashboard sind mindestens diese Punkte zu prüfen:

1. offene Systemincidents und Wissensfehler;
2. ausstehende Freigaben und Konflikte;
3. Dokumente mit bevorstehendem Ablauf;
4. fehlgeschlagene E-Mails;
5. Status des Hybridindex;
6. letztes Backup und letzter isolierter Restore-Test.

Systemfehler werden automatisch als Incident angelegt und per E-Mail gemeldet. Nutzer können eine sichtbare Fehlermeldung zusätzlich an einen Admin senden. Inhalte, Antworten oder Dokumenttexte werden nicht unkontrolliert in technische Fehlermails übernommen.

## 3. Dokumentfreigabe

Der normale Weg lautet: Upload → Sicherheits- und Prompt-Injection-Prüfung → Document-Worker-Konvertierung → globale Dubletten-, Versions-, Ähnlichkeits- und Widerspruchsprüfung → Auswahl durch Mitarbeiter → Freigabe durch Führungskraft → Freigabe durch Admin → atomare Indexaktivierung.

Abweichungen:

- Exakte Dubletten werden blockiert.
- Knowledge-Base-übergreifende Treffer und Widersprüche gehen direkt an einen Admin.
- Prompt-Injection- oder Malwaretreffer bleiben in Quarantäne.
- Schlägt der Neuindex nach einer Freigabe fehl, wird die vorherige aktive Version wiederhergestellt.
- Der Retrieval-Filter akzeptiert ausschließlich aktive Versions-IDs, die der Portal-API für den angemeldeten Nutzer freigibt. Ein veralteter Index allein kann deshalb keine gesperrte Version ausliefern.

## 4. Ablauf, Verlängerung und Entfernung

- Gültigkeit: höchstens 60 Arbeitstage.
- Sammelerinnerungen: 15 und 10 Arbeitstage vorher an den Owner, 5 Arbeitstage vorher zusätzlich an die Führungskraft, 1 Arbeitstag vorher zusätzlich an Admins.
- Verlängerungen benötigen die Bestätigung des Owners, anschließend die Führungskraft und einen Admin.
- Abgelaufene Dokumente werden deaktiviert und aus dem aktiven Retrievalumfang entfernt.
- Entfernte Dokumente bleiben im Papierkorb. Ab Tag 30 erhält der Admin einen Löschauftrag, danach alle 10 Tage eine Erinnerung. Drei Tage vor Tag 90 folgt die letzte Warnung. An Tag 90 wird ohne Legal Hold physisch gelöscht.
- Eine Wiederherstellung ist nur mit gültiger, bereits genehmigter Version möglich. Andernfalls ist eine neue Freigabe erforderlich.

## 5. Knowledge Bases und Benutzer

Benutzer stammen aus OpenWebUI und werden anhand ihrer stabilen Benutzer-ID sowie Microsoft-E-Mail synchronisiert. Führungskräfte, Vertretungen, Rollen und getrennte Lese-/Uploadrechte werden im Portal manuell verwaltet.

Normale Admins können Änderungen an Knowledge Bases vorbereiten. Anlegen, Umbenennen, Archivieren oder endgültiges Entfernen wird erst nach Portal-Admin-Freigabe wirksam. Portal-Admins können diese Aktionen nach Microsoft-Step-up direkt ausführen.

## 6. Backup und Wiederherstellung

Das neue Portal sichert die kanonische SQLite-Datenbank und alle Original-/Markdown-Dateien verschlüsselt mit AES-256-GCM. Das Backup wird zusätzlich an einen getrennten Speicherort kopiert. Der operative Backupdienst läuft über das Compose-Profil `operations`.

Erforderliche Konfiguration:

```text
KB_BACKUP_ENCRYPTION_KEY=<32-Byte-Schlüssel, base64 oder hex>
KAHLE_BACKUP_SECONDARY_ROOT=<physisch getrennter Zielpfad>
```

Ein Restore erfolgt immer in ein leeres, isoliertes Ziel. Der Restore prüft vor der Freigabe:

- verschlüsselte Integrität und Manifest-Hashes;
- sichere Pfade ohne Traversal oder symbolische Links;
- SQLite-Integrität;
- Vorhandensein aller aktiven RAG-Markdowns.

Danach wird der Hybridindex vollständig aus den wiederhergestellten Quelldaten neu aufgebaut. Ein Backup oder Restore-Test mit Fehler erzeugt automatisch einen Admin-Incident. Produktive Daten dürfen niemals probeweise über eine laufende Instanz zurückgespielt werden.

## 7. Lokale technische Abnahme

Die automatisierten Prüfungen werden aus dem Repository-Stamm ausgeführt:

```powershell
docker build -t kahle-kb-admin-api-prd-test stack/kb-admin-api
docker run --rm -v C:/kahle-vinci/stack/kb-admin-api/tests:/app/tests:ro kahle-kb-admin-api-prd-test sh -c "pip install --quiet pytest && python -m pytest -q /app/tests"

docker build -t kahle-kb-sync-prd-test stack/kb-sync
docker run --rm -v C:/kahle-vinci/stack/kb-sync/tests:/app/tests:ro kahle-kb-sync-prd-test sh -c "pip install --quiet pytest && python -m pytest -q /app/tests"

Set-Location admin-dashboard
npm test
```

Zusätzlich sind die 20 Abnahmeszenarien des PRDs, die Retrieval-Evaluation unter `eval/rag` und ein isolierter Restore mit vollständigem Neuindex auszuführen. Die Ergebnisse werden mit Datum, Commit, Testdaten und Konfiguration protokolliert.

## 8. Go-live-Sperre

Kein Produktionsrollout bei:

- einem unberechtigten Retrieval- oder Quellenzugriff;
- aktiven abgelaufenen, gelöschten oder ungeprüften Dokumenten;
- offenen kritischen/hohen Sicherheitsbefunden;
- nicht bestandenem Restore oder Indexneuaufbau;
- weniger als 90 Prozent korrekten Dokumenttreffern oder weniger als 95 Prozent korrekten Originalquellen;
- nicht abgeschlossenen kritischen E2E-Szenarien.

Der lokale Abschluss ist keine automatische Produktionsfreigabe. Der Produktionswechsel benötigt ein aktuelles Backup, einen geprüften Restore, einen dokumentierten Rollback und anschließende Smoke-Tests.
