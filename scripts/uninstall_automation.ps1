$ErrorActionPreference = "Stop"
$taskName = "Local Mail Organizer Agent"
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}
Write-Host "Local Mail Organizer Agent removed. Mailbox rules and audit history were retained."
