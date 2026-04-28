#!/bin/bash
# azdopal installation script
set -e

echo "=== azdopal setup ==="
echo ""

# Check Python
if ! command -v python3 &>/dev/null; then
  echo "❌ python3 not found. Please install Python 3.10+ first."
  exit 1
fi
echo "✓ Python: $(python3 --version)"

# Check Node
if ! command -v node &>/dev/null; then
  echo "❌ node not found. Please install Node.js 18+ first."
  exit 1
fi
echo "✓ Node: $(node --version)"

# Check npm
if ! command -v npm &>/dev/null; then
  echo "❌ npm not found. Please install npm first."
  exit 1
fi
echo "✓ npm: $(npm --version)"

echo ""
echo "--- Creating Python virtual environment ---"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  echo "✓ Created venv at ./.venv"
else
  echo "✓ .venv already exists"
fi

# Activate venv
source .venv/bin/activate
echo "✓ Activated venv"

echo ""
echo "--- Installing Python dependencies ---"
pip install --upgrade pip -q
pip install -r requirements.txt -q
pip install fastapi uvicorn -q
echo "✓ Python packages installed"

echo ""
echo "--- Installing UI dependencies ---"
cd web/ui
npm install
cd ../..
echo "✓ UI packages installed"

echo ""
echo "--- Setting up environment ---"
if [ ! -f .env ]; then
  cp .env.example .env
  echo "✓ Created .env from .env.example"
  echo "⚠️  Edit .env and fill in your Azure DevOps credentials:"
  echo "   ADO_ORG, ADO_PROJECT, ADO_PAT"
else
  echo "✓ .env already exists"
fi

echo ""
echo "--- Initializing database ---"
python -c "from db import init_db; init_db(); print('✓ Database initialized (azdopal.db)')"

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit .env with your Azure DevOps credentials"
echo "  2. Activate the venv:  source .venv/bin/activate"
echo "  3. Sync reference data:"
echo "     python fetch.py sync-teams"
echo "     python fetch.py sync-team-members"
echo "     python fetch.py sync-sprints"
echo "  4. Fetch data:"
echo "     python fetch.py work-items --sprint 107"
echo "     python fetch.py engineer --sprint 107"
echo "  5. Start the web UI:"
echo "     ./start.sh"
echo "     Open http://localhost:5173"
