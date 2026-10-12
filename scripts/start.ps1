[CmdletBinding()]
param(
    [int]$TimeoutSeconds = 180,
    [int]$Port = 8080
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $projectRoot ".env"
$envExample = Join-Path $projectRoot ".env.example"
$healthUrl = "http://localhost:$Port/healthz"

Push-Location $projectRoot
try {
    docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Desktop is not ready. Start Docker Desktop and wait for 'Engine running'."
    }

    if (-not (Test-Path -LiteralPath $envFile)) {
        Copy-Item -LiteralPath $envExample -Destination $envFile
        Write-Host "Created .env from .env.example"
    }

    $env:AGENTFORGE_WEB_PORT = [string]$Port
    docker compose up --build --detach --remove-orphans --wait --wait-timeout $TimeoutSeconds
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose did not reach a healthy state."
    }

    $response = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 10
    if ($response.StatusCode -ne 200) {
        throw "AgentForge returned HTTP $($response.StatusCode) from $healthUrl."
    }

    Write-Host "AgentForge is healthy: http://localhost:$Port/"
}
catch {
    Write-Error $_
    Write-Host "`nContainer status:"
    docker compose ps --all
    Write-Host "`nRecent startup logs:"
    docker compose logs --no-color --tail=120 postgres redis api worker beat maintenance web
    exit 1
}
finally {
    Pop-Location
}
