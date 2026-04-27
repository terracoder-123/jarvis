#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════
#  J.A.R.V.I.S. — macOS / Linux Quick Launcher
#  Run with: ./start.sh
# ════════════════════════════════════════════════════════════

set -e
cd "$(dirname "$0")"

echo ""
echo "  ┌──────────────────────────────────────────────────────────┐"
echo "  │   J.A.R.V.I.S. — Starting up Stark Industries AI…        │"
echo "  └──────────────────────────────────────────────────────────┘"
echo ""

# Check Python 3
if ! command -v python3 &> /dev/null; then
    echo "  ✗ Python 3 not found."
    echo "    Install Python 3.11+ from https://www.python.org/downloads/"
    exit 1
fi

# Create venv if missing
if [ ! -d "venv" ]; then
    echo "  + First-time setup. Creating virtual environment…"
    python3 -m venv venv
fi

# Activate venv
source venv/bin/activate

# Install deps if needed
if ! python -c "import fastapi" &> /dev/null; then
    echo "  + Installing dependencies…"
    pip install --upgrade pip --quiet
    pip install -r requirements.txt
fi

# Check .env
if [ ! -f ".env" ]; then
    echo ""
    echo "  ! No .env file found."
    echo "  + Creating one from .env.example…"
    cp .env.example .env
    echo ""
    echo "  ! IMPORTANT: Open .env and paste your Gemini API key."
    echo "  ! Get a free key at: https://aistudio.google.com/app/apikey"
    echo ""
    # Open in default editor
    if command -v nano &> /dev/null; then
        read -p "  Press Enter to open .env in nano…"
        nano .env
    elif command -v vi &> /dev/null; then
        read -p "  Press Enter to open .env in vi…"
        vi .env
    else
        echo "  Edit .env manually, then re-run ./start.sh"
        exit 1
    fi
fi

# Launch
python -m backend.server
