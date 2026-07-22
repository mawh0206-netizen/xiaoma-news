param(
    [int]$MaxPushAttempts = 8,
    [int]$RetrySeconds = 20,
    [int]$DeployWaitSeconds = 300,
    [switch]$SkipEmail
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$git = "C:\Users\maweihua\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\git\cmd\git.exe"
$newsPath = Join-Path $root "data\news.json"
$siteDataUrl = "https://mawh0206-netizen.github.io/xiaoma-news/data/news.json"
$logPath = Join-Path $root "runtime\pipeline.log"

if (-not (Test-Path -LiteralPath $git)) {
    $git = (Get-Command git -ErrorAction Stop).Source
}

try {
    $pushed = $false
    for ($attempt = 1; $attempt -le $MaxPushAttempts; $attempt++) {
        "[$(Get-Date -Format o)] git push attempt $attempt/$MaxPushAttempts" | Add-Content -LiteralPath $logPath
        & $git -C $root push 2>&1 | Tee-Object -FilePath $logPath -Append
        if ($LASTEXITCODE -eq 0) { $pushed = $true; break }
        if ($attempt -lt $MaxPushAttempts) { Start-Sleep -Seconds $RetrySeconds }
    }
    if (-not $pushed) { throw "GitHub push failed after $MaxPushAttempts attempts" }

    $expected = (Get-Content -LiteralPath $newsPath -Raw -Encoding utf8 | ConvertFrom-Json).statusLabel
    $deadline = (Get-Date).AddSeconds($DeployWaitSeconds)
    $verified = $false
    do {
        try {
            $online = Invoke-RestMethod -Uri ("$siteDataUrl?v=" + [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()) -TimeoutSec 20
            if ($online.statusLabel -eq $expected) { $verified = $true; break }
        } catch {
            "[$(Get-Date -Format o)] deploy verification retry: $($_.Exception.Message)" | Add-Content -LiteralPath $logPath
        }
        Start-Sleep -Seconds 15
    } while ((Get-Date) -lt $deadline)

    if (-not $verified) { throw "GitHub Pages did not expose expected status '$expected' within $DeployWaitSeconds seconds" }
    "[$(Get-Date -Format o)] publish verified online: $expected" | Add-Content -LiteralPath $logPath
}
catch {
    $detail = "Xiaoma News publish failed.`r`n`r`nTime: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz')`r`nError: $($_.Exception.Message)`r`nLocal changes are preserved and the last successful website edition remains online."
    $detail | Add-Content -LiteralPath $logPath
    if (-not $SkipEmail) {
        & (Join-Path $PSScriptRoot "send_alert.ps1") -Subject "[Xiaoma News] Publish failed" -Body $detail
    }
    throw
}
