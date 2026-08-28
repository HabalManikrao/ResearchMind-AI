# Starts/verifies ResearchMind's supporting services (SearXNG + Ollama) on Windows.
# Run this once per boot, THEN start the backend and frontend in their own terminals:
#   backend : cd backend; .\.venv\Scripts\python -m uvicorn app.main:app --port 8000
#   frontend: cd frontend; npm run dev
#
# Usage:  powershell -ExecutionPolicy Bypass -File .\start-services.ps1

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

function Test-Url($url, $timeoutSec = 4) {
  try { Invoke-WebRequest -Uri $url -TimeoutSec $timeoutSec -UseBasicParsing | Out-Null; return $true }
  catch { return $false }
}

# --- 1. Docker + SearXNG ---
Write-Host "[1/3] Docker engine..." -NoNewline
$dockerOk = $false
try { docker info *> $null; $dockerOk = ($LASTEXITCODE -eq 0) } catch {}
if (-not $dockerOk) {
  Write-Host " starting Docker Desktop (this can take ~60s)..."
  $dd = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
  if (Test-Path $dd) { Start-Process $dd }
  for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep 3
    try { docker info *> $null; if ($LASTEXITCODE -eq 0) { $dockerOk = $true; break } } catch {}
  }
}
if ($dockerOk) { Write-Host " OK" } else { Write-Host " FAILED — start Docker Desktop manually"; exit 1 }

Write-Host "[2/3] SearXNG container..." -NoNewline
$running = (docker ps --filter "name=searxng" --filter "status=running" --format "{{.Names}}")
if ($running -eq "searxng") {
  Write-Host " already running"
} else {
  docker rm -f searxng *> $null
  $settings = Join-Path $root "searxng\settings.yml"
  docker run -d --name searxng -p 8080:8080 -v "${settings}:/etc/searxng/settings.yml:ro" searxng/searxng *> $null
  Write-Host " started"
  for ($i = 0; $i -lt 15; $i++) { Start-Sleep 2; if (Test-Url "http://localhost:8080/search?q=test&format=json") { break } }
}
if (Test-Url "http://localhost:8080/search?q=test&format=json") { Write-Host "      SearXNG JSON endpoint: OK" }
else { Write-Host "      SearXNG not responding yet — give it a few more seconds" }

# --- 3. Ollama ---
Write-Host "[3/3] Ollama server..." -NoNewline
if (Test-Url "http://localhost:11434/api/tags") {
  Write-Host " already running"
} else {
  Start-Process -WindowStyle Hidden -FilePath "ollama" -ArgumentList "serve"
  for ($i = 0; $i -lt 15; $i++) { Start-Sleep 2; if (Test-Url "http://localhost:11434/api/tags") { break } }
  if (Test-Url "http://localhost:11434/api/tags") { Write-Host " started" } else { Write-Host " FAILED — run 'ollama serve' manually" }
}

Write-Host ""
Write-Host "Supporting services ready. Now start the app:" -ForegroundColor Green
Write-Host "  backend : cd backend;  .\.venv\Scripts\python -m uvicorn app.main:app --port 8000"
Write-Host "  frontend: cd frontend; npm run dev   (http://localhost:5173)"
