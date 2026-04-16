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
        """)


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
             review_time_hours, url, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (pr_id, repo, period, engineer_email)
        DO UPDATE SET
            title             = excluded.title,
            status            = excluded.status,
            source_branch     = excluded.source_branch,
            target_branch     = excluded.target_branch,
            created_date      = excluded.created_date,
            closed_date       = excluded.closed_date,
            review_time_hours = excluded.review_time_hours,
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
        pr.get("url"),
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
