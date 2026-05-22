# OpenWebUI KAHLE Branding Design

## Ziel

OpenWebUI soll fuer KAHLE-Vinci reproduzierbar gebrandet werden, ohne manuelle Aenderungen im laufenden Container. Die Anpassung umfasst den Namen `KAHLE-Vinci`, das KAHLE-Vinci-Logo oben links, das KAHLE-Gruppe-Logo als globalen Chat-Hintergrund und eine reduzierte Einstellungsoberflaeche fuer normale Benutzer.

## Bestehender Stand

Die aktuelle Installation nutzt in `C:\kahle-vinci\stack\docker-compose.yml` das fertige Image `ghcr.io/open-webui/open-webui:v0.9.2`. Backend-Dateien werden bereits ueber `stack/open-webui-overrides` in den Container gemountet. Frontend-Quellcode oder ein eigenes OpenWebUI-Image fuer KAHLE-Branding existieren noch nicht.

Die Branding-Assets liegen hier:

- `C:\kahle-vinci\public\logo\KAHLE-Vinci-Logo.png`
- `C:\kahle-vinci\public\background\Logo_Kahle_Gruppe_positiv.jpg`

Der Chat-Hintergrund ist derzeit fuer mindestens einen Account als Benutzer-Einstellung `ui.backgroundImageUrl` gespeichert. Das ist nicht ausreichend fuer eine globale Vorgabe.

## Privilegierte Rollen und Gruppen

OpenWebUI speichert die technische Rolle in `user.role`; in der lokalen Datenbank sind aktuell `admin` und `user` vorhanden. Fachliche Rollen werden als OpenWebUI-Gruppen modelliert. Die Sichtbarkeitsregel wird deshalb so ausgewertet:

- `Administrator`: technische OpenWebUI-Rolle `admin`
- `Geschaeftsleitung`: OpenWebUI-Gruppe `Geschaeftsleitung` oder `Geschäftsleitung`
- `AI-Pilot`: OpenWebUI-Gruppe `AI-Pilot`

Alle anderen Rollen sehen eine reduzierte Settings-UI.

## Auszublendende Bereiche

Fuer alle nicht privilegierten Rollen werden folgende Bereiche ausgeblendet:

- Benutzeroberflaeche
- Verbindungen
- Integrationen
- Audio
- Datenkontrolle
- Erweiterte Modell-/Parameterbereiche

Admins und die freigegebenen Fachgruppen behalten Zugriff auf diese Bereiche.

## Architektur

Die stabile Loesung ist ein eigenes KAHLE-OpenWebUI-Image auf Basis der gepinnten OpenWebUI-Version. Das Image wird reproduzierbar gebaut und ersetzt keine Dateien manuell im laufenden Container.

Die KAHLE-Schicht enthaelt:

- statische Assets unter einem KAHLE-Pfad, zum Beispiel `/static/kahle/logo.png` und `/static/kahle/chat-background.jpg`
- eine Anpassung des App-Namens auf `KAHLE-Vinci`
- Frontend-Logik fuer den globalen Chat-Hintergrund, wenn kein Benutzer-Hintergrund gesetzt ist oder wenn KAHLE-Branding erzwungen wird
- rollen- und gruppenbasierte Sichtbarkeit fuer Settings-Navigation und erweiterte Parameterbereiche

Die bestehende Compose-Datei soll kuenftig ein lokal gebautes Image nutzen, zum Beispiel `kahle-open-webui:v0.9.2-kahle.1`. Die OpenWebUI-Basisversion bleibt sichtbar und updatebar.

## Update-Strategie

Bei OpenWebUI-Updates wird die Basisversion aktualisiert, das KAHLE-Image neu gebaut und die KAHLE-Patches werden gegen die neue Version geprueft. Die Anpassungen sollen als kleine, dokumentierte Patch-Schicht erhalten bleiben, damit Konflikte bei Updates sichtbar und testbar sind.

Jedes Update muss mindestens pruefen:

- Startet OpenWebUI mit dem eigenen Image?
- Wird `KAHLE-Vinci` oben links angezeigt?
- Wird das KAHLE-Vinci-Logo angezeigt?
- Wird der KAHLE-Gruppe-Hintergrund in hell und dunkel korrekt dargestellt?
- Sieht ein normaler Benutzer nur die reduzierte Settings-UI?
- Sehen `Administrator`, `Geschaeftsleitung`/`Geschäftsleitung` und `AI-Pilot` die vollstaendige Settings-UI?

## Teststrategie

Die Umsetzung braucht drei Testebenen:

- statische Compose-/Build-Tests fuer das neue Image und die Asset-Pfade
- Frontend- oder Patch-Tests fuer die Rollenlogik
- manueller Browser-Smoke-Test mit mindestens einem normalen Benutzer und einem privilegierten Benutzer

## Nicht-Ziele

Diese Aenderung soll keine OpenWebUI-Funktionen entfernen. Sie reduziert die sichtbare Oberflaeche fuer normale Rollen. Sicherheitsrelevante oder administrative Faehigkeiten muessen weiterhin serverseitig ueber Rollen, Gruppen oder Berechtigungen abgesichert werden, wenn reines Ausblenden nicht ausreicht.
