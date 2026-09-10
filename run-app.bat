@echo off
REM ============================================================================
REM  ResearchMind - start EVERYTHING with one command.
REM    1) Supporting services : Docker Desktop + SearXNG container + Ollama
REM                             (delegated to start-services.ps1)
REM    2) Backend             : FastAPI / uvicorn on :8000  (own window)
REM    3) Frontend            : Vite dev server on :5173    (own window)
REM
REM  Usage:  double-click run-app.bat   -or-   run-app.bat   from a terminal.
REM ============================================================================

REM Resolve the repo root (folder this .bat lives in) regardless of where it's run from.
set "ROOT=%~dp0"

REM --- sanity checks --------------------------------------------------------
if not exist "%ROOT%backend\.venv\Scripts\python.exe" (
  echo [ERROR] backend venv not found at backend\.venv
  echo         Create it:  cd backend ^&^& python -m venv .venv ^&^& .venv\Scripts\python -m pip install -r requirements.txt
  pause
  exit /b 1
)
if not exist "%ROOT%frontend\package.json" (
  echo [ERROR] frontend not found at frontend\package.json
  pause
  exit /b 1
)
if not exist "%ROOT%frontend\node_modules" (
  echo [WARN] frontend\node_modules missing - run "npm install" in frontend first.
)

REM --- 1) supporting services (Docker + SearXNG + Ollama) ------------------
echo ============================================================
echo  [1/3] Starting supporting services (SearXNG + Ollama)...
echo ============================================================
if exist "%ROOT%start-services.ps1" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%start-services.ps1"
  if errorlevel 1 (
    echo [WARN] start-services.ps1 reported a problem ^(e.g. Docker not ready^).
    echo        The app will still launch; live web search / LLM may be unavailable
    echo        until SearXNG and Ollama are up.
  )
) else (
  echo [WARN] start-services.ps1 not found - skipping SearXNG/Ollama startup.
)

REM --- 2) backend: uvicorn with reload on port 8000 -----------------------
echo.
echo ============================================================
echo  [2/3] Starting backend  -^> http://localhost:8000  (docs: /docs)
echo ============================================================
start "ResearchMind Backend" cmd /k "cd /d "%ROOT%backend" && .venv\Scripts\python -m uvicorn app.main:app --reload --port 8000"

REM --- 3) frontend: Vite dev server (proxies /api -> :8000) ----------------
echo.
echo ============================================================
echo  [3/3] Starting frontend -^> http://localhost:5173
echo ============================================================
start "ResearchMind Frontend" cmd /k "cd /d "%ROOT%frontend" && npm run dev"

echo.
echo All set. Backend and frontend run in their own windows.
echo Close those windows (or Ctrl+C inside each) to stop the servers.
echo Open the app at http://localhost:5173
