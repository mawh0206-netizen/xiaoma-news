param(
    [Parameter(Mandatory=$true)][string]$Subject,
    [Parameter(Mandatory=$true)][string]$Body,
    [string]$SettingsPath = "D:\Codex\miit_smtp_settings.json",
    [string]$CredentialPath = "D:\Codex\miit_smtp_credential.xml"
)
$ErrorActionPreference = "Stop"
$settings = Get-Content -LiteralPath $SettingsPath -Raw | ConvertFrom-Json
$credential = Import-Clixml -LiteralPath $CredentialPath
$message = [System.Net.Mail.MailMessage]::new()
$smtp = [System.Net.Mail.SmtpClient]::new([string]$settings.host, [int]$settings.port)
try {
    $message.From = [System.Net.Mail.MailAddress]::new([string]$settings.sender)
    $message.To.Add([string]$settings.recipient)
    $message.Subject = $Subject
    $message.SubjectEncoding = [System.Text.Encoding]::UTF8
    $message.Body = $Body
    $message.BodyEncoding = [System.Text.Encoding]::UTF8
    $smtp.EnableSsl = [bool]$settings.enable_ssl
    $smtp.UseDefaultCredentials = $false
    $smtp.Credentials = $credential.GetNetworkCredential()
    $smtp.Send($message)
}
finally {
    $message.Dispose()
    $smtp.Dispose()
}
