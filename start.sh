#!/bin/bash
# Start both the API and UI servers for azdopal

PIDS=()

cleanup() {
  echo ""
  echo "Shutting down..."
  for pid in "${PIDS[@]}"; do
    kill -TERM "$pid" 2>/dev/null
    wait "$pid" 2>/dev/null
  done
  # Force-kill anything still on our ports
  lsof -ti :8000 | xargs kill -9 2>/dev/null
  lsof -ti :5173 | xargs kill -9 2>/dev/null
  exit 0
}

trap cleanup INT TERM

# Activate venv
source .venv/bin/activate

echo "Starting API server on http://localhost:8000 ..."
python -m uvicorn web.api.main:app --reload --port 8000 &
PIDS+=($!)

echo "Starting UI server on http://localhost:5173 ..."
cd web/ui && npm run dev &
PIDS+=($!)

wait
