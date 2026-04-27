"""view.py — query azdopal.db and display results"""
import sys
import click
from db import init_db, get_connection
from common import parse_date, handle_errors, resolve_date_range


def _print_table(headers: list[str], rows: list[tuple], col_widths: list[int] = None):
    """Simple fixed-width table printer."""
    if not rows:
        click.echo("  No results found.")
        return
    if not col_widths:
        col_widths = [max(len(str(r[i])) for r in rows + [headers]) + 2 for i in range(len(headers))]
    header_line = "  " + "".join(str(h).ljust(col_widths[i]) for i, h in enumerate(headers))
    separator = "  " + "-" * (sum(col_widths))
    click.echo(header_line)
    click.echo(separator)
    for row in rows:
        click.echo("  " + "".join(str(v).ljust(col_widths[i]) for i, v in enumerate(row)))


@click.group()
def cli():
    """azdopal view — query the local database."""


@cli.command()
@click.option("--from", "from_date", default=None, callback=parse_date, is_eager=True, help="Start date dd-mm-yyyy.")
@click.option("--to", "to_date", default=None, callback=parse_date, is_eager=True, help="End date dd-mm-yyyy.")
@click.option("--sprint", default=None, help="Sprint name or number (alternative to --from/--to).")
@click.option("--team", default=None, help="Team name to scope sprint lookup (partial match).")
@click.option("--eng", default=None, help="Filter by engineer email (partial match supported).")
@handle_errors
def summary(from_date, to_date, sprint, team, eng):
    """Show a summary table of commits and PRs per engineer for a period."""
    init_db()
    with get_connection() as conn:
        from_dt, to_dt, period = resolve_date_range(from_date, to_date, sprint, conn, team)
        eng_filter = f"%{eng}%" if eng else "%"

        commit_rows = conn.execute("""
            SELECT engineer_email, COUNT(*) AS commits
            FROM   commits
            WHERE  period = ?
            AND    engineer_email LIKE ?
            GROUP  BY engineer_email
        """, (period, eng_filter)).fetchall()

        pr_rows = conn.execute("""
            SELECT engineer_email,
                   COUNT(*)                     AS prs,
                   AVG(review_time_hours)        AS avg_review_hours
            FROM   pull_requests
            WHERE  period = ?
            AND    engineer_email LIKE ?
            GROUP  BY engineer_email
        """, (period, eng_filter)).fetchall()

    commit_map = {r["engineer_email"]: r["commits"] for r in commit_rows}
    pr_map = {r["engineer_email"]: (r["prs"], r["avg_review_hours"]) for r in pr_rows}
    all_emails = sorted(set(commit_map) | set(pr_map))

    click.echo(f"\nSummary for period: {period}\n")
    rows = [
        (
            email,
            commit_map.get(email, 0),
            pr_map.get(email, (0, None))[0],
            f"{pr_map.get(email, (0, None))[1]:.1f}h" if pr_map.get(email, (0, None))[1] else "-",
        )
        for email in all_emails
    ]
    rows.sort(key=lambda r: r[1], reverse=True)
    _print_table(
        ["Engineer", "Commits", "PRs", "Avg Review"],
        rows,
        col_widths=[45, 10, 8, 12],
    )
    click.echo(f"\n  Total engineers: {len(rows)}")


@cli.command()
@click.option("--from", "from_date", default=None, callback=parse_date, is_eager=True, help="Start date dd-mm-yyyy.")
@click.option("--to", "to_date", default=None, callback=parse_date, is_eager=True, help="End date dd-mm-yyyy.")
@click.option("--sprint", default=None, help="Sprint name or number (alternative to --from/--to).")
@click.option("--team", default=None, help="Team name to scope sprint lookup (partial match).")
@click.option("--eng", required=True, help="Engineer email (partial match supported).")
@click.option("--repo", default=None, help="Filter by repo name (partial match).")
@handle_errors
def commits(from_date, to_date, sprint, team, eng, repo):
    """List commits for an engineer in a period."""
    init_db()
    with get_connection() as conn:
        from_dt, to_dt, period = resolve_date_range(from_date, to_date, sprint, conn, team)
        query = """
            SELECT commit_date, repo, branch, message, url
            FROM   commits
            WHERE  period = ?
            AND    engineer_email LIKE ?
        """
        params = [period, f"%{eng}%"]
        if repo:
            query += " AND repo LIKE ?"
            params.append(f"%{repo}%")
        query += " ORDER BY commit_date DESC"
        rows = conn.execute(query, params).fetchall()

    click.echo(f"\nCommits for '{eng}' — period: {period}\n")
    if not rows:
        click.echo("  No commits found.")
        return
    for r in rows:
        date = (r["commit_date"] or "")[:10]
        click.echo(f"  {date}  [{r['repo']} / {r['branch']}]")
        click.echo(f"           {r['message']}")
        click.echo(f"           {r['url']}")
        click.echo()


@cli.command()
@click.option("--from", "from_date", default=None, callback=parse_date, is_eager=True, help="Start date dd-mm-yyyy.")
@click.option("--to", "to_date", default=None, callback=parse_date, is_eager=True, help="End date dd-mm-yyyy.")
@click.option("--sprint", default=None, help="Sprint name or number (alternative to --from/--to).")
@click.option("--team", default=None, help="Team name to scope sprint lookup (partial match).")
@click.option("--eng", required=True, help="Engineer email (partial match supported).")
@click.option("--repo", default=None, help="Filter by repo name (partial match).")
@click.option("--status", default=None, type=click.Choice(["active", "completed", "abandoned"]), help="Filter by PR status.")
@handle_errors
def prs(from_date, to_date, sprint, team, eng, repo, status):
    """List PRs for an engineer in a period."""
    init_db()
    with get_connection() as conn:
        from_dt, to_dt, period = resolve_date_range(from_date, to_date, sprint, conn, team)
        query = """
            SELECT created_date, repo, source_branch, target_branch,
                   status, review_time_hours, title, url
            FROM   pull_requests
            WHERE  period = ?
            AND    engineer_email LIKE ?
        """
        params = [period, f"%{eng}%"]
        if repo:
            query += " AND repo LIKE ?"
            params.append(f"%{repo}%")
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_date DESC"
        rows = conn.execute(query, params).fetchall()

    click.echo(f"\nPRs for '{eng}' — period: {period}\n")
    if not rows:
        click.echo("  No PRs found.")
        return
    for r in rows:
        date = (r["created_date"] or "")[:10]
        review = f"{r['review_time_hours']}h" if r["review_time_hours"] else "open"
        click.echo(f"  {date}  [{r['status'].upper()}]  {r['repo']}")
        click.echo(f"           {r['source_branch']} → {r['target_branch']}  ({review})")
        click.echo(f"           {r['title']}")
        click.echo(f"           {r['url']}")
        click.echo()


@cli.command()
@click.option("--from", "from_date", default=None, callback=parse_date, is_eager=True, help="Start date dd-mm-yyyy.")
@click.option("--to", "to_date", default=None, callback=parse_date, is_eager=True, help="End date dd-mm-yyyy.")
@click.option("--sprint", default=None, help="Sprint name or number (alternative to --from/--to).")
@click.option("--team", default=None, help="Team name to scope sprint lookup (partial match).")
@click.option("--eng", default=None, help="Engineer email (partial match). If omitted, shows all engineers.")
@click.option("--type", "item_type", default=None, help="Filter by type e.g. Bug, Task, User Story.")
@click.option("--state", default=None, help="Filter by state e.g. Active, Closed, Resolved.")
@handle_errors
def work_items(from_date, to_date, sprint, team, eng, item_type, state):
    """List work items for a sprint/period, optionally filtered by engineer."""
    init_db()
    with get_connection() as conn:
        from_dt, to_dt, period = resolve_date_range(from_date, to_date, sprint, conn, team)

        # If team specified, filter by area_path derived from team name
        team_area_filter = ""
        team_area_params: list = []
        if team:
            # Find area paths that match the team name (try exact and partial)
            area_rows = conn.execute("""
                SELECT DISTINCT area_path FROM work_items
                WHERE period = ?
                AND (area_path LIKE ? OR area_path LIKE ?)
            """, (period, f"%{team}%", f"%{team.rstrip('s')}%")).fetchall()

            area_paths = [r["area_path"] for r in area_rows]
            if area_paths:
                placeholders = ",".join("?" * len(area_paths))
                team_area_filter = f"AND area_path IN ({placeholders})"
                team_area_params = area_paths
                click.echo(f"  Filtering by area paths: {area_paths}", err=True)
            else:
                # Fall back to team_members
                from db import get_team_member_emails
                team_emails = get_team_member_emails(conn, team)
                if team_emails:
                    placeholders = ",".join("?" * len(team_emails))
                    team_area_filter = f"AND engineer_email IN ({placeholders})"
                    team_area_params = team_emails

        query = """
            SELECT engineer_email, id, type, state, title, story_points, effort,
                   remaining_work, original_estimate, completed_work,
                   area_path, iteration_path, changed_date, url
            FROM   work_items
            WHERE  period = ?
        """
        params = [period]
        if eng:
            query += " AND engineer_email LIKE ?"
            params.append(f"%{eng}%")
        if team_area_filter:
            query += f" {team_area_filter}"
            params.extend(team_area_params)
        if item_type:
            query += " AND type = ?"
            params.append(item_type)
        if state:
            query += " AND state = ?"
            params.append(state)
        query += " ORDER BY engineer_email, changed_date DESC"
        rows = conn.execute(query, params).fetchall()

    label = f"'{eng}'" if eng else "all engineers"
    click.echo(f"\nWork items for {label} — period: {period}\n")
    if not rows:
        click.echo("  No work items found.")
        return

    current_eng = None
    for r in rows:
        if r["engineer_email"] != current_eng:
            current_eng = r["engineer_email"]
            click.echo(f"\n  ── {current_eng} ──")
        date = (r["changed_date"] or "")[:10]
        points = f"  SP:{r['story_points']}" if r["story_points"] else ""
        effort = f"  Effort:{r['effort']}" if r["effort"] else ""
        remaining = f"  Remaining:{r['remaining_work']}" if r["remaining_work"] else ""
        original = f"  Original:{r['original_estimate']}h" if r["original_estimate"] else ""
        completed = f"  Completed:{r['completed_work']}h" if r["completed_work"] else ""
        click.echo(f"  #{r['id']}  [{r['type']}]  [{r['state']}]  {date}{points}{effort}{remaining}{original}{completed}")
        click.echo(f"           {r['title']}")
        click.echo(f"           {r['url']}")

        # Show linked PRs
        with get_connection() as pr_conn:
            pr_rows = pr_conn.execute(
                "SELECT pr_id, repo, url FROM work_item_prs WHERE work_item_id = ? AND period = ? ORDER BY pr_id",
                (r["id"], period)
            ).fetchall()
        for pr in pr_rows:
            click.echo(f"           └─ PR #{pr['pr_id']} [{pr['repo']}]  {pr['url']}")

    click.echo(f"\n  Total: {len(rows)} items")


if __name__ == "__main__":
    cli()
