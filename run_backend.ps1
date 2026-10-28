<#
  Runs the FastAPI backend and brings it back if it stops.

      powershell -ExecutionPolicy Bypass -File run_backend.ps1

  Why this exists: on a machine with little free RAM, Windows terminates
  processes under memory pressure, and uvicorn is a frequent casualty. The
  browser then shows "The FastAPI backend isn't running". This wrapper
  notices and restarts it within a second or two, so a memory spike becomes
  a blip instead of a dead application.

  It is not a substitute for having enough memory - it just means you do not
  have to restart by hand. Ctrl+C stops it for good.
#>

param(
    [int]$Port = 8000,
    [int]$MaxRestarts = 0     # 0 = unlimited
)

$ErrorActionPreference = "Continue"
$Root = $PSScriptRoot
$python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

$restarts = 0
$startedAt = Get-Date

Write-Host "Backend supervisor started. Ctrl+C to stop." -ForegroundColor Cyan
Write-Host "  http://127.0.0.1:$Port" -ForegroundColor Cyan

while ($true) {
    $launched = Get-Date
    Write-Host ("[{0}] starting uvicorn..." -f (Get-Date -Format "HH:mm:ss"))

    & $python -m uvicorn backend.main:app --host 127.0.0.1 --port $Port --log-level warning
    $code = $LASTEXITCODE

    $ranFor = [int]((Get-Date) - $launched).TotalSeconds
    $restarts++

    if ($code -eq 0) {
        Write-Host ("[{0}] backend exited cleanly after {1}s - not restarting." -f (Get-Date -Format "HH:mm:ss"), $ranFor) -ForegroundColor Green
        break
    }

    Write-Host ("[{0}] backend stopped (exit {1}) after {2}s - restart #{3}" -f `
        (Get-Date -Format "HH:mm:ss"), $code, $ranFor, $restarts) -ForegroundColor Yellow

    if ($ranFor -lt 10) {
        # Dying immediately usually means a real error (port in use, bad
        # config), not memory pressure. Back off so the log stays readable.
        Write-Host "  (it failed within 10s - check the error above; waiting 15s)" -ForegroundColor Red
        Start-Sleep -Seconds 15
    } else {
        Start-Sleep -Seconds 2
    }

    if ($MaxRestarts -gt 0 -and $restarts -ge $MaxRestarts) {
        Write-Host "Reached $MaxRestarts restarts; giving up." -ForegroundColor Red
        break
    }
}

$uptime = [int]((Get-Date) - $startedAt).TotalMinutes
Write-Host "Supervisor finished after $uptime minute(s), $restarts restart(s)."
