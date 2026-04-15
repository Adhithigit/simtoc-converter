#!/bin/bash
# ================================================
# SimToC — One-click local startup script
# Run this file to start SimToC offline
# Usage: bash run_local.sh
# ================================================

set -e

# Colors
GREEN='\033[0;32m'
CYAN='\033[0;36m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo ""
echo -e "${CYAN}╔══════════════════════════════════════╗${NC}"
echo -e "${CYAN}║        SimToC — Offline Mode         ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════╝${NC}"
echo ""

# ── Find project root ────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d "backend" ] || [ ! -d "frontend" ]; then
    echo -e "${RED}ERROR: Run this script from the simtoc-converter folder${NC}"
    echo "       cd path/to/simtoc-converter && bash run_local.sh"
    exit 1
fi

# ── Check Python ─────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo -e "${RED}ERROR: Python 3 not found.${NC}"
    echo "Install from https://python.org/downloads"
    exit 1
fi

PYTHON_VER=$(python3 --version 2>&1)
echo -e "${GREEN}✓ Python:${NC} $PYTHON_VER"

# ── Setup virtual environment ────────────────────────────────────
VENV_DIR="backend/venv"

if [ ! -d "$VENV_DIR" ]; then
    echo -e "${YELLOW}⟳ Creating virtual environment...${NC}"
    python3 -m venv "$VENV_DIR"
fi

# Activate venv
source "$VENV_DIR/bin/activate" 2>/dev/null || \
    source "$VENV_DIR/Scripts/activate" 2>/dev/null || true

echo -e "${GREEN}✓ Virtual environment ready${NC}"

# ── Install dependencies ──────────────────────────────────────────
echo -e "${YELLOW}⟳ Checking dependencies...${NC}"

cd backend
pip install -q -r requirements.txt --no-warn-script-location
cd ..

echo -e "${GREEN}✓ Dependencies ready${NC}"

# ── Kill any existing backend on port 8080 ───────────────────────
if lsof -Pi :8080 -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo -e "${YELLOW}⟳ Stopping existing process on port 8080...${NC}"
    kill $(lsof -Pi :8080 -sTCP:LISTEN -t) 2>/dev/null || true
    sleep 1
fi

# Also try port 5001 as fallback
PORT=8080
if lsof -Pi :8080 -sTCP:LISTEN -t >/dev/null 2>&1; then
    PORT=5001
fi

# ── Update frontend to use local backend ─────────────────────────
SCRIPT_JS="frontend/script.js"
SCRIPT_JS_BAK="frontend/script.js.online.bak"

# Backup online version if not already done
if [ ! -f "$SCRIPT_JS_BAK" ]; then
    cp "$SCRIPT_JS" "$SCRIPT_JS_BAK"
fi

# Swap API URL to localhost
sed -i.tmp "s|const API = '.*'|const API = 'http://localhost:$PORT'|g" "$SCRIPT_JS"
rm -f "$SCRIPT_JS.tmp"

echo -e "${GREEN}✓ Frontend configured for offline (port $PORT)${NC}"

# ── Start backend ─────────────────────────────────────────────────
echo ""
echo -e "${CYAN}⟳ Starting backend on port $PORT...${NC}"

cd backend
PORT=$PORT python3 app.py &
BACKEND_PID=$!
cd ..

# Wait for backend to start
sleep 2

# Check backend is running
if ! kill -0 $BACKEND_PID 2>/dev/null; then
    echo -e "${RED}ERROR: Backend failed to start. Check the error above.${NC}"
    exit 1
fi

# Verify health endpoint
for i in 1 2 3 4 5; do
    if curl -s "http://localhost:$PORT/health" | grep -q "running" 2>/dev/null; then
        echo -e "${GREEN}✓ Backend is running!${NC}"
        break
    fi
    sleep 1
done

# ── Open frontend in browser ──────────────────────────────────────
FRONTEND_PATH="$(pwd)/frontend/index.html"

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  SimToC is ready!                        ║${NC}"
echo -e "${GREEN}║                                          ║${NC}"
echo -e "${GREEN}║  Open in browser:                        ║${NC}"
echo -e "${GREEN}║  file://$FRONTEND_PATH  ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════╝${NC}"
echo ""
echo -e "  Press ${RED}Ctrl+C${NC} to stop the server"
echo ""

# Auto-open browser
if command -v open &>/dev/null; then
    open "file://$FRONTEND_PATH"          # macOS
elif command -v xdg-open &>/dev/null; then
    xdg-open "file://$FRONTEND_PATH"     # Linux
elif command -v start &>/dev/null; then
    start "file://$FRONTEND_PATH"        # Windows Git Bash
fi

# ── Wait for Ctrl+C ───────────────────────────────────────────────
cleanup() {
    echo ""
    echo -e "${YELLOW}⟳ Shutting down SimToC...${NC}"
    kill $BACKEND_PID 2>/dev/null || true

    # Restore online script.js
    if [ -f "$SCRIPT_JS_BAK" ]; then
        cp "$SCRIPT_JS_BAK" "$SCRIPT_JS"
        echo -e "${GREEN}✓ Frontend restored to online mode${NC}"
    fi

    echo -e "${GREEN}✓ Stopped. Goodbye!${NC}"
    exit 0
}

trap cleanup INT TERM
wait $BACKEND_PID