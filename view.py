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
@click.option("--sprint", default=None, help="Sprint name (alternative to --from/--to).")
@click.option("--eng", default=None, help="Filter by engineer email (partial match supported).")
@handle_errors
def summary(from_date, to_date, sprint, eng):
    """Show a summary table of commits and PRs per engineer for a period."""
    init_db()
    with get_connection() as conn:
        from_dt, to_dt, period = resolve_date_range(from_date, to_date, sprint, conn)
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

    # Merge by email
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
@click.option("--sprint", default=None, help="Sprint name (alternative to --from/--to).")
@click.option("--eng", required=True, help="Engineer email (partial match supported).")
@click.option("--repo", default=None, help="Filter by repo name (partial match).")
@handle_errors
def commits(from_date, to_date, sprint, eng, repo):
    """List commits for an engineer in a period."""
    init_db()
    with get_connection() as conn:
        from_dt, to_dt, period = resolve_date_range(from_date, to_date, sprint, conn)
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
@click.option("--sprint", default=None, help="Sprint name (alternative to --from/--to).")
@click.option("--eng", required=True, help="Engineer email (partial match supported).")
@click.option("--repo", default=None, help="Filter by repo name (partial match).")
@click.option("--status", default=None, type=click.Choice(["active", "completed", "abandoned"]), help="Filter by PR status.")
@handle_errors
def prs(from_date, to_date, sprint, eng, repo, status):
    """List PRs for an engineer in a period."""
    init_db()
    with get_connection() as conn:
        from_dt, to_dt, period = resolve_date_range(from_date, to_date, sprint, conn)
        query = """
            SELECT created_date, repo, source_branch, target_branch,
                   status, review_time_hours, lines_added, lines_deleted, title, url
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
        lines = ""
        if r["lines_added"] or r["lines_deleted"]:
            lines = f"  +{r['lines_added'] or 0} / -{r['lines_deleted'] or 0} lines"
        click.echo(f"  {date}  [{r['status'].upper()}]  {r['repo']}")
        click.echo(f"           {r['source_branch']} → {r['target_branch']}  ({review}){lines}")
        click.echo(f"           {r['title']}")
        click.echo(f"           {r['url']}")
        click.echo()


@cli.command()
@click.option("--from", "from_date", default=None, callback=parse_date, is_eager=True, help="Start date dd-mm-yyyy.")
@click.option("--to", "to_date", default=None, callback=parse_date, is_eager=True, help="End date dd-mm-yyyy.")
@click.option("--sprint", default=None, help="Sprint name (alternative to --from/--to).")
@click.option("--eng", required=True, help="Engineer email (partial match supported).")
@click.option("--type", "item_type", default=None, help="Filter by type e.g. Bug, Task, User Story.")
@click.option("--state", default=None, help="Filter by state e.g. Active, Closed, Resolved.")
@handle_errors
def work_items(from_date, to_date, sprint, eng, item_type, state):
    """List work items assigned to an engineer in a period."""
    init_db()
    with get_connection() as conn:
        from_dt, to_dt, period = resolve_date_range(from_date, to_date, sprint, conn)
        query = """
            SELECT id, type, state, title, story_points, effort,
                   remaining_work, area_path, iteration_path, changed_date, url
            FROM   work_items
            WHERE  period = ?
            AND    engineer_email LIKE ?
        """
        params = [period, f"%{eng}%"]
        if item_type:
            query += " AND type = ?"
            params.append(item_type)
        if state:
            query += " AND state = ?"
            params.append(state)
        query += " ORDER BY changed_date DESC"
        rows = conn.execute(query, params).fetchall()

    click.echo(f"\nWork items for '{eng}' — period: {period}\n")
    if not rows:
        click.echo("  No work items found.")
        return

    for r in rows:
        date = (r["changed_date"] or "")[:10]
        points = f"  SP:{r['story_points']}" if r["story_points"] else ""
        effort = f"  Effort:{r['effort']}" if r["effort"] else ""
        remaining = f"  Remaining:{r['remaining_work']}" if r["remaining_work"] else ""
        click.echo(f"  #{r['id']}  [{r['type']}]  [{r['state']}]  {date}")
        click.echo(f"           {r['title']}{points}{effort}{remaining}")
        click.echo(f"           {r['iteration_path']}")
        click.echo(f"           {r['url']}")
        click.echo()

    # Summary by type and state
    click.echo(f"  Total: {len(rows)} items")


if __name__ == "__main__":
    cli()
