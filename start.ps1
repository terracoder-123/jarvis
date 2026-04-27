# J.A.R.V.I.S. v3 - Windows PowerShell Launcher

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "`n  +============================================================+" -ForegroundColor Cyan
Write-Host "  |   J.A.R.V.I.S. v3 - Stark Industries Command Center       |" -ForegroundColor Cyan
Write-Host "  |   Starting up systems...                                   |" -ForegroundColor Cyan
Write-Host "  +============================================================+`n" -ForegroundColor Cyan

# Check Python
Write-Host "  [+] Checking Python installation..." -ForegroundColor Yellow
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "  [!] Python not found. Install Python 3.11+ from python.org" -ForegroundColor Red
    Write-Host "      and tick 'Add Python to PATH' during install." -ForegroundColor Red
    exit 1
}

# Create venv if missing
if (-not (Test-Path "venv")) {
    Write-Host "  [+] First run - creating virtual environment..." -ForegroundColor Yellow
    python -m venv venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [!] Failed to create venv." -ForegroundColor Red
        exit 1
    }
}

# Activate venv
Write-Host "  [+] Activating virtual environment..." -ForegroundColor Yellow
& .\venv\Scripts\Activate.ps1

# Install dependencies
# Validate imports instead of checking one package folder so partial installs are recovered.
python -c "import fastapi, groq, edge_tts, google.genai" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [+] Installing dependencies (missing modules detected)..." -ForegroundColor Yellow
    pip install --upgrade pip -q
    pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [!] Dependency install failed." -ForegroundColor Red
        exit 1
    }
}

# Check .env
if (-not (Test-Path ".env")) {
    Write-Host "`n  [!] No .env file found. Creating one..." -ForegroundColor Yellow
    @"
GEMINI_API_KEY=your_gemini_key_here
GROQ_API_KEY=your_groq_key_here
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=your_livekit_api_key
LIVEKIT_API_SECRET=your_livekit_api_secret
HOST=127.0.0.1
PORT=8000
MCP_PORT=8001
"@ | Out-File ".env" -Encoding UTF8
    
    Write-Host "  [!] IMPORTANT - open .env and fill in your API keys:" -ForegroundColor Yellow
    Write-Host "      GEMINI_API_KEY   : https://aistudio.google.com/app/apikey [free]" -ForegroundColor Yellow
    Write-Host "      GROQ_API_KEY     : https://console.groq.com/keys [free]" -ForegroundColor Yellow
    Write-Host "      LIVEKIT_*        : https://cloud.livekit.io [free tier]" -ForegroundColor Yellow
    Write-Host "`n"
    notepad .env
    Write-Host "  [+] Saved. Starting JARVIS...`n" -ForegroundColor Yellow
}

Write-Host "  [1/2] Starting MCP Tool Server on port 8001..." -ForegroundColor Cyan
Start-Process -WindowStyle Minimized cmd -ArgumentList "/c", "cd `"$PSScriptRoot`" && .\venv\Scripts\activate.bat && python -m mcp_server.server"

Write-Host "  [+]   Waiting for MCP server to initialise..." -ForegroundColor Yellow
Start-Sleep -Seconds 3

Write-Host "  [2/2] Starting main server on port 8000..." -ForegroundColor Cyan
Write-Host "`n  Open in browser: http://127.0.0.1:8000`n" -ForegroundColor Green

python -m backend.server

Read-Host "Press Enter to exit"
