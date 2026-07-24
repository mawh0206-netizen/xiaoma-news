param(
    [switch]$Force,
    [switch]$DryRun,
    [switch]$CheckOnly,
    [datetime]$TargetDate = (Get-Date).Date
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$root = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $root "runtime"
$logPath = Join-Path $runtime "daily_runner.log"
$statePath = Join-Path $runtime "daily_success.json"
$failurePath = Join-Path $runtime "daily_failure.json"
$python = "C:\Users\maweihua\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$git = "C:\Users\maweihua\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\git\cmd\git.exe"
$powershell = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$dateKey = $TargetDate.ToString("yyyy-MM-dd")
$deadline = $TargetDate.Date.AddHours(8)
$alertAt = $TargetDate.Date.AddHours(7).AddMinutes(50)
$utf8 = New-Object System.Text.UTF8Encoding($false)
$script:currentStage = "startup"
$script:lateAlertSent = $false

New-Item -ItemType Directory -Force -Path $runtime | Out-Null

function Write-RunLog {
    param([string]$Message)
    $line = "[$(Get-Date -Format o)] $Message"
    [System.IO.File]::AppendAllText($logPath, $line + [Environment]::NewLine, $utf8)
    Write-Output $line
}

function Write-State {
    param([string]$Path, [hashtable]$State)
    $json = $State | ConvertTo-Json -Depth 6
    [System.IO.File]::WriteAllText($Path, $json + [Environment]::NewLine, $utf8)
}

function Send-FailureAlert {
    param([string]$Subject, [string]$Body)
    try {
        & $powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "send_alert.ps1") -Subject $Subject -Body $Body
        Write-RunLog "SMTP alert sent: $Subject"
    }
    catch {
        Write-RunLog "SMTP alert failed: $($_.Exception.Message)"
    }
}

function Test-TodaySucceeded {
    if (-not (Test-Path -LiteralPath $statePath)) { return $false }
    try {
        $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
        return $state.date -eq $dateKey -and $state.status -eq "success"
    }
    catch {
        return $false
    }
}

function Assert-BeforeAlertThreshold {
    if ($CheckOnly -or $DryRun) { return }
    if ((Get-Date) -ge $alertAt -and -not $script:lateAlertSent) {
        $script:lateAlertSent = $true
        Send-FailureAlert -Subject "[Xiaoma News] 07:50 deadline warning" -Body (
            "The daily briefing has not completed by 07:50.`r`n`r`n" +
            "Date: $dateKey`r`nStage: $script:currentStage`r`n" +
            "The runner is still retrying. Check $logPath."
        )
    }
}

function Invoke-Step {
    param(
        [Parameter(Mandatory=$true)][string]$Name,
        [Parameter(Mandatory=$true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [int]$Attempts = 1,
        [int]$RetrySeconds = 15
    )
    $script:currentStage = $Name
    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        Assert-BeforeAlertThreshold
        Write-RunLog "stage=$Name attempt=$attempt/$Attempts started"
        $previousErrorAction = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            & $FilePath @Arguments 2>&1 | ForEach-Object { Write-RunLog "stage=$Name output=$_" }
            $exitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previousErrorAction
        }
        if ($exitCode -eq 0) {
            Write-RunLog "stage=$Name completed"
            return
        }
        Write-RunLog "stage=$Name failed exit_code=$exitCode"
        if ($attempt -lt $Attempts) { Start-Sleep -Seconds $RetrySeconds }
    }
    throw "$Name failed after $Attempts attempt(s)"
}

$mutex = New-Object System.Threading.Mutex($false, "Local\XiaomaNewsDailyMorningBrief")
$hasLock = $false

try {
    $hasLock = $mutex.WaitOne(0)
    if (-not $hasLock) {
        Write-RunLog "another daily runner instance is active; exiting"
        exit 0
    }

    Write-RunLog "daily run started date=$dateKey force=$Force dry_run=$DryRun check_only=$CheckOnly"

    if ((Test-TodaySucceeded) -and -not $Force) {
        Write-RunLog "today already has a success marker; no work required"
        exit 0
    }

    if (-not (Test-Path -LiteralPath $python)) { throw "Python executable not found: $python" }
    if (-not (Test-Path -LiteralPath $git)) { throw "Git executable not found: $git" }

    if ($CheckOnly) {
        Invoke-Step -Name "health_check_strict_validation" -FilePath $python -Arguments @(
            (Join-Path $PSScriptRoot "validate_news.py"), "--strict-details"
        )
        $checkNews = Get-Content -LiteralPath (Join-Path $root "data\news.json") -Raw -Encoding UTF8 | ConvertFrom-Json
        $checkWechat = Get-Content -LiteralPath (Join-Path $runtime "wechat_news.json") -Raw -Encoding UTF8 | ConvertFrom-Json
        if (@($checkNews.stories).Count -ne 45) { throw "health check expected 45 website stories" }
        if (@($checkWechat.stories).Count -ne 14) { throw "health check expected 14 WeChat stories" }
        Write-RunLog "health check passed website=45 wechat=14"
        return
    }

    Invoke-Step -Name "candidate_collection" -FilePath $powershell -Arguments @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        (Join-Path $PSScriptRoot "run_pipeline.ps1"), "-SkipEmail"
    ) -Attempts 3 -RetrySeconds 30

    Invoke-Step -Name "website_selection" -FilePath $python -Arguments @(
        (Join-Path $PSScriptRoot "prepare_daily_issue.py")
    ) -Attempts 2 -RetrySeconds 10

    Invoke-Step -Name "strict_validation" -FilePath $python -Arguments @(
        (Join-Path $PSScriptRoot "validate_news.py"), "--strict-details"
    )

    Invoke-Step -Name "website_archive" -FilePath $python -Arguments @(
        (Join-Path $PSScriptRoot "archive_issue.py")
    )

    Invoke-Step -Name "wechat_selection" -FilePath $python -Arguments @(
        (Join-Path $PSScriptRoot "prepare_wechat_issue.py")
    ) -Attempts 2 -RetrySeconds 10

    Invoke-Step -Name "wechat_generation" -FilePath $python -Arguments @(
        (Join-Path $PSScriptRoot "generate_wechat_article.py")
    )

    if (-not $DryRun) {
        Invoke-Step -Name "wechat_draft" -FilePath $python -Arguments @(
            (Join-Path $PSScriptRoot "upload_wechat_draft.py")
        ) -Attempts 3 -RetrySeconds 30
    }
    else {
        Write-RunLog "dry run: WeChat draft upload skipped"
    }

    Invoke-Step -Name "wechat_archive" -FilePath $python -Arguments @(
        (Join-Path $PSScriptRoot "archive_wechat_issue.py")
    )

    if (-not $DryRun) {
        $script:currentStage = "git_commit"
        & $git -C $root diff --cached --quiet
        if ($LASTEXITCODE -ne 0) {
            throw "pre-existing staged Git changes detected; refusing to mix them into the automated commit"
        }

        $websiteArchive = Join-Path $root "data\archive\$dateKey.json"
        $wechatArchive = Join-Path $root "data\wechat\$dateKey.json"
        $publishFiles = @(
            (Join-Path $root "data\news.json"),
            (Join-Path $root "data\archive\index.json"),
            $websiteArchive,
            (Join-Path $root "data\wechat\index.json"),
            $wechatArchive
        )
        & $git -C $root add -- @publishFiles
        if ($LASTEXITCODE -ne 0) { throw "git add failed" }

        & $git -C $root diff --cached --quiet
        if ($LASTEXITCODE -ne 0) {
            Invoke-Step -Name "git_commit" -FilePath $git -Arguments @(
                "-C", $root, "commit", "-m", "publish $dateKey morning brief"
            )
        }
        else {
            Write-RunLog "no publishable Git changes detected"
        }

        Invoke-Step -Name "website_publish" -FilePath $powershell -Arguments @(
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            (Join-Path $PSScriptRoot "publish_with_retry.ps1"), "-SkipEmail"
        ) -Attempts 2 -RetrySeconds 30
    }
    else {
        Write-RunLog "dry run: Git commit and website publish skipped"
    }

    $news = Get-Content -LiteralPath (Join-Path $root "data\news.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    $wechat = Get-Content -LiteralPath (Join-Path $runtime "wechat_news.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    $expectedDatePattern = "^{0}\D+{1}\D+{2}\D+" -f $TargetDate.Year, $TargetDate.Month, $TargetDate.Day
    $websiteDateLabel = [string]$news.dateLabel
    $wechatDateLabel = [string]$wechat.dateLabel
    if ($websiteDateLabel -notmatch $expectedDatePattern) {
        throw "website date validation failed after generation"
    }
    if ($wechatDateLabel -notmatch $expectedDatePattern) {
        throw "WeChat date validation failed after generation"
    }

    $head = (& $git -C $root rev-parse HEAD).Trim()
    $completedAt = Get-Date
    $state = @{
        status = "success"
        date = $dateKey
        started_by = "Windows Task Scheduler"
        completed_at = $completedAt.ToString("o")
        before_08_00 = ($completedAt -lt $deadline)
        website_stories = @($news.stories).Count
        wechat_stories = @($wechat.stories).Count
        commit = $head
        dry_run = [bool]$DryRun
    }
    Write-State -Path $statePath -State $state
    if (Test-Path -LiteralPath $failurePath) { Remove-Item -LiteralPath $failurePath -Force }
    Write-RunLog "daily run succeeded website=$($state.website_stories) wechat=$($state.wechat_stories) commit=$head"

    if ($completedAt -ge $deadline) {
        Send-FailureAlert -Subject "[Xiaoma News] Published after 08:00" -Body (
            "The daily briefing was published after the 08:00 SLA.`r`n`r`n" +
            "Date: $dateKey`r`nCompleted: $($completedAt.ToString('yyyy-MM-dd HH:mm:ss zzz'))`r`n" +
            "Check $logPath."
        )
    }
}
catch {
    $failedAt = Get-Date
    $failure = @{
        status = "failed"
        date = $dateKey
        failed_at = $failedAt.ToString("o")
        stage = $script:currentStage
        error = $_.Exception.Message
    }
    Write-State -Path $failurePath -State $failure
    Write-RunLog "daily run failed stage=$script:currentStage error=$($_.Exception.Message)"
    Send-FailureAlert -Subject "[Xiaoma News] Daily briefing failed" -Body (
        "The daily briefing automation failed.`r`n`r`n" +
        "Date: $dateKey`r`nTime: $($failedAt.ToString('yyyy-MM-dd HH:mm:ss zzz'))`r`n" +
        "Stage: $script:currentStage`r`nError: $($_.Exception.Message)`r`n" +
        "The last successful website edition remains online.`r`nLog: $logPath"
    )
    exit 1
}
finally {
    if ($hasLock) {
        try { $mutex.ReleaseMutex() } catch {}
    }
    $mutex.Dispose()
}
