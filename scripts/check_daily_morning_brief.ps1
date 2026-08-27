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
$publishReadyPath = Join-Path $runtime "wechat_publish_ready.json"
$powershell = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$today = (Get-Date).Date
$dateKey = $today.ToString("yyyy-MM-dd")
$expectedDatePattern = "^{0}\D+{1}\D+{2}\D+" -f $today.Year, $today.Month, $today.Day
$alertTime = $today.AddHours(9)
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

    if ((Get-Date) -ge $alertTime) {
        try {
            if (-not (Test-Path -LiteralPath $publishReadyPath)) {
                $failures.Add("公众号发布放行状态缺失")
            }
            else {
                $ready = Get-Content -LiteralPath $publishReadyPath -Raw -Encoding UTF8 | ConvertFrom-Json
                if ($ready.date -ne $dateKey -or $ready.status -ne "ready" -or -not $ready.email_sent) {
                    $failures.Add("公众号完整校验或成功邮件尚未完成")
                }
            }
        }
        catch {
            $failures.Add("公众号发布放行状态无法读取")
        }
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
    $productionFailures = @($failures | Where-Object { $_ -notlike "公众号发布放行状态*" -and $_ -ne "公众号完整校验或成功邮件尚未完成" })
    if ($productionFailures.Count -gt 0) {
        $primary = Get-ScheduledTask -TaskName $PrimaryTaskName -ErrorAction Stop
        if ($primary.State -ne "Running") {
            Start-ScheduledTask -TaskName $PrimaryTaskName
            Write-WatchdogLog "primary task started for recovery"
        }
        else {
            Write-WatchdogLog "primary task is already running"
        }
    }
    else {
        Write-WatchdogLog "production passed; waiting for editorial publish readiness"
    }

    if ((Get-Date) -ge $alertTime -and -not (Test-AlertAlreadySent)) {
        $body = (
            "小马看世界每日晨报从08:00开始执行，到09:00仍未达到完整发布条件。`r`n`r`n" +
            "日期：$dateKey`r`n未通过项目：$($failures -join '；')`r`n" +
            "Windows守门任务已启动或保留补救流程，请关注后续结果。`r`n" +
            "日志：$logPath"
        )
        & $powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "send_alert.ps1") `
            -Subject "【小马看世界】09:00晨报超时提醒" -Body $body
        if ($LASTEXITCODE -ne 0) {
            throw "send_alert.ps1 exited with code $LASTEXITCODE"
        }
        $marker = @{
            date = $dateKey
            sent_at = (Get-Date).ToString("o")
            failures = $failures
        } | ConvertTo-Json -Depth 4
        [System.IO.File]::WriteAllText($alertMarkerPath, $marker + [Environment]::NewLine, $utf8)
        Write-WatchdogLog "09:00 timeout alert sent"
    }
    exit 1
}
catch {
    Write-WatchdogLog "watchdog failed error=$($_.Exception.Message)"
    exit 2
}
