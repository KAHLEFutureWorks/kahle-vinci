param(
    [string]$Container = "open-webui"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$registerScript = Join-Path $repoRoot "scripts\openwebui\register-kahle-workflow-tool.py"
$distRoot = Join-Path $repoRoot "stack\open-webui-tools\dist"

foreach ($path in @(
    $registerScript,
    (Join-Path $distRoot "rag_chat_hybrid_tool.py"),
    (Join-Path $distRoot "kahle_workflow_orchestrator.py")
)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Erforderliche Datei fehlt: $path"
    }
}

$running = docker inspect -f "{{.State.Running}}" $Container 2>$null
if ($LASTEXITCODE -ne 0 -or $running.Trim() -ne "true") {
    throw "Der Container '$Container' läuft nicht."
}

docker exec $Container sh -c "mkdir -p /tmp/kahle-vinci/scripts/openwebui /tmp/kahle-vinci/stack/open-webui-tools/dist"
if ($LASTEXITCODE -ne 0) { throw "Temporärer Zielordner konnte nicht vorbereitet werden." }

docker cp $registerScript "${Container}:/tmp/kahle-vinci/scripts/openwebui/register-kahle-workflow-tool.py"
if ($LASTEXITCODE -ne 0) { throw "Registrierungsskript konnte nicht kopiert werden." }
docker cp (Join-Path $distRoot "rag_chat_hybrid_tool.py") "${Container}:/tmp/kahle-vinci/stack/open-webui-tools/dist/rag_chat_hybrid_tool.py"
if ($LASTEXITCODE -ne 0) { throw "RAG-Tool konnte nicht kopiert werden." }
docker cp (Join-Path $distRoot "kahle_workflow_orchestrator.py") "${Container}:/tmp/kahle-vinci/stack/open-webui-tools/dist/kahle_workflow_orchestrator.py"
if ($LASTEXITCODE -ne 0) { throw "Workflow-Tool konnte nicht kopiert werden." }

foreach ($tool in @("rag_chat", "kahle_workflow")) {
    docker exec `
        -e KAHLE_REPO_ROOT=/tmp/kahle-vinci `
        -e OWUI_DB_PATH=/app/backend/data/webui.db `
        $Container python /tmp/kahle-vinci/scripts/openwebui/register-kahle-workflow-tool.py --only $tool
    if ($LASTEXITCODE -ne 0) { throw "Tool-Aktualisierung fehlgeschlagen: $tool" }
}

docker restart $Container | Out-Null
if ($LASTEXITCODE -ne 0) { throw "OpenWebUI konnte nicht neu gestartet werden." }

Write-Host "RAG-Tools wurden ohne API-Key aktualisiert. OpenWebUI startet neu."
