# KAHLE-Vinci: verschlüsselte Backups und Restore

## Sicherungsumfang

Das Nachtbackup stoppt den Compose-Stack kurz und sichert konsistent:

- Open-WebUI-Datenvolume
- Qdrant-Datenvolume
- Document-Worker-Datenvolume
- `/opt/kahle-vinci` einschließlich n8n, Knowledgebases, Assets und Konfiguration

Die vier Archive werden technisch geprüft, mit SHA-256 manifestiert und anschließend mit dem age-Empfängerschlüssel verschlüsselt. Nur die verschlüsselte Datei verbleibt dauerhaft. Standardaufbewahrung: 21 Tage.

## Schlüsselverwahrung

Der private age-Schlüssel bleibt ausschließlich auf administrativen Arbeitsplätzen bzw. in einem freigegebenen Passwortmanager/Offline-Tresor. Er darf niemals auf den Server kopiert werden. Der Server benötigt nur den öffentlichen `age1...`-Empfängerschlüssel in `/etc/kahle-vinci/backup-recipient.txt`.

Ohne privaten Schlüssel sind die Backups absichtlich nicht wiederherstellbar. Mindestens eine zweite, geschützte Kopie des privaten Schlüssels ist daher Pflicht.

## Betriebsprüfung

```bash
sudo systemctl status kahle-vinci-backup.timer --no-pager
sudo systemctl list-timers kahle-vinci-backup.timer --all
sudo cat /var/lib/kahle-vinci-backup/last-success
sudo journalctl -u kahle-vinci-backup.service -n 100 --no-pager
sudo ls -lh /var/backups/kahle-vinci/encrypted
```

Ein manueller Lauf verursacht eine kurze Unterbrechung:

```bash
sudo systemctl start kahle-vinci-backup.service
sudo systemctl status kahle-vinci-backup.service --no-pager
```

## Nicht-destruktiver Restore-Lesetest auf Windows

1. Verschlüsselte Datei und `.sha256`-Datei herunterladen.
2. Äußere SHA-256-Prüfsumme vergleichen.
3. Mit dem privaten age-Schlüssel in ein temporäres Verzeichnis entschlüsseln.
4. `SHA256SUMS.txt` innerhalb des Backups prüfen und jedes `tar.gz` testweise lesen.
5. Temporäre entschlüsselte Daten sicher entfernen.

Der bereits ausgeführte Referenztest endete mit `RESTORE-LESETEST: OK`.

## Tatsächliche Wiederherstellung

Eine echte Wiederherstellung überschreibt Produktionsdaten und erfolgt nur in einem angekündigten Wartungsfenster:

1. Fehlerzustand dokumentieren und vorhandene Daten zusätzlich sichern.
2. Stack stoppen.
3. Gewünschtes Backup entschlüsseln und alle inneren Prüfsummen prüfen.
4. Volume- und Projektdaten mit numerischen Eigentümern, ACLs und Extended Attributes wiederherstellen.
5. Stack starten und Healthchecks, Datenbank, Benutzer, Chats, Modelle, RAG, Dateierstellung, n8n und Downloads testen.
6. Ergebnis und verwendete Backup-Prüfsumme protokollieren.

Die destruktiven Restore-Befehle werden bewusst nicht als unbeaufsichtigtes Standardskript bereitgestellt. Sie müssen an den konkreten Schaden und das gewählte Backup angepasst und vor Ausführung gegengeprüft werden.