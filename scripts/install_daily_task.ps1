param(
    [string]$TaskName = "Xiaoma News Daily Morning Brief",
    [string]$WatchdogTaskName = "Xiaoma News Morning Brief Watchdog",
    [string]$StartTime = "06:30"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $PSScriptRoot "run_daily_morning_brief.ps1"
$watchdog = Join-Path $PSScriptRoot "check_daily_morning_brief.ps1"
$powershell = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"

if (-not (Test-Path -LiteralPath $runner)) {
    throw "Runner script not found: $runner"
}
if (-not (Test-Path -LiteralPath $watchdog)) {
    throw "Watchdog script not found: $watchdog"
}

$action = New-ScheduledTaskAction `
    -Execute $powershell `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$runner`"" `
    -WorkingDirectory $root

$trigger = New-ScheduledTaskTrigger -Daily -At $StartTime
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -WakeToRun `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 90) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5)

$principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Limited

$task = New-ScheduledTask `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Generate, validate, archive, draft, commit, and publish Xiaoma News before 08:00."

Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null

$watchdogAction = New-ScheduledTaskAction `
    -Execute $powershell `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$watchdog`" -PrimaryTaskName `"$TaskName`"" `
    -WorkingDirectory $root

$watchdogTriggers = @(
    (New-ScheduledTaskTrigger -Daily -At "07:40"),
    (New-ScheduledTaskTrigger -Daily -At "07:50")
)
$watchdogSettings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -WakeToRun `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

$watchdogTask = New-ScheduledTask `
    -Action $watchdogAction `
    -Trigger $watchdogTriggers `
    -Settings $watchdogSettings `
    -Principal $principal `
    -Description "Check Xiaoma News at 07:40, recover if needed, and alert at 07:50."

Register-ScheduledTask -TaskName $WatchdogTaskName -InputObject $watchdogTask -Force | Out-Null

$registered = Get-ScheduledTask -TaskName $TaskName
$info = Get-ScheduledTaskInfo -TaskName $TaskName
$registeredWatchdog = Get-ScheduledTask -TaskName $WatchdogTaskName
$watchdogInfo = Get-ScheduledTaskInfo -TaskName $WatchdogTaskName

@(
    [pscustomobject]@{
        TaskName = $registered.TaskName
        State = $registered.State
        NextRunTime = $info.NextRunTime
        LastRunTime = $info.LastRunTime
        WakeToRun = $registered.Settings.WakeToRun
        StartWhenAvailable = $registered.Settings.StartWhenAvailable
        Command = $registered.Actions.Execute
        Arguments = $registered.Actions.Arguments
    },
    [pscustomobject]@{
        TaskName = $registeredWatchdog.TaskName
        State = $registeredWatchdog.State
        NextRunTime = $watchdogInfo.NextRunTime
        LastRunTime = $watchdogInfo.LastRunTime
        WakeToRun = $registeredWatchdog.Settings.WakeToRun
        StartWhenAvailable = $registeredWatchdog.Settings.StartWhenAvailable
        Command = $registeredWatchdog.Actions.Execute
        Arguments = $registeredWatchdog.Actions.Arguments
    }
) | Format-List
