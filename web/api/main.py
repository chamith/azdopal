"""FastAPI backend for azdopal web UI."""
import sqlite3
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

DB_PATH = Path(__file__).parent.parent.parent / "azdopal.db"

app = FastAPI(title="azdopal API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # Ensure parent_id column exists (migration)
    try:
        conn.execute("ALTER TABLE work_items ADD COLUMN parent_id INTEGER")
        conn.commit()
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE work_items ADD COLUMN activated_date TEXT")
        conn.commit()
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE work_items ADD COLUMN resolved_date TEXT")
        conn.commit()
    except Exception:
        pass
    return conn


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

@app.get("/api/sprints")
def list_sprints(team: Optional[str] = None):
    with get_conn() as conn:
        if team:
            rows = conn.execute(
                "SELECT name, MIN(start_date) as start_date, MIN(end_date) as end_date, "
                "MIN(time_frame) as time_frame, team_name "
                "FROM sprints WHERE team_name LIKE ? "
                "GROUP BY name ORDER BY start_date DESC",
                (f"%{team}%",)
            ).fetchall()
        else:
            # Deduplicate by name — pick the most recent team_name entry
            rows = conn.execute(
                "SELECT name, MIN(start_date) as start_date, MIN(end_date) as end_date, "
                "MIN(time_frame) as time_frame "
                "FROM sprints GROUP BY name ORDER BY start_date DESC"
            ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/teams")
def list_teams():
    with get_conn() as conn:
        rows = conn.execute("SELECT id, name, description FROM teams ORDER BY name").fetchall()
    return [dict(r) for r in rows]


@app.get("/api/periods")
def list_periods():
    """Return all distinct periods stored in the DB."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT period FROM commits UNION "
            "SELECT DISTINCT period FROM pull_requests UNION "
            "SELECT DISTINCT period FROM work_items "
            "ORDER BY period DESC"
        ).fetchall()
    return [r["period"] for r in rows]


# ---------------------------------------------------------------------------
# Sprint Summary
# ---------------------------------------------------------------------------

@app.get("/api/summary")
def sprint_summary(period: str, team: Optional[str] = None):
    """Commits + PRs per engineer for a period, optionally filtered by team."""
    with get_conn() as conn:
        # Resolve team email filter via area_path
        email_filter = ""
        email_params: list = []

        if team:
            area_rows = conn.execute(
                "SELECT DISTINCT area_path FROM work_items WHERE period = ? "
                "AND (area_path LIKE ? OR area_path LIKE ?)",
                (period, f"%{team}%", f"%{team.rstrip('s')}%")
            ).fetchall()
            area_paths = [r["area_path"] for r in area_rows]
            if area_paths:
                ph = ",".join("?" * len(area_paths))
                eng_rows = conn.execute(
                    f"SELECT DISTINCT engineer_email FROM work_items "
                    f"WHERE period = ? AND area_path IN ({ph})",
                    [period] + area_paths
                ).fetchall()
                emails = [r["engineer_email"] for r in eng_rows]
                if emails:
                    ph2 = ",".join("?" * len(emails))
                    email_filter = f"AND engineer_email IN ({ph2})"
                    email_params = emails

        commit_rows = conn.execute(
            f"SELECT engineer_email, COUNT(*) AS commits FROM commits "
            f"WHERE period = ? {email_filter} GROUP BY engineer_email",
            [period] + email_params
        ).fetchall()

        pr_rows = conn.execute(
            f"SELECT engineer_email, COUNT(*) AS prs, AVG(review_time_hours) AS avg_review "
            f"FROM pull_requests WHERE period = ? {email_filter} GROUP BY engineer_email",
            [period] + email_params
        ).fetchall()

    commit_map = {r["engineer_email"]: r["commits"] for r in commit_rows}
    pr_map = {r["engineer_email"]: {"prs": r["prs"], "avg_review": r["avg_review"]}
              for r in pr_rows}
    all_emails = sorted(set(commit_map) | set(pr_map))

    return [
        {
            "engineer": email,
            "commits": commit_map.get(email, 0),
            "prs": pr_map.get(email, {}).get("prs", 0),
            "avg_review_hours": pr_map.get(email, {}).get("avg_review"),
        }
        for email in all_emails
    ]


# ---------------------------------------------------------------------------
# Engineer Detail
# ---------------------------------------------------------------------------

@app.get("/api/engineer/{email}/commits")
def engineer_commits(email: str, period: str, repo: Optional[str] = None):
    with get_conn() as conn:
        query = ("SELECT commit_date, repo, branch, message, url FROM commits "
                 "WHERE period = ? AND engineer_email LIKE ?")
        params: list = [period, f"%{email}%"]
        if repo:
            query += " AND repo LIKE ?"
            params.append(f"%{repo}%")
        query += " ORDER BY commit_date DESC"
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/engineer/{email}/prs")
def engineer_prs(email: str, period: str, status: Optional[str] = None):
    with get_conn() as conn:
        query = ("SELECT pr_id, repo, title, status, source_branch, target_branch, "
                 "created_date, closed_date, review_time_hours, url "
                 "FROM pull_requests WHERE period = ? AND engineer_email LIKE ?")
        params: list = [period, f"%{email}%"]
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_date DESC"
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/engineer/{email}/work-items")
def engineer_work_items(email: str, period: str):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, type, state, title, story_points, effort, remaining_work, "
            "original_estimate, completed_work, area_path, iteration_path, changed_date, url "
            "FROM work_items WHERE period = ? AND engineer_email LIKE ? "
            "ORDER BY changed_date DESC",
            [period, f"%{email}%"]
        ).fetchall()
        result = []
        for r in rows:
            item = dict(r)
            pr_rows = conn.execute(
                "SELECT pr_id, repo, url FROM work_item_prs "
                "WHERE work_item_id = ? AND period = ?",
                (r["id"], period)
            ).fetchall()
            item["linked_prs"] = [dict(p) for p in pr_rows]
            result.append(item)
    return result


# ---------------------------------------------------------------------------
# Work Items (team view)
# ---------------------------------------------------------------------------

@app.get("/api/work-items")
def work_items(
    period: str,
    team: Optional[str] = None,
    eng: Optional[str] = None,
    item_type: Optional[str] = None,
    state: Optional[str] = None,
):
    with get_conn() as conn:
        query = ("SELECT engineer_email, id, type, state, title, story_points, effort, "
                 "remaining_work, original_estimate, completed_work, parent_id, "
                 "activated_date, resolved_date, area_path, iteration_path, changed_date, url "
                 "FROM work_items WHERE period = ?")
        params: list = [period]

        if eng:
            query += " AND engineer_email LIKE ?"
            params.append(f"%{eng}%")

        if team:
            area_rows = conn.execute(
                "SELECT DISTINCT area_path FROM work_items WHERE period = ? "
                "AND (area_path LIKE ? OR area_path LIKE ?)",
                (period, f"%{team}%", f"%{team.rstrip('s')}%")
            ).fetchall()
            area_paths = [r["area_path"] for r in area_rows]
            if area_paths:
                ph = ",".join("?" * len(area_paths))
                query += f" AND area_path IN ({ph})"
                params.extend(area_paths)

        if item_type:
            query += " AND type = ?"
            params.append(item_type)
        if state:
            query += " AND state = ?"
            params.append(state)

        query += " AND state != 'Removed'"
        query += " AND type IN ('User Story', 'Task', 'Bug')"
        query += " ORDER BY engineer_email, changed_date DESC"
        rows = conn.execute(query, params).fetchall()

        result = []
        for r in rows:
            item = dict(r)
            pr_rows = conn.execute(
                "SELECT pr_id, repo, url FROM work_item_prs "
                "WHERE work_item_id = ? AND period = ?",
                (r["id"], period)
            ).fetchall()
            item["linked_prs"] = [dict(p) for p in pr_rows]
            item["children"] = []

            # Calculate sprints_active for all work items with an activated date
            sprints_active = None
            # Use activated_date if available, fall back to created_date
            ref_date = item.get("activated_date") or item.get("created_date")
            if ref_date:
                act_date = ref_date[:10]
                # For closed stories, count up to resolved date
                # For active stories, count up to current sprint's end
                if item.get("resolved_date"):
                    end_date = item["resolved_date"][:10]
                else:
                    sprint_row = conn.execute(
                        "SELECT end_date FROM sprints WHERE name = ? LIMIT 1", (period,)
                    ).fetchone()
                    end_date = sprint_row["end_date"][:10] if sprint_row and sprint_row["end_date"] else None

                if end_date:
                    # Count sprints that overlap with [activated_date, end_date]
                    # A sprint overlaps if its end >= activated_date AND its start <= end_date
                    sprint_count = conn.execute(
                        "SELECT COUNT(DISTINCT name) as cnt FROM sprints "
                        "WHERE start_date IS NOT NULL AND end_date IS NOT NULL "
                        "AND end_date >= ? AND start_date <= ?",
                        (act_date, end_date)
                    ).fetchone()
                    sprints_active = sprint_count["cnt"] if sprint_count else 0
            item["sprints_active"] = sprints_active

            # Detect spillover — was this item in the previous sprint in an active state?
            spilled_from = None
            if item.get("type") in ("User Story", "Bug") and item.get("state") not in ("New", "Closed"):
                # Find the previous sprint
                prev_sprint = conn.execute(
                    "SELECT DISTINCT name FROM sprints "
                    "WHERE start_date IS NOT NULL AND start_date < ("
                    "  SELECT MIN(start_date) FROM sprints WHERE name = ?"
                    ") ORDER BY start_date DESC LIMIT 1",
                    (period,)
                ).fetchone()
                if prev_sprint:
                    prev_name = prev_sprint["name"]
                    prev_item = conn.execute(
                        "SELECT state FROM work_items WHERE id = ? AND period = ? LIMIT 1",
                        (item["id"], prev_name)
                    ).fetchone()
                    if prev_item and prev_item["state"] not in ("New", "Closed", "Removed"):
                        spilled_from = prev_name
            item["spilled_from"] = spilled_from

            result.append(item)

    return result
