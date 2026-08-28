# KAHLE-Vinci Wissensportal – Betrieb und Administration

## Lokale Schulungsaccounts

Für Bildschirmaufnahmen können zwei ausschließlich lokale Konten reproduzierbar angelegt werden. Zuerst muss der lokale Stack laufen. Danach im Projektstamm ausführen:

```powershell
.\scripts\setup-local-training-accounts.ps1
```

Der Befehl legt einen Benutzer und eine Führungskraft an, ordnet den Benutzer der Führungskraft zu und gibt beiden Konten Lese- und Uploadrechte für alle aktiven Wissensbereiche. Ein erneuter Aufruf setzt Namen, Passwörter, Rollen und Rechte auf den definierten Schulungsstand zurück. Das Skript bricht ab, wenn OpenWebUI nicht als erwartete lokale Instanz auf `127.0.0.1:3001` läuft.

Standardzugänge:

| Rolle | E-Mail | Passwort |
|---|---|---|
| Benutzer | `mitarbeiter.schulung@kahle.de` | `Vinci-Mitarbeiter-2026!` |
| Führungskraft | `fuehrungskraft.schulung@kahle.de` | `Vinci-Fuehrung-2026!` |

Die Werte können bei Bedarf als Parameter überschrieben werden. Die Schulungskonten sind nicht für Produktion vorgesehen.

Stand: 6. August 2026. Diese Anleitung beschreibt den lokalen Abnahmebetrieb. Eine Aktivierung auf dem Produktionsserver ist erst nach bestandenem Go-live-Gate zulässig.

## 1. Rollen und Verantwortungen

- Mitarbeiter laden Dokumente nur in freigegebene Wissensbereiche, prüfen Treffer und wählen die gewünschte Aktion.
- Führungskräfte prüfen Uploads für KAHLE-Allgemein, fachlich auffällige Dokumente und die erste Stufe kritischer Fälle ihrer zugeordneten Mitarbeiter. Sie können unklare Fälle an einen Admin weiterleiten.
- Admins bearbeiten Freigaben, Qualitätsfälle, Benutzerzuordnungen und Knowledge Bases. Änderungen an Knowledge Bases benötigen die Freigabe eines Portal-Admins.
- Portal-Admins besitzen sämtliche Rechte und dürfen Knowledge-Base- sowie Adminänderungen direkt ausführen. Kritische Rollen- und Knowledge-Base-Änderungen verlangen die im Portal angezeigte ausdrückliche Bestätigung.

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

Der normale Weg lautet: Upload → Sicherheits- und Prompt-Injection-Prüfung → Document-Worker-Konvertierung → globale Dubletten-, Versions-, Ähnlichkeits- und Widerspruchsprüfung → Auswahl durch Mitarbeiter → automatische Zuordnung der Freigabestufe → atomare Indexaktivierung nach Erfüllung dieser Stufe.

- Sauberes Dokument für genau eine Bereichs-Knowledgebase: direkte Aktivierung ohne menschliche Freigabe.
- KAHLE-Allgemein, Dublette, Versionskandidat oder unklare Dokumentenpriorität: Freigabe durch die Führungskraft.
- Widerspruch, kritischer Sicherheitsbefund, kritischer Prompt-Injection-Treffer, Veröffentlichung in mehreren Wissensbereichen, unsichere Konvertierung oder sonstiger kritischer Fall: zuerst Führungskraft, anschließend Admin oder Portal-Admin.

Abweichungen:

- Exakte Dubletten werden blockiert.
- Ein Knowledgebase-übergreifender Ähnlichkeitstreffer allein verlangt die Führungskraftprüfung. Erst eine Veröffentlichung in mehreren Wissensbereichen oder ein fachlicher Widerspruch verlangt zusätzlich die Adminfreigabe.
- Malware, ausführbare Schadbestandteile und technisch nicht sicher prüfbare Dateien bleiben ohne Override-Möglichkeit in Quarantäne. Kritische Inhalts- oder Prompt-Injection-Befunde in technisch sicher untersuchten Dateien durchlaufen Führungskraft und Admin.
- Schlägt der Neuindex nach einer Freigabe fehl, wird die vorherige aktive Version wiederhergestellt.
- Der Retrieval-Filter akzeptiert ausschließlich aktive Versions-IDs, die der Portal-API für den angemeldeten Nutzer freigibt. Ein veralteter Index allein kann deshalb keine gesperrte Version ausliefern.

## 4. Ablauf, Verlängerung und Entfernung

- Gültigkeit: höchstens 60 Arbeitstage.
- Sammelerinnerungen: 7 Arbeitstage vorher an den Owner, 5 Arbeitstage vorher zusätzlich an die Führungskraft, 1 Arbeitstag vorher zusätzlich an Admins und Portal-Admins.
- Verlängerungen benötigen die Bestätigung des Owners, anschließend die Führungskraft und einen Admin.
- Abgelaufene Dokumente werden deaktiviert und aus dem aktiven Retrievalumfang entfernt.
- Entfernte Dokumente bleiben im Papierkorb. Ab Tag 30 erhält der Admin einen Löschauftrag, danach alle 10 Tage eine Erinnerung. Drei Tage vor Tag 90 folgt die letzte Warnung. An Tag 90 wird ohne Legal Hold physisch gelöscht.
- Beim Verschieben in den Papierkorb erhalten alle aktiven Nutzer mit bisherigem Lesezugriff eine Portal-Mitteilung und eine E-Mail. Der Empfängerkreis wird vor dem Entzug der Veröffentlichung ermittelt.
- Eine Wiederherstellung ist nur mit gültiger, bereits genehmigter Version möglich. Andernfalls ist eine neue Freigabe erforderlich.

## 5. Knowledge Bases und Benutzer

Benutzer stammen aus OpenWebUI und werden anhand ihrer stabilen Benutzer-ID sowie Microsoft-E-Mail synchronisiert. Führungskräfte, Vertretungen, Rollen und getrennte Lese-/Uploadrechte werden im Portal manuell verwaltet.

Normale Admins können Änderungen an Knowledge Bases vorbereiten. Anlegen, Umbenennen, Archivieren oder endgültiges Entfernen wird erst nach Portal-Admin-Freigabe wirksam. Portal-Admins können diese Aktionen nach ausdrücklicher Bestätigung direkt ausführen.

Bei Archivierung oder endgültiger Entfernung einer Knowledge Base werden alle aktiven Nutzer mit bisherigem Leserecht sowie Admins und Portal-Admins über Portal und E-Mail informiert.

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

## 7. Freigabewarteschlange

Aktivierung und Hybridindexwechsel werden global über die persistente Tabelle `decision_jobs` serialisiert. Gleichzeitig eingehende Entscheidungen verschiedener Nutzer bleiben erhalten und werden in Eingangsreihenfolge verarbeitet. Sobald die Entscheidung dauerhaft gespeichert ist, bestätigt das Portal sie sofort und verschiebt den Vorgang sichtbar nach „Veröffentlichung läuft“; der Nutzer kann weiterarbeiten und erhält nach Abschluss eine Mitteilung.

Im Tagesbetrieb synchronisiert `kb-sync` ausschließlich das betroffene Dokument. Neue Chunks werden zunächst mit `published=false` geschrieben, die alte Version wird ausgeblendet und erst danach wird die neue Version freigeschaltet. Schlägt dieser Wechsel fehl, wird die alte Version wieder sichtbar. Ein kompletter Neuaufbau aller Dokumente ist nur für die einmalige Schema-Migration, Restore, Modell-/Chunking-Wechsel oder eine ausdrücklich gestartete Wartung vorgesehen.

Ein aktiver Verarbeitungsschritt besitzt eine zeitlich begrenzte Lease. Läuft diese nach einem Prozessabbruch ab, kann der Job beim nächsten Worker-Lauf erneut übernommen werden. Bei einer auffällig lange stehenden Warteschlange sind API- und Sync-Erreichbarkeit, der letzte `decision_queue`-Incident und der Status der Jobs zu prüfen; Jobs dürfen nicht manuell aus der SQLite-Datenbank gelöscht oder auf `completed` gesetzt werden.

## 8. Lokale technische Abnahme

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

## 9. Go-live-Sperre

Kein Produktionsrollout bei:

- einem unberechtigten Retrieval- oder Quellenzugriff;
- aktiven abgelaufenen, gelöschten oder ungeprüften Dokumenten;
- offenen kritischen/hohen Sicherheitsbefunden;
- nicht bestandenem Restore oder Indexneuaufbau;
- weniger als 90 Prozent korrekten Dokumenttreffern oder weniger als 95 Prozent korrekten Originalquellen;
- nicht abgeschlossenen kritischen E2E-Szenarien.

Der lokale Abschluss ist keine automatische Produktionsfreigabe. Der Produktionswechsel benötigt ein aktuelles Backup, einen geprüften Restore, einen dokumentierten Rollback und anschließende Smoke-Tests.
