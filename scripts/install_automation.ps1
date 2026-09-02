$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonw = Join-Path $projectRoot ".venv\Scripts\pythonw.exe"
if (-not (Test-Path -LiteralPath $pythonw)) {
    throw "Python environment not found. Run .\scripts\install.ps1 first."
}

$taskName = "Local Mail Organizer Agent"
$action = New-ScheduledTaskAction `
    -Execute $pythonw `
    -Argument "-m mail_organizer.automation" `
    -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Days 3650) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Description "Applies approved local mailbox filing rules." -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
Write-Host "Local Mail Organizer Agent installed and started."
Write-Host "Logs: $projectRoot\data\automation.log"
