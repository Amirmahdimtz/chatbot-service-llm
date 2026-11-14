<#
Read one local Chat SSE response incrementally on Windows PowerShell 5.1+.
Never echo credentials or pass them via command-line arguments.
#>
[CmdletBinding()]
param(
    [string]$ApiUrl = "http://127.0.0.1:18000/api/v1/chat/stream",
    [switch]$CancelAfterFirstDelta,
    [string]$ConversationId,
    [ValidateSet("general", "knowledge_qa")]
    [string]$Scenario = "general"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Windows PowerShell 5.1 does not necessarily preload System.Net.Http.
Add-Type -AssemblyName System.Net.Http -ErrorAction Stop

$Endpoint = [Uri]$ApiUrl
if ($Endpoint.Scheme -ne "http" -or
    $Endpoint.Host -notin @("127.0.0.1", "localhost") -or
    $Endpoint.AbsolutePath -ne "/api/v1/chat/stream") {
    throw "This development script only sends credentials to a local HTTP Chat endpoint."
}

$EnvPath = Join-Path (Split-Path -Parent $PSScriptRoot) ".env"
if (-not (Test-Path -LiteralPath $EnvPath -PathType Leaf)) {
    throw "Missing .env file; run scripts/initialize-development-env.ps1."
}
$KeyLines = @(Get-Content -LiteralPath $EnvPath | Where-Object { $_ -match '^CHATBOT_DEV_API_TOKEN=' })
if ($KeyLines.Count -ne 1) {
    throw "Expected exactly one CHATBOT_DEV_API_TOKEN entry in .env."
}

$Token = $KeyLines[0].Substring("CHATBOT_DEV_API_TOKEN=".Length)
if ($Token.Length -lt 32) {
    throw "CHATBOT_DEV_API_TOKEN is missing or too short."
}
$Http = $null
$Req = $null
$Resp = $null
$Reader = $null
try {
    $Http = [System.Net.Http.HttpClient]::new()
    $Http.Timeout = [TimeSpan]::FromMinutes(3)
    $Req = [System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::Post, $Endpoint)
    $Req.Headers.Authorization = [System.Net.Http.Headers.AuthenticationHeaderValue]::new("Bearer", $Token)
    # Keep this script ASCII-only: Windows PowerShell 5.1 reads UTF-8 without BOM as ANSI.
    # JSON Unicode escapes reconstruct the Persian request after JSON decoding.
    $Body = '{"message":"\u0633\u0644\u0627\u0645\u060c \u0644\u0637\u0641\u0627\u064b \u062f\u0631 \u062f\u0648 \u062c\u0645\u0644\u0647 \u0628\u0647 \u0641\u0627\u0631\u0633\u06cc \u067e\u0627\u0633\u062e \u0628\u062f\u0647."}'
    if ($Scenario -eq "knowledge_qa") {
        $Body = $Body.Substring(0, $Body.Length - 1) + ',"scenario":"knowledge_qa"}'
    }
    if ($ConversationId) {
        $ParsedId = [Guid]::Empty
        if (-not [Guid]::TryParse($ConversationId, [ref]$ParsedId)) {
            throw "ConversationId must be a UUID."
        }
        $Body = $Body.Substring(0, $Body.Length - 1) + ',"conversation_id":"' + $ParsedId.ToString() + '"}'
    }
    $Req.Content = [System.Net.Http.StringContent]::new(
        $Body, [System.Text.Encoding]::UTF8, "application/json"
    )
    $Clock = [System.Diagnostics.Stopwatch]::StartNew()
    $Resp = $Http.SendAsync(
        $Req, [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead
    ).GetAwaiter().GetResult()

    Write-Host ("HTTP status: {0}" -f [int]$Resp.StatusCode)
    Write-Host ("Content-Type: {0}" -f $Resp.Content.Headers.ContentType)
    if ([int]$Resp.StatusCode -ne 200) {
        throw "Chat API returned an unexpected HTTP status; check the local setup."
    }
    if ($null -eq $Resp.Content.Headers.ContentType -or
        $Resp.Content.Headers.ContentType.MediaType -ne "text/event-stream") {
        throw "Chat API did not return text/event-stream."
    }

    $Reader = [System.IO.StreamReader]::new(
        $Resp.Content.ReadAsStreamAsync().GetAwaiter().GetResult(),
        [System.Text.Encoding]::UTF8
    )
    $SawStart = $false
    $SawEnd = $false
    $SawError = $false
    $SawDelta = $false
    $SawSources = $false
    $EventName = ""
    while (($Line = $Reader.ReadLine()) -ne $null) {
        if ($Line.StartsWith("event: ")) {
            $EventName = $Line.Substring(7)
            if ($EventName -eq "message_start") { $SawStart = $true }
            if ($EventName -eq "message_end") { $SawEnd = $true }
            if ($EventName -eq "error") { $SawError = $true }
            if ($EventName -eq "sources") { $SawSources = $true }
            Write-Host ("{0:N2}s {1}" -f $Clock.Elapsed.TotalSeconds, $Line)
        }
        elseif ($Line.StartsWith("data: ")) {
            Write-Host ("{0:N2}s {1}" -f $Clock.Elapsed.TotalSeconds, $Line)
            if ($EventName -eq "delta") {
                $SawDelta = $true
                if ($CancelAfterFirstDelta) {
                    Write-Host "Client cancelled after first delta."
                    break
                }
            }
        }
    }

    if ($CancelAfterFirstDelta) {
        if (-not $SawDelta) { throw "No delta arrived before the stream ended." }
    }
    elseif ($SawError) {
        throw "Chat model returned an SSE error; see the sanitized event code above."
    }
    elseif (-not $SawStart -or -not $SawEnd -or -not $SawDelta) {
        throw "Incomplete SSE stream: expected start, delta and end events."
    }
    if ($Scenario -eq "knowledge_qa" -and -not $SawSources) {
        Write-Host "No authorized sources returned; inspect response_type for insufficient_evidence."
    }
}
finally {
    foreach ($Resource in @($Reader, $Resp, $Req, $Http)) {
        if ($null -ne $Resource) { $Resource.Dispose() }
    }
    Remove-Variable Token, KeyLines -ErrorAction SilentlyContinue
}
