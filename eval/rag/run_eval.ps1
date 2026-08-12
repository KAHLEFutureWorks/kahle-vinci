[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$BaseUrl = "http://127.0.0.1:3000",
    [string]$Model = "mistralai/Mistral-Small-24B-Instruct",
    [string]$QuestionsFile = "eval/rag/questions.yml",
    [string]$OutputDir = "eval/rag/results",
    [string]$ApiKey,
    [string]$ApiKeyEnv = "OPENWEBUI_API_KEY",
    [string]$ChatPath = "/api/chat/completions",
    [int]$TimeoutSec = 120,
    [int]$MaxQuestions = 0,
    [string[]]$ToolIds = @("rag_chat")
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-ApiKey {
    param([string]$ExplicitKey, [string]$EnvName)

    if (-not [string]::IsNullOrWhiteSpace($ExplicitKey)) {
        return $ExplicitKey
    }

    $fromEnv = [Environment]::GetEnvironmentVariable($EnvName)
    if (-not [string]::IsNullOrWhiteSpace($fromEnv)) {
        return $fromEnv
    }

    return $null
}

function Read-RagQuestions {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Questions file not found: $Path"
    }

    $items = New-Object System.Collections.Generic.List[object]
    $kb = $null
    $current = $null

    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -match '^\s{2}([A-Za-z0-9_-]+):\s*$') {
            $kb = $Matches[1]
            continue
        }
        if ($line -match '^\s{4}-\s+question:\s+"(.*)"\s*$') {
            if ($null -ne $current) {
                $items.Add([pscustomobject]$current)
            }
            $current = @{
                knowledgebase = $kb
                question = $Matches[1]
                expected_topic = ""
                must_have_terms = @()
                conversation = ""
            }
            continue
        }
        if ($null -ne $current -and $line -match '^\s{6}expected_topic:\s+"(.*)"\s*$') {
            $current.expected_topic = $Matches[1]
            continue
        }
        if ($null -ne $current -and $line -match '^\s{6}must_have_terms:\s+\[(.*)\]\s*$') {
            $terms = @()
            foreach ($part in ($Matches[1] -split ',')) {
                $term = $part.Trim().Trim('"').Trim("'")
                if ($term.Length -gt 0) {
                    $terms += $term
                }
            }
            $current.must_have_terms = $terms
            continue
        }
        if ($null -ne $current -and $line -match '^\s{6}conversation:\s+"(.*)"\s*$') {
            $current.conversation = $Matches[1]
        }
    }

    if ($null -ne $current) {
        $items.Add([pscustomobject]$current)
    }

    return $items
}

function Invoke-RagQuestion {
    param(
        [string]$Url,
        [string]$ModelName,
        [object]$Question,
        [string]$Token,
        [int]$Timeout,
        [object[]]$History = @()
    )

    $headers = @{
        "Content-Type" = "application/json"
    }
    if (-not [string]::IsNullOrWhiteSpace($Token)) {
        $headers.Authorization = "Bearer $Token"
    }

    $prompt = @"
Beantworte die folgende Frage nur anhand der verfuegbaren Knowledgebase-Inhalte.
Wenn die Antwort nicht belegt ist, sage kurz, dass die Information in den Quellen fehlt.

Knowledgebase: $($Question.knowledgebase)
Erwarteter Themenbereich fuer die Evaluation: $($Question.expected_topic)
Frage: $($Question.question)
"@

    $messages = New-Object System.Collections.Generic.List[object]
    $messages.Add(@{ role = "system"; content = "Du bist ein vorsichtiger deutschsprachiger RAG-Evaluationsassistent." })
    foreach ($message in $History) { $messages.Add($message) }
    $messages.Add(@{ role = "user"; content = $prompt })

    $messageArray = @($messages | ForEach-Object { $_ })
    $body = @{
        model = $ModelName
        messages = $messageArray
        temperature = 0
        tool_ids = $ToolIds
        stream = $false
    } | ConvertTo-Json -Depth 8

    Add-Type -AssemblyName System.Net.Http
    $client = New-Object System.Net.Http.HttpClient
    $client.Timeout = [TimeSpan]::FromSeconds($Timeout)
    try {
        $request = New-Object System.Net.Http.HttpRequestMessage([System.Net.Http.HttpMethod]::Post, $Url)
        if (-not [string]::IsNullOrWhiteSpace($Token)) {
            $request.Headers.Authorization = New-Object System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", $Token)
        }
        $request.Content = New-Object System.Net.Http.StringContent($body, [Text.Encoding]::UTF8, "application/json")
        $httpResponse = $client.SendAsync($request).GetAwaiter().GetResult()
        $rawBytes = $httpResponse.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult()
        $rawJson = [Text.Encoding]::UTF8.GetString($rawBytes)
        if (-not $httpResponse.IsSuccessStatusCode) {
            throw "HTTP $([int]$httpResponse.StatusCode): $rawJson"
        }
        return $rawJson | ConvertFrom-Json
    }
    finally {
        $client.Dispose()
    }
}

$questions = Read-RagQuestions -Path $QuestionsFile
if ($MaxQuestions -gt 0) {
    $questions = @($questions | Select-Object -First $MaxQuestions)
}
$base = $BaseUrl.TrimEnd("/")
$chatUrl = "$base$ChatPath"
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$jsonlPath = Join-Path $OutputDir "rag-eval-$timestamp.jsonl"
$mdPath = Join-Path $OutputDir "rag-eval-$timestamp.md"
$token = Get-ApiKey -ExplicitKey $ApiKey -EnvName $ApiKeyEnv
$conversationHistory = @{}

Write-Host "RAG eval template"
Write-Host "Base URL: $base"
Write-Host "Chat path: $ChatPath"
Write-Host "Model: $Model"
Write-Host "Questions: $($questions.Count) from $QuestionsFile"
Write-Host "API key source: parameter or environment variable '$ApiKeyEnv' (value is never printed)"

if ($WhatIfPreference) {
    foreach ($q in $questions) {
        Write-Host "WHATIF question [$($q.knowledgebase)]: $($q.question)"
    }
}

if ($PSCmdlet.ShouldProcess($OutputDir, "Create RAG evaluation output directory")) {
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
}

$markdown = New-Object System.Collections.Generic.List[string]
$markdown.Add("# RAG Evaluation $timestamp")
$markdown.Add("")
$markdown.Add("- Base URL: ``$base``")
$markdown.Add("- Chat path: ``$ChatPath``")
$markdown.Add("- Model: ``$Model``")
$markdown.Add("- Questions file: ``$QuestionsFile``")
$markdown.Add("")

foreach ($q in $questions) {
    if (-not $PSCmdlet.ShouldProcess($q.question, "Call RAG chat endpoint")) {
        continue
    }

    $started = Get-Date
    $status = "ok"
    $answer = ""
    $sources = @()
    $toolCalls = @()
    $errorMessage = ""

    try {
        $history = @()
        if (-not [string]::IsNullOrWhiteSpace($q.conversation) -and $conversationHistory.ContainsKey($q.conversation)) {
            $history = @($conversationHistory[$q.conversation])
        }
        $response = Invoke-RagQuestion -Url $chatUrl -ModelName $Model -Question $q -Token $token -Timeout $TimeoutSec -History $history
        $answer = [string]$response.choices[0].message.content
        if ($response.choices[0].message.PSObject.Properties.Name -contains "tool_calls") {
            $toolCalls = @($response.choices[0].message.tool_calls)
        }
        if ($response.PSObject.Properties.Name -contains "sources") { $sources = @($response.sources) }
        elseif ($response.choices[0].message.PSObject.Properties.Name -contains "sources") { $sources = @($response.choices[0].message.sources) }
        if (-not [string]::IsNullOrWhiteSpace($q.conversation)) {
            $conversationHistory[$q.conversation] = @($history) + @(
                @{ role = "user"; content = $q.question },
                @{ role = "assistant"; content = $answer }
            )
        }
    }
    catch {
        $status = "error"
        $errorMessage = $_.Exception.Message
        if (-not [string]::IsNullOrWhiteSpace($_.ErrorDetails.Message)) {
            $errorMessage += " " + $_.ErrorDetails.Message
        }
    }

    $record = [pscustomobject]@{
        timestamp = $started.ToString("o")
        status = $status
        knowledgebase = $q.knowledgebase
        question = $q.question
        expected_topic = $q.expected_topic
        conversation = $q.conversation
        elapsed_ms = [Math]::Round(((Get-Date) - $started).TotalMilliseconds)
        must_have_terms = $q.must_have_terms
        answer = $answer
        sources = $sources
        tool_calls = $toolCalls
        error = $errorMessage
    }

    $json = $record | ConvertTo-Json -Compress -Depth 8
    Add-Content -LiteralPath $jsonlPath -Value $json -Encoding UTF8

    $markdown.Add("## $($q.knowledgebase): $($q.question)")
    $markdown.Add("")
    $markdown.Add("Erwarteter Themenbereich: $($q.expected_topic)")
    $markdown.Add("")
    if ($status -eq "ok") {
        $markdown.Add($answer)
    }
    else {
        $markdown.Add("ERROR: $errorMessage")
    }
    $markdown.Add("")
}

if ($PSCmdlet.ShouldProcess($mdPath, "Write Markdown evaluation report")) {
    Set-Content -LiteralPath $mdPath -Value $markdown -Encoding UTF8
    Write-Host "Wrote $jsonlPath"
    Write-Host "Wrote $mdPath"
}
