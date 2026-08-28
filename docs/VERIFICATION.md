# Lokale Verification

Diese Datei ist der kanonische Einstiegspunkt für die lokale technische
Verification von KAHLE-Vinci. Der zentrale Runner ist
`scripts/run-local-tests.ps1`.

Die allgemeine Verification läuft offline und ohne reale Secrets. Prüfungen
gegen laufende Dienste, externe APIs oder Produktionskonfigurationen sind
separat als Specialized Verification beschrieben.

## Voraussetzungen

- Windows PowerShell 5.1 oder PowerShell 7
- Python 3.11 mit `stack/requirements-dev.txt`
- Node.js ab 22.13.0
- NPM-Abhängigkeiten aus `admin-dashboard/package-lock.json`

Saubere Verification-Umgebung anlegen:

```powershell
Set-Location C:\kahle-vinci
py -3.11 -m venv .venv-verify
.\.venv-verify\Scripts\python.exe -m pip install -r stack\requirements-dev.txt
.\.venv-verify\Scripts\python.exe -m pip check

Push-Location admin-dashboard
npm.cmd ci
Pop-Location
```

`stack/requirements-dev.txt` ist die gemeinsame, lokal verifizierte
Testkombination. Die Runtime-Requirements der einzelnen Dienste bleiben davon
getrennt und dürfen nicht durch diese Datei ersetzt werden.

## Welcher Tier ist wann erforderlich?

### Targeted Checks

Targeted Checks laufen während der Implementierung. Sie prüfen genau den
betroffenen Dienst, Vertrag oder statischen Bereich und geben schnelles
Feedback. Nach einer Änderung werden zunächst die kleinsten aussagekräftigen
Tests ausgeführt. Targeted Checks ersetzen den erforderlichen Fast oder Full
Verify vor Abschluss nicht.

### Fast

Fast ist für kleinere bis mittlere, lokal begrenzte Änderungen vorgesehen.
Typische Beispiele sind eine Änderung innerhalb eines Dienstes, eine
überschaubare Workflow-Anpassung oder eine lokale UI-Korrektur ohne
bereichsübergreifende Auswirkungen.

Fast läuft vollständig offline. Es umfasst die breiten Stack-Verträge, die
kleineren Dienstsuiten, die statischen Konfigurationsprüfungen und den UI-Lint.

### Full

Full ist vor Abschluss substantieller Änderungen erforderlich. Full ist
ebenfalls Pflicht bei bereichsübergreifenden Änderungen sowie bei Security-,
Datenmodell-, Integrations- oder Infrastrukturänderungen.

Full enthält alle Fast-Checks und ergänzt die vollständige Portal-Backend-Suite
sowie UI-Produktionsbuild und Renderingtests. `Full` ist der Standard des
Runners.

### Specialized

Specialized Verification wird nur für die jeweils betroffenen Bereiche
ausgeführt. Diese Prüfungen benötigen einen laufenden Stack, externe APIs,
reale Konfigurationen, Secrets, Testkorpora oder eine konkrete
Betriebsumgebung. Sie ersetzen Fast oder Full nicht, sondern ergänzen den
erforderlichen allgemeinen Tier.

## Inhalt der Tiers

| Check | Targeted | Fast | Full |
|---|:---:|:---:|:---:|
| Compose-Static-Check | bei Compose-Änderungen | ja | ja |
| n8n-Workflow-Static-Check | bei n8n-Änderungen | ja | ja |
| Open-WebUI-Tool-Bundle-Sync | bei Tool-Änderungen | ja | ja |
| `stack/tests` | nach betroffenem Vertrag | ja | ja |
| `stack/kb-sync/tests` | bei Index-/Retrieval-Änderungen | ja | ja |
| `eval/rag/tests` | bei Eval-/Retrieval-Änderungen | ja | ja |
| `stack/academy-provisioner/tests` | bei Academy-Änderungen | ja | ja |
| `stack/personio-directory/tests` | bei Personio-Änderungen | ja | ja |
| Portal-UI-Lint | bei UI-Änderungen | ja | ja |
| `stack/kb-admin-api/tests` | bei Portal-Backend-Änderungen | nein | ja |
| Portal-UI-Produktionsbuild | bei UI-Änderungen | nein | ja |
| Portal-UI-Renderingtests | bei UI-Änderungen | nein | ja |

Jeder Check wird soweit technisch möglich unabhängig ausgeführt. Der Runner
sammelt Fehler und zeigt am Ende eine kompakte Ergebnisübersicht. Exit-Code 0
bedeutet, dass alle für den gewählten Tier erforderlichen Checks bestanden
haben.

Die Ergebnisübersicht unterscheidet:

- `TESTFEHLER`: Der Check wurde regulär ausgeführt und hat einen Fehler
  festgestellt.
- `SETUPFEHLER`: Der Check war nicht regulär ausführbar, etwa wegen eines
  fehlenden Befehls, einer fehlenden Python-/Node-Abhängigkeit oder
  `spawn EPERM` in einer verwalteten Windows-Sandbox.

Ungültige Repositoryartefakte, Syntax-/Collectionfehler und unerwartet leere
Testsuiten sind Testfehler. Exitcodes allein werden nicht pauschal als
Setupfehler bewertet.

Auch ein Setupfehler führt zum Gesamt-Exit-Code 1. Ein UI-Build, der nur mit
`spawn EPERM` in der Sandbox scheitert, wird mit demselben Befehl außerhalb der
Sandbox wiederholt. Ein erfolgreicher Wiederholungslauf belegt ein
Umgebungsproblem, keinen Produktfehler.

## Kanonische Befehle

Fast Verify:

```powershell
.\scripts\run-local-tests.ps1 `
  -Tier Fast `
  -Python .\.venv-verify\Scripts\python.exe `
  -Npm npm.cmd
```

Full Verify:

```powershell
.\scripts\run-local-tests.ps1 `
  -Tier Full `
  -Python .\.venv-verify\Scripts\python.exe `
  -Npm npm.cmd
```

Ohne `-Tier` läuft `Full`.

## Targeted Checks

Alle Befehle werden aus dem Repository-Root ausgeführt:

```powershell
$py = ".\.venv-verify\Scripts\python.exe"

& $py -m pytest stack\kb-admin-api\tests -q -p no:cacheprovider
& $py -m pytest stack\tests -q -p no:cacheprovider
& $py -m pytest stack\kb-sync\tests -q -p no:cacheprovider
& $py -m pytest stack\academy-provisioner\tests -q -p no:cacheprovider
& $py -m pytest stack\personio-directory\tests -q -p no:cacheprovider

$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = "$PWD\eval\rag;$PWD\stack\kb-sync"
    & $py -m pytest eval\rag\tests -q -p no:cacheprovider
}
finally {
    $env:PYTHONPATH = $previousPythonPath
}

& $py stack\tests\compose_static_check.py
& $py stack\tests\n8n_workflow_static_check.py
& $py stack\open-webui-tools\build_tools.py --check

Push-Location admin-dashboard
npm.cmd run lint
npm.cmd run build
node.exe tests\rendered-html.test.mjs
Pop-Location
```

Mehrere Python-Dienste besitzen ein eigenes Paket `app`. Ihre Suiten dürfen
nicht in einem gemeinsamen pytest-Prozess kombiniert werden. Der kanonische
Runner startet deshalb für jede Suite einen eigenen Prozess und setzt den
jeweiligen Modulpfad deterministisch.

## Specialized Verification

### Laufender lokaler Stack

File-Proxy-Smoke-Test:

```powershell
$apiKey = Read-Host "OWUI_FILE_PROXY_API_KEY"
python stack\tests\smoke_file_proxy.py `
  --base-url http://127.0.0.1:8091 `
  --api-key $apiKey `
  --docx-file <DOCX-Datei> `
  --pdf-file-a <PDF-Datei-A> `
  --pdf-file-b <PDF-Datei-B> `
  --txt-file <TXT-Datei> `
  --xlsx-file <XLSX-Datei> `
  --xlsx-sheet <Tabellenblatt>
Remove-Variable apiKey
```

Die erforderlichen Parameter und datensparsamen Regeln stehen in
`stack/tests/README.md`.

Konvertierungsqualität gegen den Document Worker:

```powershell
python stack\tests\measure_conversion_quality.py <Dateimuster> --output <Bericht.json>
```

### IONOS und Retrieval

```powershell
python stack\tests\ionos_connectivity_check.py
.\eval\rag\run_eval.ps1
python eval\rag\run_runtime_eval.py

$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = "$PWD\eval\rag;$PWD\stack\kb-sync"
    python eval\rag\offline_hybrid_eval.py <Dokumentordner> --report <Bericht.json>
}
finally {
    $env:PYTHONPATH = $previousPythonPath
}

python stack\tests\calibrate_rerank_threshold.py "<Kontrollfrage>"
```

API-Schlüssel werden über die dafür dokumentierten Umgebungsvariablen
bereitgestellt. Der File-Proxy-Smoke liest seinen Schlüssel interaktiv ein,
weil das bestehende Skript nur `--api-key` unterstützt. Specialized-Befehle
dürfen nicht protokolliert werden. Secrets dürfen weder in Berichte,
Chat-Ausgaben noch in das Repository übernommen werden.

### Akzeptanz- und Wiederherstellungsnachweise

```powershell
python scripts\openwebui\kahle-harness-acceptance.py <privacy-safe-runs.json>
Push-Location stack
python tests\measure_restore_rto.py --documents 500
Pop-Location
```

### Produktionskonfiguration

Auf dem vorgesehenen Linux-Host mit geschützter Produktions-Env-Datei:

```bash
sudo stack/scripts/start-production.sh stack/.env.production --check-only
```

Dieser Check validiert die produktive Compose-Konfiguration, ist aber nicht
Teil der allgemeinen lokalen Verification. Er legt vor dem Compose-Check die
benötigten Betriebsverzeichnisse an. `docker compose config` darf wegen
möglicher Secret-Ausgabe nicht ohne `--quiet` protokolliert werden.

`caddy validate` bleibt eine spezialisierte Routingprüfung mit der jeweils
betroffenen Caddy-Konfiguration und kontrollierten Platzhalterwerten.

## Bekannte Grenzen

- Es gibt derzeit keine eingecheckte CI-Konfiguration. Das Gate wird lokal
  ausgeführt.
- Der Compose-Static-Check prüft die Basisdatei `stack/docker-compose.yml`.
  Overlays und vollständige Variablenauflösung werden nur in der jeweils
  passenden Betriebsumgebung geprüft.
- Der n8n-Static-Check prüft den kanonischen Export
  `n8n/all-workflows.json`, nicht automatisch jede einzelne Workflow-Datei.
- Der UI-Lint meldet vorhandene Warnungen, behandelt sie gemäß bestehender
  ESLint-Konfiguration aber nicht als Fehler.
