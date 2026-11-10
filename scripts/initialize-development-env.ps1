<#
Initialize missing development credentials without overwriting existing values.
Supports CRLF and LF .env files and works with Windows PowerShell 5.1+.
#>
[CmdletBinding()]
param(
    [string]$EnvPath,
    [string]$TemplatePath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not $EnvPath) { $EnvPath = Join-Path $ProjectRoot ".env" }
if (-not $TemplatePath) { $TemplatePath = Join-Path $ProjectRoot ".env.example" }

if (-not (Test-Path -LiteralPath $EnvPath -PathType Leaf)) {
    if (-not (Test-Path -LiteralPath $TemplatePath -PathType Leaf)) {
        throw "Missing environment template: $TemplatePath"
    }
    Copy-Item -LiteralPath $TemplatePath -Destination $EnvPath -ErrorAction Stop
}

$ResolvedEnvPath = (Resolve-Path -LiteralPath $EnvPath).ProviderPath
$Contents = [System.IO.File]::ReadAllText($ResolvedEnvPath)
$Changed = $false

function New-UrlSafeSecret {
    $Bytes = New-Object byte[] 32
    $Generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $Generator.GetBytes($Bytes)
    }
    finally {
        $Generator.Dispose()
    }
    return [Convert]::ToBase64String($Bytes).TrimEnd("=").Replace("+", "-").Replace("/", "_")
}

foreach ($Name in @("POSTGRES_PASSWORD", "CHATBOT_LLM_API_KEY")) {
    $Pattern = "(?m)^" + [regex]::Escape($Name) + "=(?<value>[^\r\n]*)\r?$"
    $EntryMatches = [regex]::Matches($Contents, $Pattern)
    if ($EntryMatches.Count -ne 1) {
        throw "Expected exactly one '$Name' entry in .env. Review its structure without sharing secrets."
    }

    $ValueGroup = $EntryMatches[0].Groups["value"]
    if ($ValueGroup.Length -eq 0) {
        $Contents = $Contents.Insert($ValueGroup.Index, (New-UrlSafeSecret))
        $Changed = $true
    }
    elseif ($Name -eq "POSTGRES_PASSWORD" -and $ValueGroup.Value -cnotmatch "^[A-Za-z0-9_-]+$") {
        throw "POSTGRES_PASSWORD must be URL-safe (letters, digits, '_' or '-'). The existing value was not changed."
    }
}

if ($Changed) {
    $Utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($ResolvedEnvPath, $Contents, $Utf8WithoutBom)
}

Write-Host "Development environment verified. Existing non-empty credentials were preserved; no secrets displayed."
