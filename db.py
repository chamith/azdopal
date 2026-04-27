import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent / "azdopal.db"


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(db_path: Path = DB_PATH):
    """Create tables if they don't exist."""
    with get_connection(db_path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS engineer_activity (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                period          TEXT    NOT NULL,
                from_date       TEXT    NOT NULL,
                to_date         TEXT    NOT NULL,
                engineer_email  TEXT    NOT NULL,
                repo            TEXT    NOT NULL,
                branch          TEXT    NOT NULL,
                pr_count        INTEGER NOT NULL DEFAULT 0,
                commit_count    INTEGER NOT NULL DEFAULT 0,
                updated_at      TEXT    NOT NULL,
                UNIQUE (period, engineer_email, repo, branch)
            );

            CREATE INDEX IF NOT EXISTS idx_ea_engineer
                ON engineer_activity (engineer_email);
            CREATE INDEX IF NOT EXISTS idx_ea_period
                ON engineer_activity (period);
            CREATE INDEX IF NOT EXISTS idx_ea_repo
                ON engineer_activity (repo);

            CREATE TABLE IF NOT EXISTS commits (
                commit_id       TEXT    NOT NULL,
                period          TEXT    NOT NULL,
                engineer_email  TEXT    NOT NULL,
                repo            TEXT    NOT NULL,
                branch          TEXT    NOT NULL,
                message         TEXT,
                commit_date     TEXT,
                url             TEXT,
                updated_at      TEXT    NOT NULL,
                PRIMARY KEY (commit_id, period, engineer_email)
            );

            CREATE INDEX IF NOT EXISTS idx_commits_engineer
                ON commits (engineer_email);
            CREATE INDEX IF NOT EXISTS idx_commits_period
                ON commits (period);
            CREATE INDEX IF NOT EXISTS idx_commits_repo
                ON commits (repo);

            CREATE TABLE IF NOT EXISTS pull_requests (
                pr_id           INTEGER NOT NULL,
                repo            TEXT    NOT NULL,
                period          TEXT    NOT NULL,
                engineer_email  TEXT    NOT NULL,
                title           TEXT,
                status          TEXT,
                source_branch   TEXT,
                target_branch   TEXT,
                created_date    TEXT,
                closed_date     TEXT,
                review_time_hours REAL,
                lines_added     INTEGER,
                lines_deleted   INTEGER,
                url             TEXT,
                updated_at      TEXT    NOT NULL,
                PRIMARY KEY (pr_id, repo, period, engineer_email)
            );

            CREATE INDEX IF NOT EXISTS idx_prs_engineer
                ON pull_requests (engineer_email);
            CREATE INDEX IF NOT EXISTS idx_prs_period
                ON pull_requests (period);
            CREATE INDEX IF NOT EXISTS idx_prs_repo
                ON pull_requests (repo);

            CREATE TABLE IF NOT EXISTS scanned_repos (
                period      TEXT NOT NULL,
                repo        TEXT NOT NULL,
                scanned_at  TEXT NOT NULL,
                PRIMARY KEY (period, repo)
            );

            CREATE TABLE IF NOT EXISTS repos (
                id              TEXT    PRIMARY KEY,
                name            TEXT    NOT NULL UNIQUE,
                default_branch  TEXT,
                remote_url      TEXT,
                web_url         TEXT,
                is_disabled     INTEGER NOT NULL DEFAULT 0,
                size            INTEGER,
                updated_at      TEXT    NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_repos_name
                ON repos (name);

            CREATE TABLE IF NOT EXISTS work_items (
                id              INTEGER NOT NULL,
                period          TEXT    NOT NULL,
                engineer_email  TEXT    NOT NULL,
                title           TEXT,
                type            TEXT,
                state           TEXT,
                area_path       TEXT,
                iteration_path  TEXT,
                story_points    REAL,
                effort          REAL,
                remaining_work  REAL,
                original_estimate REAL,
                completed_work  REAL,
                created_date    TEXT,
                changed_date    TEXT,
                url             TEXT,
                updated_at      TEXT    NOT NULL,
                PRIMARY KEY (id, period, engineer_email)
            );

            CREATE INDEX IF NOT EXISTS idx_wi_engineer
                ON work_items (engineer_email);
            CREATE INDEX IF NOT EXISTS idx_wi_period
                ON work_items (period);
            CREATE INDEX IF NOT EXISTS idx_wi_type
                ON work_items (type);
            CREATE INDEX IF NOT EXISTS idx_wi_state
                ON work_items (state);

            CREATE TABLE IF NOT EXISTS sprints (
                id              TEXT    NOT NULL,
                name            TEXT    NOT NULL,
                team_name       TEXT    NOT NULL DEFAULT '',
                path            TEXT,
                start_date      TEXT,
                end_date        TEXT,
                time_frame      TEXT,
                updated_at      TEXT    NOT NULL,
                PRIMARY KEY (id, team_name)
            );

            CREATE INDEX IF NOT EXISTS idx_sprints_name
                ON sprints (name);
            CREATE INDEX IF NOT EXISTS idx_sprints_dates
                ON sprints (start_date, end_date);

            CREATE TABLE IF NOT EXISTS teams (
                id          TEXT    PRIMARY KEY,
                name        TEXT    NOT NULL UNIQUE,
                description TEXT,
                updated_at  TEXT    NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_teams_name
                ON teams (name);

            CREATE TABLE IF NOT EXISTS team_members (
                team_id     TEXT    NOT NULL,
                team_name   TEXT    NOT NULL,
                email       TEXT    NOT NULL,
                display_name TEXT,
                updated_at  TEXT    NOT NULL,
                PRIMARY KEY (team_id, email)
            );

            CREATE INDEX IF NOT EXISTS idx_tm_team
                ON team_members (team_name);
            CREATE INDEX IF NOT EXISTS idx_tm_email
                ON team_members (email);

            CREATE TABLE IF NOT EXISTS work_item_prs (
                work_item_id    INTEGER NOT NULL,
                period          TEXT    NOT NULL,
                pr_id           INTEGER NOT NULL,
                repo            TEXT,
                url             TEXT,
                updated_at      TEXT    NOT NULL,
                PRIMARY KEY (work_item_id, period, pr_id)
            );

            CREATE INDEX IF NOT EXISTS idx_wi_prs
                ON work_item_prs (work_item_id, period);
        """)
        # Migrate existing DBs — add columns if they don't exist yet
        for col, typedef in [("lines_added", "INTEGER"), ("lines_deleted", "INTEGER")]:
            try:
                conn.execute(f"ALTER TABLE pull_requests ADD COLUMN {col} {typedef}")
            except Exception:
                pass
        for col, typedef in [("original_estimate", "REAL"), ("completed_work", "REAL")]:
            try:
                conn.execute(f"ALTER TABLE work_items ADD COLUMN {col} {typedef}")
            except Exception:
                pass
        try:
            conn.execute("ALTER TABLE work_items ADD COLUMN parent_id INTEGER")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE work_items ADD COLUMN activated_date TEXT")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE work_items ADD COLUMN resolved_date TEXT")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE sprints ADD COLUMN team_name TEXT NOT NULL DEFAULT ''")
        except Exception:
            pass  # column already exists
        # Fix primary key if sprints table still has single-column PK
        try:
            # Check if the composite PK exists by trying a conflicting insert
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sprints_new (
                    id              TEXT    NOT NULL,
                    name            TEXT    NOT NULL,
                    team_name       TEXT    NOT NULL DEFAULT '',
                    path            TEXT,
                    start_date      TEXT,
                    end_date        TEXT,
                    time_frame      TEXT,
                    updated_at      TEXT    NOT NULL,
                    PRIMARY KEY (id, team_name)
                )
            """)
            # Migrate data if sprints_new is empty
            count = conn.execute("SELECT COUNT(*) FROM sprints_new").fetchone()[0]
            if count == 0:
                conn.execute("""
                    INSERT OR IGNORE INTO sprints_new
                    SELECT id, name, team_name, path, start_date, end_date, time_frame, updated_at
                    FROM sprints
                """)
                conn.execute("DROP TABLE sprints")
                conn.execute("ALTER TABLE sprints_new RENAME TO sprints")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_sprints_name ON sprints (name)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_sprints_dates ON sprints (start_date, end_date)")
        except Exception:
            pass


def upsert_activity(
    conn: sqlite3.Connection,
    period: str,
    from_date: str,
    to_date: str,
    engineer_email: str,
    repo: str,
    branch: str,
    pr_count: int,
    commit_count: int,
):
    updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute("""
        INSERT INTO engineer_activity
            (period, from_date, to_date, engineer_email, repo, branch,
             pr_count, commit_count, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (period, engineer_email, repo, branch)
        DO UPDATE SET
            pr_count     = excluded.pr_count,
            commit_count = excluded.commit_count,
            updated_at   = excluded.updated_at
    """, (period, from_date, to_date, engineer_email, repo, branch,
          pr_count, commit_count, updated_at))


def upsert_commit(conn: sqlite3.Connection, period: str, engineer_email: str, commit: dict):
    updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute("""
        INSERT INTO commits
            (commit_id, period, engineer_email, repo, branch, message, commit_date, url, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (commit_id, period, engineer_email)
        DO UPDATE SET
            repo        = excluded.repo,
            branch      = excluded.branch,
            message     = excluded.message,
            commit_date = excluded.commit_date,
            url         = excluded.url,
            updated_at  = excluded.updated_at
    """, (
        commit.get("commit_id"),
        period,
        engineer_email,
        commit.get("repo"),
        commit.get("branch"),
        commit.get("message"),
        commit.get("date"),
        commit.get("url"),
        updated_at,
    ))


def upsert_pr(conn: sqlite3.Connection, period: str, engineer_email: str, pr: dict):
    updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute("""
        INSERT INTO pull_requests
            (pr_id, repo, period, engineer_email, title, status,
             source_branch, target_branch, created_date, closed_date,
             review_time_hours, lines_added, lines_deleted, url, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (pr_id, repo, period, engineer_email)
        DO UPDATE SET
            title             = excluded.title,
            status            = excluded.status,
            source_branch     = excluded.source_branch,
            target_branch     = excluded.target_branch,
            created_date      = excluded.created_date,
            closed_date       = excluded.closed_date,
            review_time_hours = excluded.review_time_hours,
            lines_added       = excluded.lines_added,
            lines_deleted     = excluded.lines_deleted,
            url               = excluded.url,
            updated_at        = excluded.updated_at
    """, (
        pr.get("pr_id"),
        pr.get("repo"),
        period,
        engineer_email,
        pr.get("title"),
        pr.get("status"),
        pr.get("source_branch"),
        pr.get("target_branch"),
        pr.get("created_date"),
        pr.get("closed_date"),
        pr.get("review_time_hours"),
        pr.get("lines_added"),
        pr.get("lines_deleted"),
        pr.get("url"),
        updated_at,
    ))


def upsert_team_member(conn: sqlite3.Connection, team_id: str, team_name: str,
                       email: str, display_name: str):
    updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute("""
        INSERT INTO team_members (team_id, team_name, email, display_name, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (team_id, email) DO UPDATE SET
            team_name    = excluded.team_name,
            display_name = excluded.display_name,
            updated_at   = excluded.updated_at
    """, (team_id, team_name, email.lower(), display_name, updated_at))


def get_team_member_emails(conn: sqlite3.Connection, team_name: str) -> list[str]:
    """Return lowercase emails of all members of a team (partial name match)."""
    rows = conn.execute(
        "SELECT email FROM team_members WHERE team_name LIKE ?",
        (f"%{team_name}%",)
    ).fetchall()
    return [r["email"] for r in rows]


def upsert_team(conn: sqlite3.Connection, team: dict):
    updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute("""
        INSERT INTO teams (id, name, description, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (id) DO UPDATE SET
            name        = excluded.name,
            description = excluded.description,
            updated_at  = excluded.updated_at
    """, (
        team.get("id"),
        team.get("name"),
        team.get("description"),
        updated_at,
    ))


def list_teams(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM teams ORDER BY name").fetchall()
    return [dict(r) for r in rows]


def get_team_by_name(conn: sqlite3.Connection, name: str) -> dict | None:
    row = conn.execute("SELECT * FROM teams WHERE name = ? LIMIT 1", (name,)).fetchone()
    if not row:
        row = conn.execute(
            "SELECT * FROM teams WHERE name LIKE ? LIMIT 1", (f"%{name}%",)
        ).fetchone()
    return dict(row) if row else None


def upsert_sprint(conn: sqlite3.Connection, sprint: dict):
    updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute("""
        INSERT INTO sprints (id, name, team_name, path, start_date, end_date, time_frame, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (id, team_name) DO UPDATE SET
            name       = excluded.name,
            path       = excluded.path,
            start_date = excluded.start_date,
            end_date   = excluded.end_date,
            time_frame = excluded.time_frame,
            updated_at = excluded.updated_at
    """, (
        sprint.get("id"),
        sprint.get("name"),
        sprint.get("team_name", ""),
        sprint.get("path"),
        sprint.get("start_date"),
        sprint.get("end_date"),
        sprint.get("time_frame"),
        updated_at,
    ))


def get_sprint_by_name(conn: sqlite3.Connection, name: str, team_name: str | None = None) -> dict | None:
    """Find a sprint by exact name, number suffix, or partial name match. Optionally filter by team."""
    team_clause = "AND team_name = ?" if team_name else ""
    team_params = [team_name] if team_name else []

    # Exact match first
    row = conn.execute(
        f"SELECT * FROM sprints WHERE name = ? {team_clause} LIMIT 1",
        [name] + team_params
    ).fetchone()
    if row:
        return dict(row)

    # If input is a number, match "Sprint {number}", "Iteration {number}" etc. exactly
    if name.strip().isdigit():
        for pattern in (f"Sprint {name.strip()}", f"Sprint{name.strip()}",
                        f"Iteration {name.strip()}", f"Iteration{name.strip()}"):
            row = conn.execute(
                f"SELECT * FROM sprints WHERE name = ? {team_clause} LIMIT 1",
                [pattern] + team_params
            ).fetchone()
            if row:
                return dict(row)

    # Partial match — prefer most recent
    row = conn.execute(
        f"SELECT * FROM sprints WHERE name LIKE ? {team_clause} ORDER BY start_date DESC LIMIT 1",
        [f"%{name}%"] + team_params
    ).fetchone()
    return dict(row) if row else None


def list_sprints(conn: sqlite3.Connection, team_name: str | None = None) -> list[dict]:
    if team_name:
        rows = conn.execute(
            "SELECT * FROM sprints WHERE team_name = ? ORDER BY start_date DESC", (team_name,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM sprints ORDER BY start_date DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def upsert_work_item_pr(conn: sqlite3.Connection, work_item_id: int, period: str,
                        pr_id: int, repo: str, url: str):
    updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute("""
        INSERT INTO work_item_prs (work_item_id, period, pr_id, repo, url, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (work_item_id, period, pr_id) DO UPDATE SET
            repo       = excluded.repo,
            url        = excluded.url,
            updated_at = excluded.updated_at
    """, (work_item_id, period, pr_id, repo, url, updated_at))


def upsert_work_item(conn: sqlite3.Connection, period: str, engineer_email: str, item: dict):
    updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute("""
        INSERT INTO work_items
            (id, period, engineer_email, title, type, state, area_path,
             iteration_path, story_points, effort, remaining_work,
             original_estimate, completed_work, parent_id,
             activated_date,
             resolved_date,
             created_date, changed_date, url, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (id, period, engineer_email)
        DO UPDATE SET
            title             = excluded.title,
            type              = excluded.type,
            state             = excluded.state,
            area_path         = excluded.area_path,
            iteration_path    = excluded.iteration_path,
            story_points      = excluded.story_points,
            effort            = excluded.effort,
            remaining_work    = excluded.remaining_work,
            original_estimate = excluded.original_estimate,
            completed_work    = excluded.completed_work,
            parent_id         = excluded.parent_id,
            activated_date    = excluded.activated_date,
            resolved_date     = excluded.resolved_date,
            created_date      = excluded.created_date,
            changed_date      = excluded.changed_date,
            url               = excluded.url,
            updated_at        = excluded.updated_at
    """, (
        item.get("id"),
        period,
        engineer_email,
        item.get("title"),
        item.get("type"),
        item.get("state"),
        item.get("area_path"),
        item.get("iteration_path"),
        item.get("story_points"),
        item.get("effort"),
        item.get("remaining_work"),
        item.get("original_estimate"),
        item.get("completed_work"),
        item.get("parent_id"),
        item.get("activated_date"),
        item.get("resolved_date"),
        item.get("created_date"),
        item.get("changed_date"),
        item.get("url"),
        updated_at,
    ))


def upsert_repo(conn: sqlite3.Connection, repo: dict):
    updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute("""
        INSERT INTO repos (id, name, default_branch, remote_url, web_url, is_disabled, size, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (id) DO UPDATE SET
            name           = excluded.name,
            default_branch = excluded.default_branch,
            remote_url     = excluded.remote_url,
            web_url        = excluded.web_url,
            is_disabled    = excluded.is_disabled,
            size           = excluded.size,
            updated_at     = excluded.updated_at
    """, (
        repo.get("id"),
        repo.get("name"),
        repo.get("defaultBranch", "").replace("refs/heads/", ""),
        repo.get("remoteUrl"),
        repo.get("webUrl"),
        1 if repo.get("isDisabled") else 0,
        repo.get("size"),
        updated_at,
    ))


def get_repos_by_pattern(conn: sqlite3.Connection, pattern: str) -> list[dict]:
    """
    Return repos whose name matches a glob pattern.
    e.g. "Sports.*", "Racing.DataTools.*", "*"
    SQLite GLOB is case-sensitive; pattern uses * and ? wildcards.
    """
    rows = conn.execute(
        "SELECT id, name, default_branch, remote_url, web_url FROM repos WHERE name GLOB ? AND is_disabled = 0",
        (pattern,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_all_repos(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT id, name, default_branch, remote_url, web_url FROM repos WHERE is_disabled = 0 ORDER BY name"
    ).fetchall()
    return [dict(r) for r in rows]


def mark_repo_scanned(conn: sqlite3.Connection, period: str, repo: str):
    """Record that a repo has been fully scanned for a given period."""
    scanned_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute("""
        INSERT OR REPLACE INTO scanned_repos (period, repo, scanned_at)
        VALUES (?, ?, ?)
    """, (period, repo, scanned_at))
    conn.commit()


def get_scanned_repos(conn: sqlite3.Connection, period: str) -> set[str]:
    """Return the set of repo names already scanned for a given period."""
    rows = conn.execute(
        "SELECT repo FROM scanned_repos WHERE period = ?", (period,)
    ).fetchall()
    return {row["repo"] for row in rows}


def save_engineer_results(
    results: dict[str, dict],
    db_path: Path = DB_PATH,
):
    """Persist fetch_all_engineers_activity results to SQLite."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        for email, data in results.items():
            from_date = data["from"]
            to_date = data["to"]
            period = f"{from_date.replace('-', '/')} - {to_date.replace('-', '/')}"

            commit_counts: dict[tuple, int] = {}
            for c in data.get("commits", []):
                key = (c.get("repo", ""), c.get("branch", ""))
                commit_counts[key] = commit_counts.get(key, 0) + 1

            pr_counts: dict[tuple, int] = {}
            for pr in data.get("pull_requests", []):
                key = (pr.get("repo", ""), pr.get("source_branch", ""))
                pr_counts[key] = pr_counts.get(key, 0) + 1

            all_keys = set(commit_counts.keys()) | set(pr_counts.keys())
            for repo, branch in all_keys:
                upsert_activity(
                    conn,
                    period=period,
                    from_date=from_date,
                    to_date=to_date,
                    engineer_email=email,
                    repo=repo,
                    branch=branch,
                    pr_count=pr_counts.get((repo, branch), 0),
                    commit_count=commit_counts.get((repo, branch), 0),
                )
        conn.commit()
