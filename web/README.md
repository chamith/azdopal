# azdopal web

React + FastAPI web interface for azdopal.

## Start the API

```bash
cd azdopal
pip install fastapi uvicorn
uvicorn web.api.main:app --reload --port 8000
```

## Start the UI

```bash
cd azdopal/web/ui
npm install
npm run dev
```

Open http://localhost:5173

## Views

- **Summary** — commits and PRs per engineer for a sprint, click any row to drill in
- **Engineer Detail** — commits, PRs and work items for a specific engineer
- **Work Items** — all work items for a sprint/team with linked PRs, filterable by type/state/engineer
