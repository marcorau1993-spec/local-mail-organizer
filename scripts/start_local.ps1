[CmdletBinding()]
param([switch]$NoBrowser)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$dataRoot = Join-Path $projectRoot 'data'
$apiExecutable = Join-Path $projectRoot '.venv\Scripts\uvicorn.exe'
$npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
$statePath = Join-Path $dataRoot 'launcher-state.json'
$apiUrl = 'http://127.0.0.1:8765/api/health'
$webUrl = 'http://localhost:3000/'

function Test-HttpEndpoint {
    param([Parameter(Mandatory)][string]$Uri)
    try {
        $response = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 500
    }
    catch { return $false }
}

function Wait-HttpEndpoint {
    param(
        [Parameter(Mandatory)][string]$Uri,
        [Parameter(Mandatory)][string]$Name,
        [int]$TimeoutSeconds = 45
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-HttpEndpoint -Uri $Uri) { return }
        Start-Sleep -Milliseconds 500
    }
    throw "$Name did not become ready. Check the log files in $dataRoot."
}

function Get-ListeningProcessId {
    param([Parameter(Mandatory)][int]$Port)
    $listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $listener) { return $null }
    return [int]$listener.OwningProcess
}

if (-not (Test-Path $apiExecutable)) {
    throw 'Python environment is missing. Run .\scripts\install.ps1 first.'
}
if ($null -eq $npmCommand) {
    throw 'Node.js/npm is missing. Install Node.js 22.13 or newer, then run .\scripts\install.ps1.'
}
if (-not (Test-Path (Join-Path $projectRoot 'node_modules'))) {
    throw 'Frontend dependencies are missing. Run .\scripts\install.ps1 first.'
}

New-Item -ItemType Directory -Path $dataRoot -Force | Out-Null

$apiHealthy = Test-HttpEndpoint $apiUrl
$webHealthy = Test-HttpEndpoint $webUrl
if ($apiHealthy -and $webHealthy) {
    Write-Host 'Local Mail Organizer is already running.' -ForegroundColor Green
    if (-not $NoBrowser) { Start-Process $webUrl }
    exit 0
}

foreach ($service in @(
    @{ Port = 8765; Healthy = $apiHealthy },
    @{ Port = 3000; Healthy = $webHealthy }
)) {
    if ($service.Healthy) { continue }
    $owner = Get-ListeningProcessId -Port $service.Port
    if ($null -ne $owner) {
        throw "Port $($service.Port) is already used by process $owner, but it is not a healthy Local Mail Organizer service."
    }
}

$apiLog = Join-Path $dataRoot 'api.log'
$apiErrorLog = Join-Path $dataRoot 'api-error.log'
$webLog = Join-Path $dataRoot 'web.log'
$webErrorLog = Join-Path $dataRoot 'web-error.log'

$apiProcess = $null
$webProcess = $null

try {
    if (-not $apiHealthy) {
        Write-Host 'Starting the private local API...' -ForegroundColor Cyan
        $apiProcess = Start-Process -FilePath $apiExecutable `
            -ArgumentList 'mail_organizer.api:app', '--host', '127.0.0.1', '--port', '8765' `
            -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput $apiLog -RedirectStandardError $apiErrorLog
    }
    Wait-HttpEndpoint -Uri $apiUrl -Name 'Local API'
    if (-not $webHealthy) {
        Write-Host 'Starting the web interface...' -ForegroundColor Cyan
        $webProcess = Start-Process -FilePath $npmCommand.Source `
            -ArgumentList 'run', 'dev' -WorkingDirectory $projectRoot `
            -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput $webLog -RedirectStandardError $webErrorLog
    }
    Wait-HttpEndpoint -Uri $webUrl -Name 'Web interface'

    [ordered]@{
        project_root = $projectRoot
        started_at = (Get-Date).ToUniversalTime().ToString('o')
        api_process_id = if ($null -ne $apiProcess) { $apiProcess.Id } else { $null }
        web_process_id = if ($null -ne $webProcess) { $webProcess.Id } else { $null }
        api_listener_id = if ($null -ne $apiProcess) { Get-ListeningProcessId -Port 8765 } else { $null }
        web_listener_id = if ($null -ne $webProcess) { Get-ListeningProcessId -Port 3000 } else { $null }
    } | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8

    Write-Host ''
    Write-Host 'Local Mail Organizer is ready.' -ForegroundColor Green
    Write-Host "Web interface: $webUrl"
    Write-Host 'Stop it later with: .\Stop-MailOrganizer.ps1'
    Write-Host "Logs: $dataRoot"
    if (-not $NoBrowser) { Start-Process $webUrl }
}
catch {
    if ($null -ne $apiProcess -and -not $apiProcess.HasExited) {
        Stop-Process -Id $apiProcess.Id -ErrorAction SilentlyContinue
    }
    if ($null -ne $webProcess -and -not $webProcess.HasExited) {
        Stop-Process -Id $webProcess.Id -ErrorAction SilentlyContinue
    }
    throw
}
