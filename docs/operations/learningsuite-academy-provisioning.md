# LearningSuite Academy Provisionierung

Der Dienst `academy-provisioner` gleicht die OpenWebUI-Datenbank jede Minute lesend ab. Er verarbeitet ausschließlich Nutzer mit der Rolle `user` oder `admin`. Nutzer mit der Rolle `pending` bleiben unberührt.

Für jede geeignete Person legt der Dienst in LearningSuite bei Bedarf einen Account mit E-Mail-Adresse, Vorname und Nachname an. Anschließend schaltet er genau den Kurs `Einführung in die KAHLE-Vinci Nutzung` frei.

Bei der Anlage wird keine allgemeine LearningSuite-Anmelde-E-Mail versendet. Die Kursfreischaltung verschickt dagegen eine einzelne E-Mail inklusive Login-Link. Bereits vorhandene Kurszugänge werden erkannt, damit keine weitere E-Mail ausgelöst wird.

Vor der LearningSuite-Verarbeitung sendet KAHLE-Vinci einmalig eine Willkommensmail über Microsoft Graph. Als Absender wird das vorhandene Postfach aus `VINCI_WELCOME_MAIL_SENDER` verwendet. Der Versandstatus wird pro normalisierter E-Mail-Adresse gespeichert. Erst nach erfolgreichem Versand der Willkommensmail wird der Academy-Zugang verarbeitet, damit die externe Einladung nicht ohne den vorherigen Hinweis auf ihre Echtheit eintrifft.

## Einrichtung auf dem Server

1. Die Datei `/opt/kahle-vinci/stack/.env.production` aus `env.production.template` ergänzen:

   ```dotenv
   LEARNINGSUITE_API_KEY=<LearningSuite-API-Key>
   LEARNINGSUITE_API_BASE_URL=https://api.learningsuite.io/api/v1
   LEARNINGSUITE_COURSE_NAME=Einführung in die KAHLE-Vinci Nutzung
   LEARNINGSUITE_PROVISION_INTERVAL_SECONDS=60
   LEARNINGSUITE_ALLOWED_EMAILS=janssen@kahle.de
   KB_MAIL_TENANT_ID=<Microsoft-Entra-Tenant-ID>
   KB_MAIL_CLIENT_ID=<Microsoft-Graph-App-ID>
   KB_MAIL_CLIENT_SECRET=<Microsoft-Graph-App-Secret>
   VINCI_WELCOME_MAIL_SENDER=oltmanns@kahle.de
   ```

2. Der API-Key bleibt ausschließlich in dieser nicht versionierten Serverdatei. Er darf weder in Logs noch in Tickets oder im Git-Repository stehen.

3. Stack neu bauen und starten:

   ```bash
   cd /opt/kahle-vinci/stack
   docker compose --env-file .env.production -f docker-compose.yml -f docker-compose.prod.yml up -d --build academy-provisioner
   ```

4. Status prüfen:

   ```bash
   docker compose --env-file .env.production -f docker-compose.yml -f docker-compose.prod.yml ps academy-provisioner
   docker compose --env-file .env.production -f docker-compose.yml -f docker-compose.prod.yml logs --tail=100 academy-provisioner
   ```

Der Container besitzt keine veröffentlichten Ports. Er erhält die OpenWebUI-Datenbank ausschließlich als Read-only-Mount; seinen eigenen Fortschritt speichert er im Docker-Volume `academy_provisioner_state`.

## Abnahme

1. Einen Testnutzer in OpenWebUI mit Rollenstatus `pending` anlegen. Es darf kein Academy-Account entstehen.
2. Demselben Nutzer die Rolle `user` geben und maximal eine Minute warten.
3. Prüfen, ob der LearningSuite-Account mit Microsoft-E-Mail, Vor- und Nachnamen existiert und der Kurs freigeschaltet ist.
4. Prüfen, ob zuerst genau eine KAHLE-Vinci-Willkommensmail von `oltmanns@kahle.de` angekommen ist.
5. Prüfen, ob danach genau eine Kursfreischaltungs-E-Mail mit Login-Link angekommen ist.
6. Den Worker noch einmal laufen lassen. Es darf keine der beiden E-Mails erneut versendet werden.

Während der Abnahme verarbeitet `LEARNINGSUITE_ALLOWED_EMAILS` ausschließlich die dort aufgeführten, komma- oder semikolongetrennten E-Mail-Adressen. Eine fehlende oder leere Einstellung stoppt den Dienst sicher. Nach erfolgreicher Abnahme wird die Variable einmalig auf `*` gesetzt. Ab diesem Zeitpunkt werden alle freigegebenen Nutzer mit der Rolle `user` oder `admin` automatisch verarbeitet.

Fehler einzelner Nutzer werden im Statusspeicher festgehalten und beim nächsten Durchlauf erneut versucht. Pro Durchlauf werden höchstens 20 noch nicht abgeschlossene Nutzer verarbeitet. Damit bleibt der Dienst auch bei einer Erstfreischaltung klar unter dem LearningSuite-Limit von 120 API-Aufrufen pro Minute. Ein nicht gefundener oder mehrfach gefundener Kursname stoppt den Durchlauf ohne eine Teilfreischaltung. Deaktivierungen, Löschungen und nachträgliche Profiländerungen werden bewusst noch nicht synchronisiert.
