@echo off
REM ==============================================================
REM  J.A.R.V.I.S. v3 - Windows Launcher
REM  STT: OpenAI Whisper  LLM: Gemini 2.5 Flash
REM  TTS: OpenAI nova     Tools: FastMCP / SSE
REM  Audio: LiveKit room
REM ==============================================================

setlocal
cd /d "%~dp0"

echo.
echo   +============================================================+
echo   ^|   J.A.R.V.I.S. v3 - Stark Industries Command Center       ^|
echo   ^|   Starting up systems...                                   ^|
echo   +============================================================+
echo.

REM Check Python
where python >nul 2>nul
if errorlevel 1 (
    echo   [!] Python not found. Install Python 3.11+ from python.org
    echo       and tick "Add Python to PATH" during install.
    pause & exit /b 1
)

REM Create venv if missing
if not exist "venv" (
    echo   [+] First run - creating virtual environment...
    python -m venv venv
    if errorlevel 1 (echo   [!] Failed to create venv. & pause & exit /b 1)
)

REM Activate
call venv\Scripts\activate.bat

REM Install / upgrade deps
if not exist "venv\Lib\site-packages\fastapi" (
    echo   [+] Installing dependencies (first run, may take 2-3 minutes)...
    pip install --upgrade pip -q
    pip install -r requirements.txt
    if errorlevel 1 (echo   [!] Dependency install failed. & pause & exit /b 1)
)

REM Check .env
if not exist ".env" (
    echo.
    echo   [!] No .env file found. Creating one...
    (
        echo GEMINI_API_KEY=your_gemini_key_here
        echo GROQ_API_KEY=your_groq_key_here
        echo LIVEKIT_URL=wss://your-project.livekit.cloud
        echo LIVEKIT_API_KEY=your_livekit_api_key
        echo LIVEKIT_API_SECRET=your_livekit_api_secret
        echo HOST=127.0.0.1
        echo PORT=8000
        echo MCP_PORT=8001
    ) > .env
    echo.
    echo   [!] All APIs are FREE - get your keys here:
    echo       GEMINI_API_KEY : https://aistudio.google.com/app/apikey  [free, no card]
    echo       GROQ_API_KEY   : https://console.groq.com/keys           [free, no card]
    echo       LIVEKIT_*      : https://cloud.livekit.io                [free tier]
    echo       (TTS uses Microsoft edge-tts - no key needed at all!)
    echo.
    notepad .env
    echo   [+] Saved. Starting JARVIS...
    echo.
)

echo   [1/2] Starting MCP Tool Server on port 8001...
start "JARVIS MCP Server" /min cmd /c "call venv\Scripts\activate.bat && python -m mcp_server.server"

echo   [+]   Waiting for MCP server to initialise...
timeout /t 3 /nobreak >nul

echo   [2/2] Starting main server on port 8000...
echo.
echo   Open in browser: http://127.0.0.1:8000
echo.
python -m backend.server

pause
