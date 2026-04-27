#!/bin/bash
# Start both the API and UI servers for azdopal

trap 'kill 0' EXIT

echo "Starting API server on http://localhost:8000 ..."
uvicorn web.api.main:app --reload --port 8000 &

echo "Starting UI server on http://localhost:5173 ..."
cd web/ui && npm run dev &

wait
