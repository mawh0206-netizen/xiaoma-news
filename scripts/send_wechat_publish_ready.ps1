param(
    [switch]$Force
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $root "runtime"
$readyPath = Join-Path $runtime "wechat_publish_ready.json"
$python = "C:\Users\maweihua\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

& $python (Join-Path $PSScriptRoot "verify_wechat_publish_ready.py")
if ($LASTEXITCODE -ne 0) {
    throw "公众号发布放行校验失败，未发送成功邮件"
}

$ready = Get-Content -LiteralPath $readyPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($ready.status -ne "ready") {
    throw "公众号发布状态不是ready，未发送成功邮件"
}
if ($ready.email_sent -and -not $Force) {
    Write-Output "当天同一内容版本的发布成功邮件已发送，跳过重复发送。"
    exit 0
}

$subject = "【小马看世界】$($ready.date)公众号可以发布"
$body = (
    "小马看世界当日公众号已通过全部发布放行检查，可以发布。`r`n`r`n" +
    "日期：$($ready.date)`r`n" +
    "内容版本：$($ready.content_version_short)`r`n" +
    "第一条：$($ready.lead_title)`r`n" +
    "公众号草稿：当天同名仅1篇，14条正文已完整回读`r`n" +
    "阅读原文：线上14条与草稿的标题、顺序、新闻事实、小马观察和跟踪指标一致`r`n" +
    "其他检查：编辑复核通过、无逐条时间标签、无乱码`r`n`r`n" +
    "发布操作：请先刷新或重新打开公众号编辑器，确认第一条和内容版本无误后再发布。`r`n" +
    "收到本邮件后，当天阅读原文内容将冻结，不再修改。"
)

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "send_alert.ps1") `
    -Subject $subject -Body $body
if ($LASTEXITCODE -ne 0) {
    throw "公众号发布成功邮件发送失败，退出码：$LASTEXITCODE"
}

$ready.email_sent = $true
$ready | Add-Member -NotePropertyName email_sent_at -NotePropertyValue (Get-Date).ToString("o") -Force
$json = $ready | ConvertTo-Json -Depth 6
$utf8 = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($readyPath, $json + [Environment]::NewLine, $utf8)
Write-Output "公众号发布成功邮件已发送：$subject"
