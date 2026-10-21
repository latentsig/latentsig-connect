#!/usr/bin/env pwsh
param()

$ErrorActionPreference = 'Stop'

if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw 'PowerShell 7 or later is required. Install it from https://learn.microsoft.com/powershell/scripting/install/installing-powershell.'
}

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $repositoryRoot 'backend'
$venvRoot = Join-Path $backendRoot '.venv'
$venvPython = if ($IsWindows) {
    Join-Path $venvRoot 'Scripts/python.exe'
} else {
    Join-Path $venvRoot 'bin/python'
}

if (-not (Test-Path -LiteralPath (Join-Path $backendRoot '.env'))) {
    Copy-Item -LiteralPath (Join-Path $backendRoot '.env.example') -Destination (Join-Path $backendRoot '.env')
    Write-Host 'Created backend/.env from the example. Add OPENROUTER_API_KEY there to enable card scanning.'
}

if (-not (Test-Path -LiteralPath $venvPython)) {
    $bootstrapCommand = $null
    $bootstrapPrefix = @()

    if ($IsWindows -and (Get-Command py -ErrorAction SilentlyContinue)) {
        $bootstrapCommand = (Get-Command py).Source
        $bootstrapPrefix = @('-3')
    } else {
        $candidateNames = if ($IsWindows) { @('python3.11', 'python') } else { @('python3.11', 'python3', 'python') }
        foreach ($candidateName in $candidateNames) {
            $candidate = Get-Command $candidateName -ErrorAction SilentlyContinue
            if ($candidate) {
                $bootstrapCommand = $candidate.Source
                break
            }
        }
    }

    if (-not $bootstrapCommand) {
        throw 'Python 3.11 or later was not found. Install Python, then run this command again.'
    }

    $versionOutput = & $bootstrapCommand @bootstrapPrefix --version 2>&1
    if ($LASTEXITCODE -ne 0 -or $versionOutput -notmatch 'Python\s+(\d+)\.(\d+)') {
        throw "Could not read the Python version from '$bootstrapCommand'."
    }
    $pythonMajor = [int]$Matches[1]
    $pythonMinor = [int]$Matches[2]
    if ($pythonMajor -lt 3 -or ($pythonMajor -eq 3 -and $pythonMinor -lt 11)) {
        throw "Python 3.11 or later is required; found $versionOutput."
    }

    $venvArguments = $bootstrapPrefix + @('-m', 'venv', $venvRoot)
    & $bootstrapCommand @venvArguments
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not create the backend virtual environment.'
    }
}

function Invoke-BackendPython {
    param([Parameter(Mandatory)][string[]]$Arguments)

    & $venvPython @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Backend command failed: python $($Arguments -join ' ')"
    }
}

Push-Location $backendRoot
try {
    Write-Host 'Installing backend dependencies...'
    Invoke-BackendPython @('-m', 'pip', 'install', '--upgrade', 'pip')
    Invoke-BackendPython @('-m', 'pip', 'install', '-r', 'requirements.txt')

    Write-Host 'Applying database migrations...'
    Invoke-BackendPython @('-m', 'alembic', 'upgrade', 'head')

    Write-Host 'Starting the API at http://127.0.0.1:8000'
    Write-Host 'Readiness: http://127.0.0.1:8000/health/ready'
    & $venvPython -m uvicorn app.main:app --host 127.0.0.1 --port 8000
    if ($LASTEXITCODE -ne 0) {
        throw 'The FastAPI server stopped with an error.'
    }
} finally {
    Pop-Location
}
