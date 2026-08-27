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
$alertTime = $today.AddHours(8).AddMinutes(25)
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
            $failures.Add("成功标记缺失")
        }
        else {
            $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($state.date -ne $dateKey -or $state.status -ne "success") {
                $failures.Add("成功标记已过期或状态失败")
            }
        }
    }
    catch {
        $failures.Add("成功标记无法读取")
    }

    foreach ($item in @(
        @{ Name = "website"; Path = (Join-Path $root "data\news.json") },
        @{ Name = "WeChat"; Path = (Join-Path $runtime "wechat_news.json") }
    )) {
        try {
            $data = Get-Content -LiteralPath $item.Path -Raw -Encoding UTF8 | ConvertFrom-Json
            $label = [string]$data.dateLabel
            if ($label -notmatch $expectedDatePattern) {
                $failures.Add("$($item.Name) 本地日期不是当天")
            }
        }
        catch {
            $failures.Add("$($item.Name) 本地数据无法读取")
        }
    }

    try {
        $url = "https://mawh0206-netizen.github.io/xiaoma-news/data/news.json?v=$([DateTimeOffset]::UtcNow.ToUnixTimeSeconds())"
        $response = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 20
        $online = $response.Content | ConvertFrom-Json
        $onlineLabel = [string]$online.dateLabel
        if ($onlineLabel -notmatch $expectedDatePattern) {
            $failures.Add("线上网站日期不是当天")
        }
    }
    catch {
        $failures.Add("线上网站检查失败")
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
            "小马看世界每日晨报在08:25仍未通过发布巡检。`r`n`r`n" +
            "日期：$dateKey`r`n未通过项目：$($failures -join '；')`r`n" +
            "Windows守门任务已启动或保留补救流程，请关注后续结果。`r`n" +
            "日志：$logPath"
        )
        & $powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "send_alert.ps1") `
            -Subject "【小马看世界】08:25晨报发布风险提醒" -Body $body
        if ($LASTEXITCODE -ne 0) {
            throw "send_alert.ps1 exited with code $LASTEXITCODE"
        }
        $marker = @{
            date = $dateKey
            sent_at = (Get-Date).ToString("o")
            failures = $failures
        } | ConvertTo-Json -Depth 4
        [System.IO.File]::WriteAllText($alertMarkerPath, $marker + [Environment]::NewLine, $utf8)
        Write-WatchdogLog "08:25 SLA alert sent"
    }
    exit 1
}
catch {
    Write-WatchdogLog "watchdog failed error=$($_.Exception.Message)"
    exit 2
}
