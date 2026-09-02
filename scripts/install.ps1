$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

if (-not (Get-Command py.exe -ErrorAction SilentlyContinue)) {
    throw 'Python Launcher is missing. Install Python 3.11 or newer from python.org.'
}
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    throw 'Node.js/npm is missing. Install Node.js 22.13 or newer from nodejs.org.'
}
if (-not (Get-Command ollama.exe -ErrorAction SilentlyContinue)) {
    Write-Warning 'Ollama was not found. Install it before using AI features.'
}

if (-not (Test-Path '.env')) {
    Copy-Item '.env.example' '.env'
}

py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
npm install

Write-Host 'Installation complete. Start with .\Start-MailOrganizer.ps1' -ForegroundColor Green
