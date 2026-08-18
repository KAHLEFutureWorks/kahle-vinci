# Learningsuite: automatisches Academy-Provisioning aus OpenWebUI

Stand: 17. August 2026. Grundlage ist ausschließlich die offizielle [LearningSuite API-Dokumentation, Version 1.23.2](https://api.learningsuite.io/api/v1/docs/1.23.2/).

## Kurzfazit

Ja. Die API deckt die erforderliche Provisionierung ab: Mitglied mit Microsoft-E-Mail, Vor- und Nachnamen anlegen bzw. aktualisieren und anschließend den KAHLE-Vinci-Kurs, ein Bundle oder eine gezielte Modulsichtbarkeit vergeben. Die Auslösung muss allerdings von OpenWebUI bzw. dem dortigen Benutzer-/Rollen-Änderungsereignis kommen; LearningSuite kann diesen OpenWebUI-Event nicht selbst empfangen oder erkennen.

## Geeigneter Ablauf

1. OpenWebUI meldet „Benutzer angelegt“ oder „Rolle wurde Benutzer/Admin“ an einen eigenen, geschützten Provisioning-Endpunkt (z. B. in n8n oder dem bestehenden Backend).
2. Der Endpunkt erstellt das Academy-Mitglied idempotent: `POST /api/v1/members` mit `email`, `firstName`, `lastName` und `ignoreIfAlreadyExists: true`. Laut Spezifikation liefert der Aufruf bei bereits vorhandenem Mitglied dieses zurück, statt einen Fehler zu werfen.
3. Bei Stammdatenänderungen erfolgt `PUT /api/v1/members/{memberId}` mit `email`, `firstName`, `lastName` (sowie optional `enabled`, `locale` usw.). Die E-Mail muss gültig und innerhalb des LearningSuite-Tenants eindeutig sein.
4. Danach wird der fachlich festgelegte Zugang vergeben:
   - Kurs: `PUT /api/v1/members/{memberId}/courses` mit `courseIds`.
   - Bundle/Lernpfad: `PUT /api/v1/members/{memberId}/bundles` mit `bundles`. Das ist die robuste Variante, wenn der Vinci-Zugang mehrere Kurse oder zeitlich gesteuerte Inhalte umfasst.
   - Gruppe: Mitglied per `PUT /api/v1/add-members-to-groups` zu einer Gruppe hinzufügen, wenn die Zugriffslogik dort modelliert ist. Die Gruppe kann mit `PUT /api/v1/group/{groupId}/courses` einmalig mit den Vinci-Kursen verbunden werden.

Die API liefert dazu `GET /api/v1/members/by-email?email=…` sowie Listen von veröffentlichten Kursen (`GET /api/v1/courses/published`), Bundles (`GET /api/v1/bundles`) und Kursmodulen (`GET /api/v1/courses/{courseId}/modules`). Das erlaubt Initialisierung, Abgleich und Monitoring.

Einzelne Module sind dagegen **kein eigenständiges Zuweisungsobjekt** in der dokumentierten API. `POST /api/v1/create-module-unlock-override` ändert nur die Sichtbarkeit eines Moduls für ein Mitglied mit bestehendem Kurszugang. Soll „KAHLE Vinci“ ein einzelnes Modul bleiben, muss der Nutzer daher zumindest Zugang zum zugehörigen Kurs erhalten. Klarer und wartbarer ist, Vinci als eigenständigen Kurs, Bundle oder gruppengesteuerten Kurszugang zu modellieren.

## Authentifizierung und Zustellung

- Basis-URL: `https://api.learningsuite.io/api/v1`.
- Authentifizierung: API-Key im Header `X-API-KEY`.
- Die API dokumentiert ein Limit von 120 Requests pro Minute.
- Das Anlegen verlangt `email`, `firstName` und `lastName`. `disableLoginEmail` unterdrückt die Willkommens-/Login-E-Mail; `locale` unterstützt `de` und `en`. Bei Bedarf kann anschließend `POST /api/v1/user/{userId}/send-login-email` eine Login-E-Mail auslösen.
- Für den Produktionsablauf: API-Key nur serverseitig speichern, Microsoft-E-Mail normalisieren und jeden Aufruf mit der OpenWebUI-User-ID sowie der LearningSuite-`memberId` revisionsfähig protokollieren.

## Idempotenz und Fehlerbehandlung

Die einfachste atomare Erstellung ist `ignoreIfAlreadyExists: true`; bei einer Wiederholung gibt LearningSuite den bestehenden Nutzer zurück. Für einen kontrollierten Abgleich kann vorher oder nach einem Fehler über `GET /members/by-email` gesucht werden. Anschließend sollten Stammdaten und Zugriffe gezielt aktualisiert werden. Die Spezifikation beschreibt jedoch keine einzelnen Fehlercodes für „E-Mail nicht gefunden“, Rate-Limit oder konkurrierende Requests; diese müssen im technischen Test gegen den KAHLE-Tenant validiert werden.

## Webhooks / Events

LearningSuite bietet ausgehende Webhook-Subscriptions über `POST /api/v1/webhooks/subscription` (`hookUrl`, `type`, `filter`). Relevant für Rückmeldungen sind insbesondere:

- `course.memberAdded`
- `group.userAccessChanged`
- `user.activationStatusChanged`
- zusätzlich Lernfortschritt: `courseProgress.changed` und `lesson.completed`.

Ein dokumentiertes LearningSuite-Ereignis für **Mitglied erstellt** oder **Rollenänderung** gibt es in Version 1.23.2 nicht. Für die gewünschte Richtung OpenWebUI → Academy ist das kein Hindernis: Die Quelle muss OpenWebUI sein. Die LearningSuite-Webhooks sind sinnvoll für Rückkanal, Audit und Zugriffsabgleich.

## Offene Punkte vor Umsetzung

1. Den fachlichen Zielzugang eindeutig festlegen: konkrete `courseId`, `bundleId` oder Gruppe. „Modul“ ist in LearningSuite ein Teil eines Kurses; ein Modul-Override ersetzt nicht den Kurszugang.
2. Prüfen, welches OpenWebUI-Ereignis bei Anlage und Rollenwechsel zuverlässig verfügbar ist und ob Vorname/Nachname dort bereits aus Microsoft Entra ID vorliegen. Falls nicht, braucht der Provisioner eine freigegebene Entra-ID-Quelle.
3. Entscheiden, ob Academy-Login-E-Mails erwünscht sind (`disableLoginEmail`) und welche Login-/SSO-Strategie für die Microsoft-Adressen gilt.
4. Mit einem Testmitglied den gesamten Ablauf testen: Erstanlage, Wiederholung, Namens-/E-Mail-Änderung, Doppel-Event, Kurs-/Bundle-Zugang und deaktivierter OpenWebUI-Nutzer.
5. Die OpenWebUI-Rollen nicht mit Academy-Administratoren gleichsetzen: Die API kann Lernende („Members“) anlegen, dokumentiert für Team-/Admin-Zugänge jedoch nur Lese-Endpunkte. Für OpenWebUI-Admins muss separat entschieden werden, ob sie ausschließlich Academy-Lernende oder auch manuell verwaltete Academy-Administratoren sein sollen.

## Quelle

- [LearningSuite API Docs 1.23.2](https://api.learningsuite.io/api/v1/docs/1.23.2/) – maßgeblich für alle genannten Endpunkte, Request-Felder, Authentifizierung, Rate-Limit und Webhook-Typen.
