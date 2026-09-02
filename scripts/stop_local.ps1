$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$statePath = Join-Path $projectRoot 'data\launcher-state.json'

if (-not (Test-Path $statePath)) {
    Write-Host 'No launcher state was found. The organizer may already be stopped.' -ForegroundColor Yellow
    exit 0
}

$state = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
if ([string]$state.project_root -ne $projectRoot) {
    throw 'The launcher state belongs to a different project directory.'
}

$targets = @(
    @{ Id = $state.api_process_id; Port = $null },
    @{ Id = $state.web_process_id; Port = $null },
    @{ Id = $state.api_listener_id; Port = 8765 },
    @{ Id = $state.web_listener_id; Port = 3000 }
) | Where-Object { $null -ne $_.Id }

$stopped = @{}
foreach ($target in $targets) {
    $processId = [int]$target.Id
    if ($stopped.ContainsKey($processId)) { continue }
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction SilentlyContinue
    if ($null -eq $process) { continue }
    $commandLine = [string]$process.CommandLine
    $ownsRecordedPort = $false
    if ($null -ne $target.Port) {
        $listener = Get-NetTCPConnection -State Listen -LocalPort ([int]$target.Port) -ErrorAction SilentlyContinue |
            Where-Object { $_.OwningProcess -eq $processId } | Select-Object -First 1
        $ownsRecordedPort = $null -ne $listener
    }
    if (-not $ownsRecordedPort -and $commandLine -notlike "*$projectRoot*") {
        Write-Warning "Process $processId no longer belongs to this project and was not stopped."
        continue
    }
    Stop-Process -Id $processId -ErrorAction SilentlyContinue
    $stopped[$processId] = $true
}

Remove-Item -LiteralPath $statePath -Force
Write-Host 'Local Mail Organizer has been stopped.' -ForegroundColor Green
