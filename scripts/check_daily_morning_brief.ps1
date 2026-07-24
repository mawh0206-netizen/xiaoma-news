param(
    [string]$PrimaryTaskName = "Xiaoma News Daily Morning Brief"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$root = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $root "runtime"
$statePath = Join-Path $runtime "daily_success.json"
$logPath = Join-Path $runtime "daily_watchdog.log"
$alertMarkerPath = Join-Path $runtime "daily_watchdog_alert.json"
$powershell = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$today = (Get-Date).Date
$dateKey = $today.ToString("yyyy-MM-dd")
$expectedDatePattern = "^{0}\D+{1}\D+{2}\D+" -f $today.Year, $today.Month, $today.Day
$alertTime = $today.AddHours(7).AddMinutes(50)
$utf8 = New-Object System.Text.UTF8Encoding($false)

New-Item -ItemType Directory -Force -Path $runtime | Out-Null

function Write-WatchdogLog {
    param([string]$Message)
    $line = "[$(Get-Date -Format o)] $Message"
    [System.IO.File]::AppendAllText($logPath, $line + [Environment]::NewLine, $utf8)
    Write-Output $line
}

function Get-HealthFailures {
    $failures = New-Object System.Collections.Generic.List[string]

    try {
        if (-not (Test-Path -LiteralPath $statePath)) {
            $failures.Add("success marker missing")
        }
        else {
            $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($state.date -ne $dateKey -or $state.status -ne "success") {
                $failures.Add("success marker is stale or failed")
            }
        }
    }
    catch {
        $failures.Add("success marker is unreadable")
    }

    foreach ($item in @(
        @{ Name = "website"; Path = (Join-Path $root "data\news.json") },
        @{ Name = "WeChat"; Path = (Join-Path $runtime "wechat_news.json") }
    )) {
        try {
            $data = Get-Content -LiteralPath $item.Path -Raw -Encoding UTF8 | ConvertFrom-Json
            $label = [string]$data.dateLabel
            if ($label -notmatch $expectedDatePattern) {
                $failures.Add("$($item.Name) local date is stale")
            }
        }
        catch {
            $failures.Add("$($item.Name) local data is unreadable")
        }
    }

    try {
        $url = "https://mawh0206-netizen.github.io/xiaoma-news/data/news.json?v=$([DateTimeOffset]::UtcNow.ToUnixTimeSeconds())"
        $response = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 20
        $online = $response.Content | ConvertFrom-Json
        $onlineLabel = [string]$online.dateLabel
        if ($onlineLabel -notmatch $expectedDatePattern) {
            $failures.Add("website online date is stale")
        }
    }
    catch {
        $failures.Add("website online check failed")
    }

    return $failures
}

function Test-AlertAlreadySent {
    if (-not (Test-Path -LiteralPath $alertMarkerPath)) { return $false }
    try {
        $marker = Get-Content -LiteralPath $alertMarkerPath -Raw -Encoding UTF8 | ConvertFrom-Json
        return $marker.date -eq $dateKey
    }
    catch {
        return $false
    }
}

try {
    $failures = @(Get-HealthFailures)
    if ($failures.Count -eq 0) {
        Write-WatchdogLog "health check passed date=$dateKey"
        exit 0
    }

    Write-WatchdogLog "health check failed reasons=$($failures -join '; ')"
    $primary = Get-ScheduledTask -TaskName $PrimaryTaskName -ErrorAction Stop
    if ($primary.State -ne "Running") {
        Start-ScheduledTask -TaskName $PrimaryTaskName
        Write-WatchdogLog "primary task started for recovery"
    }
    else {
        Write-WatchdogLog "primary task is already running"
    }

    if ((Get-Date) -ge $alertTime -and -not (Test-AlertAlreadySent)) {
        $body = (
            "The daily briefing has not passed the 07:50 SLA checkpoint.`r`n`r`n" +
            "Date: $dateKey`r`nFailures: $($failures -join '; ')`r`n" +
            "The Windows watchdog has started or retained the recovery task.`r`n" +
            "Log: $logPath"
        )
        & $powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "send_alert.ps1") `
            -Subject "[Xiaoma News] 07:50 SLA warning" -Body $body
        $marker = @{
            date = $dateKey
            sent_at = (Get-Date).ToString("o")
            failures = $failures
        } | ConvertTo-Json -Depth 4
        [System.IO.File]::WriteAllText($alertMarkerPath, $marker + [Environment]::NewLine, $utf8)
        Write-WatchdogLog "07:50 SLA alert sent"
    }
    exit 1
}
catch {
    Write-WatchdogLog "watchdog failed error=$($_.Exception.Message)"
    exit 2
}
