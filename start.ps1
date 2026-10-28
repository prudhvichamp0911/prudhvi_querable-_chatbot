<#
  One command to run the whole project:
    powershell -ExecutionPolicy Bypass -File start.ps1

  1. makes sure VeloDB (Apache Doris) is up in Docker
  2. loads the datasets the first time
  3. starts the FastAPI backend   -> http://127.0.0.1:8000
  4. starts the Next.js frontend  -> http://localhost:3100
  5. opens the browser once the frontend answers
#>

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot

function Test-Port($port) {
    Test-NetConnection 127.0.0.1 -Port $port -InformationLevel Quiet -WarningAction SilentlyContinue
}

$python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

# ---- VeloDB (Apache Doris in Docker)
if (-not (Test-Port 9030)) {
    Write-Host "VeloDB is not running; starting the container..."

    try { docker info *> $null } catch {
        Write-Host "Docker is not running. Start Docker Desktop and run this script again." -ForegroundColor Red
        exit 1
    }

    # Doris's storage backend refuses to start unless the host allows enough
    # memory maps. On Docker Desktop this has to be set on the Linux VM.
    docker run --rm --privileged --pid=host alpine nsenter -t 1 -m -u -n -i `
        sysctl -w vm.max_map_count=2000000 *> $null

    Push-Location $Root
    docker compose up -d | Out-Null
    Pop-Location

    Write-Host "Waiting for VeloDB to accept connections (first boot takes 1-2 minutes)..."
    $deadline = (Get-Date).AddSeconds(240)
    while (-not (Test-Port 9030) -and (Get-Date) -lt $deadline) { Start-Sleep -Seconds 5 }
}

if (Test-Port 9030) {
    Write-Host "VeloDB   ok   127.0.0.1:9030" -ForegroundColor Green
} else {
    Write-Host "VeloDB did not come up. Check: docker compose logs doris" -ForegroundColor Red
    exit 1
}

# ---- Data (only loads when the tables are empty)
Write-Host "Checking datasets..."
& $python -m velodb.load --if-empty
if ($LASTEXITCODE -ne 0) {
    Write-Host "Dataset load failed. Run it manually: python -m velodb.load" -ForegroundColor Yellow
}

# ---- Backend
if (Test-Port 8000) {
    Write-Host "Backend  ok   already running on :8000" -ForegroundColor Green
} else {
    Start-Process powershell.exe -WorkingDirectory $Root -ArgumentList @(
        "-NoExit", "-Command", "`$host.UI.RawUI.WindowTitle='Queryable backend'; & '$python' -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000")
    Write-Host "Backend  starting on http://127.0.0.1:8000"
}

# ---- Frontend
$web = Join-Path $Root "openui_test"
if (Test-Port 3100) {
    Write-Host "Frontend ok   already running on :3100" -ForegroundColor Green
} else {
    if (-not (Test-Path (Join-Path $web "node_modules"))) {
        Write-Host "Installing frontend packages (first run only)..."
        Push-Location $web; npm install; Pop-Location
    }
    Start-Process powershell.exe -WorkingDirectory $web -ArgumentList @(
        "-NoExit", "-Command", "`$host.UI.RawUI.WindowTitle='Queryable frontend'; npm run dev")
    Write-Host "Frontend starting on http://localhost:3100"
}

$deadline = (Get-Date).AddSeconds(90)
while (-not ((Test-Port 3100) -and (Test-Port 8000)) -and (Get-Date) -lt $deadline) { Start-Sleep -Seconds 1 }
Start-Process "http://localhost:3100"
