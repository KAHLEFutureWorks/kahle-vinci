# Admin Dashboard Instructions

## Scope

Diese Regeln gelten für das React-/Vinext-Frontend unter `admin-dashboard/`.
Die allgemeinen Regeln aus [`../AGENTS.md`](../AGENTS.md) gelten zusätzlich.

## Local Architecture

- `app/page.tsx` lädt den aktuellen Portal-Einstieg `KnowledgePortal`.
- Das Portal wird im vollständigen Stack unter `/wissen/` bereitgestellt.
- `components/KnowledgePortal.tsx` enthält die aktuelle rollenbasierte
  Portaloberfläche.
- `components/VectorAdmin.tsx` enthält weiterhin klassische Funktionen, ist
  aber nicht der aktuelle Seiteneinstieg.
- API-Aufrufe verwenden die bestehende Open-WebUI-Sitzung und den Pfad
  `/wissen/api`.
- Rollen, Rechte, Lifecycle-Regeln und Sicherheitsentscheidungen liegen in der
  Portal-API. Das Frontend stellt diese Zustände dar und sendet die vorgesehenen
  Bestätigungen.

## Local Implementation Rules

- Implementiere Authentifizierung oder Autorisierung nicht ausschließlich im
  Client. Sichtbarkeitsregeln in der UI ersetzen keine Backendprüfung.
- Bewahre die Unterschiede zwischen `employee`, `manager`, `admin` und
  `portal_admin` sowie zwischen Lese- und Uploadrechten.
- Kritische Aktionen behalten ihre ausdrücklichen Bestätigungsdialoge und
  Requestfelder.
- Füge keine IONOS-, Qdrant-, Document-Worker-, internen API- oder
  Provider-Credentials in Quelltext, Env-Bundles oder Browseraufrufe ein.
- Nutze die vorhandenen Komponenten, Hooks, API-Hilfen und Styles, bevor neue
  parallele Muster angelegt werden.
- Halte den produktiven Basispfad `/wissen/` und relative Asset-/API-Pfade
  kompatibel mit Caddy.
- Behebe vorhandene ESLint-Warnungen nicht beiläufig. Ändere sie nur, wenn sie
  Teil des Auftrags sind oder durch die eigene Änderung neu entstehen.
- Behandle Dateien unter `dist/` und `.next/` als erzeugte Ausgaben.

## Local Commands

Abhängigkeiten installieren:

```powershell
Push-Location admin-dashboard
npm.cmd ci
Pop-Location
```

Targeted UI-Checks:

```powershell
Push-Location admin-dashboard
npm.cmd run lint
npm.cmd run build
node.exe tests\rendered-html.test.mjs
Pop-Location
```

Während der Implementierung läuft der kleinste betroffene Check. Vor Abschluss
gilt der Fast- oder Full-Tier aus
[`../docs/VERIFICATION.md`](../docs/VERIFICATION.md). Der Produktionsbuild und
die Renderingtests sind Bestandteil von Full.

Wenn der UI-Build ausschließlich mit `spawn EPERM` in einer verwalteten
Windows-Sandbox scheitert, wird derselbe Befehl außerhalb der Sandbox
wiederholt. Nur ein erfolgreicher identischer Wiederholungslauf belegt ein
Umgebungsproblem.

## Local High-Risk Areas

- rollenabhängige Navigation und Aktionssichtbarkeit
- Upload-, Freigabe-, Lösch-, Restore- und Rollenbestätigungen
- Sessionübernahme und API-Basispfad
- Darstellung vertraulicher Dokument- und Mitarbeiterdaten
- Downloadlinks und Dateivorschauen
- Produktionsbuild unter dem Caddy-Basispfad

## Parent and Deeper Documentation

- [`../ARCHITECTURE.md`](../ARCHITECTURE.md)
- [`../SECURITY.md`](../SECURITY.md)
- [`../DECISIONS.md`](../DECISIONS.md)
- [`../docs/VERIFICATION.md`](../docs/VERIFICATION.md)
- [`../docs/operations/kb-admin-dashboard.md`](../docs/operations/kb-admin-dashboard.md)
- [`README.md`](README.md)
