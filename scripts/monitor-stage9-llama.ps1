# Stage 9: read-only Windows CPU/RAM sampling of a running local llama-server process.
# ASCII-only source for compatibility with Windows PowerShell 5.1.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 2147483647)]
    [int]$ProcessId,

    [ValidateRange(1, 3600)]
    [int]$DurationSeconds = 120,

    [ValidateRange(1, 30)]
    [int]$IntervalSeconds = 1,

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$OutputPath
)

$ErrorActionPreference = "Stop"
$OutputPath = [IO.Path]::GetFullPath($OutputPath)
if (Test-Path -LiteralPath $OutputPath) {
    throw "Output already exists; use a new file to preserve previous measurements."
}
$Folder = Split-Path -Path $OutputPath -Parent
if (-not (Test-Path -LiteralPath $Folder -PathType Container)) {
    throw "Output folder does not exist."
}
$Rows = New-Object System.Collections.ArrayList
$LogicalProcessors = [Environment]::ProcessorCount
$Start = Get-Date
$Prior = $null
while (((Get-Date) - $Start).TotalSeconds -le $DurationSeconds) {
    $Process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($null -eq $Process) {
        if ($Rows.Count -eq 0) {
            throw "Process was not running at the first sample."
        }
        break
    }
    $Moment = [DateTime]::UtcNow
    $CpuSeconds = [double]$Process.CPU
    $CpuPercent = $null
    if ($null -ne $Prior) {
        $Interval = ($Moment - $Prior.Moment).TotalSeconds
        if ($Interval -gt 0) {
            $CpuPercent = [math]::Round(
                [math]::Max(0, ($CpuSeconds - $Prior.CpuSeconds)) * 100 /
                ($Interval * $LogicalProcessors), 2
            )
        }
    }
    $Row = [PSCustomObject]@{
        TimestampUtc = $Moment.ToString("o")
        ProcessId = $ProcessId
        CpuSecondsCumulative = [math]::Round($CpuSeconds, 3)
        CpuPercentOfTotalLogicalCapacity = $CpuPercent
        WorkingSetMiB = [math]::Round($Process.WorkingSet64 / 1MB, 2)
        PeakWorkingSetMiBSinceLaunch = [math]::Round($Process.PeakWorkingSet64 / 1MB, 2)
    }
    [void]$Rows.Add($Row)
    $Prior = @{ Moment = $Moment; CpuSeconds = $CpuSeconds }
    if (((Get-Date) - $Start).TotalSeconds -ge $DurationSeconds) { break }
    Start-Sleep -Seconds $IntervalSeconds
}
# No process arguments, model text, token, key or environment values are recorded.
$Rows | Export-Csv -LiteralPath $OutputPath -NoTypeInformation -Encoding UTF8
Write-Output "Recorded $($Rows.Count) resource samples."
