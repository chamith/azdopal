# azdopal

Fetch PR metrics and commit activity from Azure DevOps Git repos and store results in a local SQLite database.

## Setup

### 1. Create a Personal Access Token (PAT)

1. Sign in to [dev.azure.com](https://dev.azure.com)
2. Click your profile icon (top right) → **Personal access tokens**
3. Click **New Token**
4. Give it a name, set expiry, and under **Scopes** select:
   - **Code** → Read
5. Click **Create** and copy the token — you won't see it again

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and fill in your values:

```
ADO_ORG=your-organization        # the part after dev.azure.com/
ADO_PROJECT=your-project-name
ADO_REPO=your-repo-name
ADO_PAT=your-pat-token
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

## Usage

### Fetch — pull data from Azure DevOps into the DB

```bash
# All engineers, all repos
python3 fetch.py engineer --from 01-04-2026 --to 15-04-2026

# Single engineer
python3 fetch.py engineer --eng x.y@amusedgroup.com --from 01-04-2026 --to 15-04-2026

# Filter by repo pattern
python3 fetch.py engineer --from 01-04-2026 --to 15-04-2026 -n "Sports.*,Racing.*"

# PR/commit metrics for the configured single repo
python3 fetch.py prs --days 30
python3 fetch.py commits --days 60
```

### View — query the local database

```bash
# Summary table: all engineers for a period
python3 view.py summary --from 01-04-2026 --to 15-04-2026

# Summary for a specific engineer
python3 view.py summary --from 01-04-2026 --to 15-04-2026 --eng thanura

# List commits for an engineer
python3 view.py commits --from 01-04-2026 --to 15-04-2026 --eng thanura

# List commits filtered by repo
python3 view.py commits --from 01-04-2026 --to 15-04-2026 --eng thanura --repo Sports

# List PRs for an engineer
python3 view.py prs --from 01-04-2026 --to 15-04-2026 --eng thanura

# List only completed PRs
python3 view.py prs --from 01-04-2026 --to 15-04-2026 --eng thanura --status completed
```

### Repo utilities

```bash
python3 fetch.py dedup-repos       # remove duplicates from repos.json
python3 fetch.py split-repos       # split repos.json into per-namespace files
```

## Database

Results are stored in `azdopal.db` (SQLite). Tables:

- `engineer_activity` — summary counts per engineer/repo/branch/period
- `commits` — individual commits with message, branch, date, url
- `pull_requests` — individual PRs with status, branches, review time, url
- `repos` — repo registry used for pattern-based filtering
- `scanned_repos` — resume tracking per period

```bash
# Example queries
sqlite3 azdopal.db "SELECT engineer_email, repo, commit_count FROM engineer_activity WHERE period='2026/03/30 - 2026/04/10' ORDER BY commit_count DESC"
sqlite3 azdopal.db "SELECT repo, branch, message FROM commits WHERE engineer_email='x.y@amusedgroup.com'"
```

## Architecture

### Project structure

```
azdopal/
├── fetch.py                # Entry point — fetch commands (pulls from ADO → DB)
├── view.py                 # Entry point — view commands (queries DB → console)
├── common.py               # Shared helpers (date parsing, repo pattern loading, error handling)
├── client.py               # Azure DevOps REST API client with retry/backoff
├── engineer_activity.py    # Core fetch logic — scans repos for commits & PRs
├── db.py                   # SQLite helpers — schema, upserts, queries
├── pr_metrics.py           # PR metrics for a single configured repo
├── commit_stats.py         # Commit stats for a single configured repo
├── .env                    # Local config (not committed)
├── .env.example            # Config template
├── requirements.txt        # Python dependencies
├── engineers.json          # Optional list of engineer emails to filter by
├── repos.json              # Cached repo list (fetched from ADO, deduped)
├── repos/                  # Per-namespace repo JSON files (from split-repos)
└── azdopal.db              # SQLite database
```

### Key design decisions

**Repo cache (`repos.json` / `repos` table)**
The ADO `/git/repositories` endpoint is slow and prone to timeouts on large projects. Repos are cached locally and loaded from disk/DB on every run. Use `--refresh-repos` to re-fetch. The `repos` DB table supports glob pattern filtering (e.g. `Sports.*`) via SQLite's `GLOB` operator.

**Single-pass bulk fetch**
When fetching activity for multiple engineers, all repos are scanned once and results are partitioned by engineer email client-side. This avoids N×repos API calls.

**Resume on interruption**
Each repo is written to the DB immediately after scanning. The `scanned_repos` table tracks which repos are done for a given period. Re-running the same command resumes from where it left off.

**Per-repo DB flush**
Data is committed to `azdopal.db` after each repo, not at the end of the run. This means partial results are always available even if the run is interrupted.

**Date filtering**
PRs use `searchCriteria.minTime`/`maxTime` for server-side filtering. Commits require per-branch queries (ADO has no cross-branch commit search), so all branches are fetched per repo and commits are deduplicated by `commitId`.

### Data flow

```
ADO REST API
    │
    ▼
client.py          ← handles auth, retries, pagination
    │
    ▼
engineer_activity.py  ← scans repos, partitions by engineer
    │
    ├──▶ db.py     ← upserts commits, PRs, activity summary per repo
    │
    └──▶ cli.py    ← orchestrates, handles user input/output
```

### Environment variables (`.env`)

| Variable    | Description                                      |
|-------------|--------------------------------------------------|
| `ADO_ORG`   | Organisation name (part after `dev.azure.com/`)  |
| `ADO_PROJECT` | Project name                                   |
| `ADO_REPO`  | Default repo name (used by `prs`/`commits` commands) |
| `ADO_PAT`   | Personal Access Token — needs **Code → Read** scope |
