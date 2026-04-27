# azdopal

A tool for fetching and visualizing Azure DevOps project stats — commits, PRs, work items, sprints, and team activity — stored in a local SQLite database with a React web UI.

## Setup

### 1. Create a Personal Access Token (PAT)

1. Sign in to [dev.azure.com](https://dev.azure.com)
2. Click your profile icon (top right) → **Personal access tokens**
3. Click **New Token** and select these scopes:
   - **Code** → Read
   - **Analytics** → Read (optional)
   - **Project and Team** → Read
   - **Work Items** → Read
4. Copy the token

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```
ADO_ORG=your-organization
ADO_PROJECT=your-project
ADO_PAT=your-pat-token
ADO_TEAM=your-team-name        # optional, for sprint sync fallback
ADO_REPO=your-repo-name        # optional, only for single-repo commands
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
pip install fastapi uvicorn      # for the web UI
cd web/ui && npm install         # for the React frontend
```

## Quick Start

```bash
# 1. Sync reference data from ADO
python3 fetch.py sync-teams
python3 fetch.py sync-team-members
python3 fetch.py sync-sprints

# 2. Fetch work items for a sprint
python3 fetch.py work-items --sprint 107

# 3. Fetch commits & PRs
python3 fetch.py engineer --sprint 107 --namespaces "Sports.*,Racing.*"

# 4. Start the web UI
./start.sh
# Open http://localhost:5173
```

## CLI Commands

### fetch.py — Pull data from Azure DevOps into the DB

| Command | Description |
|---|---|
| `fetch.py engineer` | Fetch commits & PRs for engineers across repos |
| `fetch.py work-items` | Fetch work items (stories, tasks, bugs) for a sprint |
| `fetch.py sync-teams` | Sync all teams from ADO |
| `fetch.py sync-team-members` | Sync team members (uses capacity data) |
| `fetch.py sync-sprints` | Sync sprint/iteration definitions |
| `fetch.py list-sprints` | List all synced sprints |
| `fetch.py list-teams` | List all synced teams |
| `fetch.py backfill-periods` | Replace date-based periods with sprint names |
| `fetch.py prs` | Fetch PR metrics for a single configured repo |
| `fetch.py commits` | Fetch commit stats for a single configured repo |
| `fetch.py split-repos` | Split repos.json into per-namespace files |
| `fetch.py dedup-repos` | Remove duplicates from repos.json |

### view.py — Query the local database

| Command | Description |
|---|---|
| `view.py summary` | Summary table of commits & PRs per engineer |
| `view.py commits` | List commits for an engineer |
| `view.py prs` | List PRs for an engineer |
| `view.py work-items` | List work items with hierarchy |

### Common options

All fetch and view commands support:
- `--sprint 107` or `--sprint "Iteration 107"` — use sprint dates from DB
- `--from dd-mm-yyyy --to dd-mm-yyyy` — explicit date range
- `--team "Team Name"` — scope to a specific team

### Examples

```bash
# Fetch work items for all teams in sprint 107
python3 fetch.py work-items --sprint 107

# Fetch work items for a specific team
python3 fetch.py work-items --sprint 107 --team "My Team"

# Fetch commits & PRs for specific repo namespaces
python3 fetch.py engineer --sprint 107 --namespaces "Sports.*,FrontEnd"

# View summary
python3 view.py summary --sprint 107

# View work items for a team
python3 view.py work-items --sprint 107 --team "My Team"

# View commits for an engineer
python3 view.py commits --sprint 107 --eng john.doe
```

## Web UI

Start both servers with one command:

```bash
./start.sh
```

Or manually:

```bash
# Terminal 1 — API (port 8000)
uvicorn web.api.main:app --reload --port 8000

# Terminal 2 — UI (port 5173)
cd web/ui && npm run dev
```

Open http://localhost:5173

### Views

- **Summary** — commits and PRs per engineer for a sprint. Click any row to drill into engineer detail.
- **Engineer Detail** — tabs for commits, PRs, and work items for a specific engineer.
- **Work Items** — all stories, tasks, and bugs for a sprint/team with:
  - Parent-child hierarchy (collapsible)
  - Owner shown on each item
  - Sprint span indicator (how many sprints an item has been active)
  - Spillover detection (badge showing which sprint an item spilled from)
  - Linked PRs
  - Filters: engineer, type, state, spilled/not-spilled, sprint span
  - Summary table showing story/bug counts by status

## Database

All data is stored in `azdopal.db` (SQLite).

### Tables

| Table | Description |
|---|---|
| `commits` | Individual commits with message, branch, date, url |
| `pull_requests` | Individual PRs with status, branches, review time, url |
| `work_items` | Work items with type, state, story points, estimates, parent_id |
| `work_item_prs` | Links between work items and PRs |
| `engineer_activity` | Summary counts per engineer/repo/branch/period |
| `repos` | Repo registry for pattern-based filtering |
| `sprints` | Sprint definitions with dates, per team |
| `teams` | Team registry |
| `team_members` | Team membership |
| `scanned_repos` | Resume tracking — which repos are done for a period |

### Example queries

```bash
# All work items for a sprint
sqlite3 azdopal.db "SELECT id, type, state, title FROM work_items WHERE period='Iteration 107'"

# Commits by engineer
sqlite3 azdopal.db "SELECT repo, branch, message FROM commits WHERE engineer_email LIKE '%john.doe%' AND period='Iteration 107'"

# Spilled stories
sqlite3 azdopal.db "SELECT id, title, state FROM work_items WHERE period='Iteration 107' AND activated_date IS NOT NULL AND state NOT IN ('New','Closed','Removed')"
```

## Architecture

### Project structure

```
azdopal/
├── fetch.py                # CLI — fetch commands (ADO → DB)
├── view.py                 # CLI — view commands (DB → console)
├── common.py               # Shared helpers (date parsing, sprint resolution)
├── client.py               # Azure DevOps REST API client with retry/backoff
├── engineer_activity.py    # Core fetch logic — scans repos for commits & PRs
├── db.py                   # SQLite schema, migrations, upserts, queries
├── pr_metrics.py           # PR metrics for a single configured repo
├── commit_stats.py         # Commit stats for a single configured repo
├── start.sh                # Start both API and UI servers
├── web/
│   ├── api/
│   │   └── main.py         # FastAPI backend serving the SQLite DB
│   └── ui/                 # React + TypeScript + Vite frontend
│       └── src/
│           ├── App.tsx      # Layout, routing, sprint/team selectors
│           ├── api.ts       # API client and TypeScript interfaces
│           └── pages/
│               ├── SprintSummary.tsx   # Summary table view
│               ├── EngineerDetail.tsx  # Engineer drill-down view
│               └── WorkItems.tsx       # Work items with hierarchy
├── .env                    # Local config (not committed)
├── .env.example            # Config template
├── requirements.txt        # Python dependencies
├── engineers.json          # Optional engineer email list
└── azdopal.db              # SQLite database
```

### Key design decisions

**Repo cache & DB-based filtering**
Repos are cached locally and stored in the `repos` DB table. Glob patterns like `Sports.*` use SQLite's `GLOB` operator for fast filtering.

**Single-pass bulk fetch**
When fetching for multiple engineers, all repos are scanned once and results partitioned by email client-side.

**Resume on interruption**
Each repo is written to DB immediately after scanning. The `scanned_repos` table tracks progress. Re-running resumes from where it left off.

**Sprint-based periods**
All data is keyed by sprint name (e.g. "Iteration 107") rather than date ranges. The `backfill-periods` command migrates old date-based periods.

**Team filtering via area_path**
Team filtering uses ADO area paths rather than team membership API, which is more reliable for matching the ADO board view.

**Spillover detection**
A story is marked as "spilled" if it existed in the previous sprint in a non-closed state.

**Sprint span calculation**
Counts how many sprints overlap with the item's active period (activated_date to resolved_date or current sprint end). Falls back to created_date if not yet activated.

### Data flow

```
Azure DevOps REST API
    │
    ▼
client.py          ← auth, retries, pagination, POST for WIQL
    │
    ▼
fetch.py           ← orchestrates fetching, writes to DB per-repo/per-item
    │
    ├──▶ db.py     ← upserts commits, PRs, work items, sprints, teams
    │
    ├──▶ view.py   ← CLI queries against DB
    │
    └──▶ web/api/  ← FastAPI serves DB data to React UI
              │
              ▼
         web/ui/   ← React app with summary, detail, work items views
```

### Environment variables

| Variable | Required | Description |
|---|---|---|
| `ADO_ORG` | Yes | Organisation name (after `dev.azure.com/`) |
| `ADO_PROJECT` | Yes | Project name |
| `ADO_PAT` | Yes | Personal Access Token |
| `ADO_TEAM` | No | Default team name (fallback for sprint sync) |
| `ADO_REPO` | No | Default repo (for single-repo prs/commits commands) |
