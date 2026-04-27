"""fetch.py — pull data from Azure DevOps and store in azdopal.db"""
import json
import sys
from pathlib import Path
import click
from client import ADOClient
from pr_metrics import fetch_pr_metrics
from commit_stats import fetch_commit_stats
from engineer_activity import fetch_engineer_activity, fetch_all_engineers_activity
from db import init_db, get_connection, get_all_repos, upsert_sprint, upsert_team, upsert_team_member, list_teams as db_list_teams
from common import parse_date, load_repos_for_patterns, handle_errors, resolve_date_range, ENGINEERS_FILE, REPOS_FILE, REPOS_DIR


def _emit(data: dict, output: str | None):
    json_str = json.dumps(data, indent=2)
    if output:
        with open(output, "w") as f:
            f.write(json_str)
        click.echo(f"Written to {output}")
    else:
        click.echo(json_str)


@click.group()
def cli():
    """azdopal fetch — pull data from Azure DevOps into the local database."""


@cli.command()
@click.option("--days", default=90, show_default=True, help="Lookback window in days.")
@click.option("--output", "-o", default=None, help="Write JSON to this file path.")
@handle_errors
def prs(days, output):
    """Fetch PR metrics for the configured repo (ADO_REPO in .env)."""
    client = ADOClient()
    data = fetch_pr_metrics(client, days=days)
    _emit(data, output)


@cli.command()
@click.option("--days", default=90, show_default=True, help="Lookback window in days.")
@click.option("--output", "-o", default=None, help="Write JSON to this file path.")
@handle_errors
def commits(days, output):
    """Fetch commit activity for the configured repo (ADO_REPO in .env)."""
    client = ADOClient()
    data = fetch_commit_stats(client, days=days)
    _emit(data, output)


@cli.command()
@click.option("--eng", default=None, help="Engineer email. If omitted, reads from engineers.json or discovers all.")
@click.option("--from", "from_date", default=None, callback=parse_date, is_eager=True, help="Start date dd-mm-yyyy.")
@click.option("--to", "to_date", default=None, callback=parse_date, is_eager=True, help="End date dd-mm-yyyy.")
@click.option("--sprint", default=None, help="Sprint name (alternative to --from/--to).")
@click.option("--namespaces", "-n", default=None, help="Comma-separated glob patterns e.g. 'Sports.*,Racing.*'. Scans all repos if omitted.")
@click.option("--refresh-repos", is_flag=True, default=False, help="Force re-fetch repo list from ADO.")
@handle_errors
def engineer(eng, from_date, to_date, sprint, namespaces, refresh_repos):
    """Fetch commits & PRs for engineers across all repos and save to DB."""
    if from_date and to_date and from_date > to_date:
        raise click.UsageError("--from date must be before --to date.")

    if eng:
        engineers = [eng]
    else:
        if ENGINEERS_FILE.exists():
            engineers = json.loads(ENGINEERS_FILE.read_text()) or None
            if engineers:
                click.echo(f"Loaded {len(engineers)} engineers from {ENGINEERS_FILE}.", err=True)
        else:
            engineers = None
        if engineers is None:
            click.echo("No engineer filter — will discover all engineers from the data.", err=True)

    client = ADOClient()
    init_db()

    with get_connection() as conn:
        from_dt, to_dt, period = resolve_date_range(from_date, to_date, sprint, conn)

        ns_list = [n.strip() for n in namespaces.split(",")] if namespaces else None
        if ns_list:
            repos_override = load_repos_for_patterns(ns_list, conn)
            if not repos_override:
                raise click.UsageError("No repos found for the given patterns.")
            click.echo(f"Scanning {len(repos_override)} repos matching: {', '.join(ns_list)}", err=True)
        else:
            db_repos = get_all_repos(conn)
            repos_override = db_repos if db_repos else None
            if repos_override:
                click.echo(f"Using {len(repos_override)} repos from database.", err=True)

        if engineers and len(engineers) == 1:
            email = engineers[0]
            click.echo(f"\nFetching activity for {email} from {from_dt.date()} to {to_dt.date()} ...", err=True)
            data = fetch_engineer_activity(
                client, email, from_dt, to_dt,
                refresh_repos=refresh_repos,
                repos_override=repos_override,
                conn=conn,
            )
            summary = data["summary"]
            click.echo(f"Done. {summary['total_commits']} commits, {summary['total_prs']} PRs.", err=True)
            click.echo("Saved to azdopal.db.", err=True)
        else:
            click.echo(
                f"\nFetching activity from {from_dt.date()} to {to_dt.date()} "
                f"({'all engineers' if engineers is None else f'{len(engineers)} engineers'}) ...",
                err=True,
            )
            all_data = fetch_all_engineers_activity(
                client, engineers, from_dt, to_dt,
                refresh_repos=refresh_repos,
                repos_override=repos_override,
                conn=conn,
            )
            click.echo(f"\nResults for {len(all_data)} engineer(s):", err=True)
            for email, data in all_data.items():
                summary = data["summary"]
                click.echo(f"  {email}: {summary['total_commits']} commits, {summary['total_prs']} PRs.", err=True)
            click.echo(f"Saved {len(all_data)} engineer(s) to azdopal.db.", err=True)


@cli.command()
@handle_errors
def backfill_periods():
    """Replace date-based period strings with sprint names where a matching sprint exists."""
    from db import list_sprints as db_list_sprints

    init_db()
    with get_connection() as conn:
        sprints = db_list_sprints(conn)
        if not sprints:
            click.echo("No sprints in DB. Run 'python3 fetch.py sync-sprints' first.")
            return

        # Build a map from date-period string → sprint name
        period_map: dict[str, str] = {}
        for s in sprints:
            if s.get("start_date") and s.get("end_date"):
                start = s["start_date"][:10].replace("-", "/")
                end = s["end_date"][:10].replace("-", "/")
                date_period = f"{start} - {end}"
                period_map[date_period] = s["name"]

        if not period_map:
            click.echo("No sprints with dates found.")
            return

        total_updated = 0
        for table in ("commits", "pull_requests", "engineer_activity",
                      "work_items", "scanned_repos"):
            for date_period, sprint_name in period_map.items():
                try:
                    result = conn.execute(
                        f"UPDATE {table} SET period = ? WHERE period = ?",
                        (sprint_name, date_period)
                    )
                    if result.rowcount:
                        click.echo(f"  {table}: {result.rowcount} rows updated "
                                   f"'{date_period}' → '{sprint_name}'")
                        total_updated += result.rowcount
                except Exception as e:
                    click.echo(f"  Warning: {table}: {e}", err=True)

        conn.commit()
        click.echo(f"\nDone. {total_updated} rows updated across all tables.")


@cli.command()
@click.option("--team", default=None, help="Sync members for a specific team (partial match). If omitted, syncs all teams.")
@handle_errors
def sync_team_members(team):
    """Sync team members from Azure DevOps into the local DB."""
    import requests as req

    client = ADOClient()
    init_db()

    with get_connection() as conn:
        if team:
            from db import get_team_by_name
            t = get_team_by_name(conn, team)
            if not t:
                raise click.UsageError(f"Team '{team}' not found. Run 'python3 fetch.py sync-teams' first.")
            teams_to_sync = [t]
        else:
            teams_to_sync = db_list_teams(conn)
            if not teams_to_sync:
                raise click.UsageError("No teams in DB. Run 'python3 fetch.py sync-teams' first.")

        total = 0
        for t in teams_to_sync:
            team_id = t["id"]
            team_name = t["name"]
            skip = 0
            top = 100
            team_total = 0

            # First try the capacity endpoint for each sprint (gives actual sprint members)
            # Fall back to the general members endpoint
            from db import list_sprints as db_list_sprints
            team_sprints = db_list_sprints(conn, team_name)
            capacity_emails: set[str] = set()

            for sprint in team_sprints[:10]:  # check recent sprints for capacity data
                cap_url = f"https://dev.azure.com/{client.org}/{client.project}/{team_name}/_apis/work/teamsettings/iterations/{sprint['id']}/capacities"
                cap_resp = req.get(cap_url, headers=client.headers,
                                   params={"api-version": "7.1"}, timeout=30)
                if cap_resp.ok:
                    for cap in cap_resp.json().get("value", []):
                        identity = cap.get("teamMember", {})
                        email = identity.get("uniqueName", "").lower()
                        display = identity.get("displayName", "")
                        if email and email not in capacity_emails:
                            capacity_emails.add(email)
                            upsert_team_member(conn, team_id, team_name, email, display)
                            team_total += 1

            if capacity_emails:
                conn.commit()
                click.echo(f"  {team_name}: {len(capacity_emails)} members from capacity data.")
                total += len(capacity_emails)
                continue

            # Fall back to general members endpoint with pagination
            while True:
                url = f"https://dev.azure.com/{client.org}/_apis/projects/{client.project}/teams/{team_id}/members"
                response = req.get(url, headers=client.headers,
                                   params={"api-version": "7.1", "$top": top, "$skip": skip},
                                   timeout=30)
                if not response.ok:
                    click.echo(f"  Warning: could not fetch members for '{team_name}': {response.status_code}", err=True)
                    break

                members = response.json().get("value", [])
                for m in members:
                    identity = m.get("identity", {})
                    email = identity.get("uniqueName", "").lower()
                    display = identity.get("displayName", "")
                    if email:
                        upsert_team_member(conn, team_id, team_name, email, display)

                conn.commit()
                team_total += len(members)
                if len(members) < top:
                    break
                skip += top

            total += team_total
            click.echo(f"  {team_name}: {team_total} members synced.")

    click.echo(f"\nDone. {total} team member records saved to azdopal.db.")


@cli.command()
@handle_errors
def sync_teams():
    """Sync all teams from Azure DevOps into the local DB."""
    client = ADOClient()
    init_db()

    data = client.org_get(f"/projects/{client.project}/teams", {"$top": 100})
    teams = data.get("value", [])
    if not teams:
        click.echo("No teams found.")
        return

    with get_connection() as conn:
        for team in teams:
            upsert_team(conn, {
                "id": team.get("id"),
                "name": team.get("name"),
                "description": team.get("description", ""),
            })
        conn.commit()

    click.echo(f"Synced {len(teams)} teams to azdopal.db:")
    for t in sorted(teams, key=lambda x: x["name"]):
        click.echo(f"  {t['name']}")


@cli.command()
@handle_errors
def list_teams():
    """List all synced teams."""
    init_db()
    with get_connection() as conn:
        teams = db_list_teams(conn)
    if not teams:
        click.echo("No teams in DB. Run 'python3 fetch.py sync-teams' first.")
        return
    click.echo(f"\n{'Name':<50} {'ID'}")
    click.echo("-" * 90)
    for t in teams:
        click.echo(f"  {t['name']:<48} {t['id']}")


@cli.command()
@click.option("--team", default=None, help="Team name (partial match). If omitted, syncs sprints for all teams.")
@handle_errors
def sync_sprints(team):
    """Sync sprints/iterations from Azure DevOps into the local DB."""
    import os
    import requests as req

    client = ADOClient()
    init_db()

    with get_connection() as conn:
        if team:
            from db import get_team_by_name
            t = get_team_by_name(conn, team)
            if not t:
                raise click.UsageError(f"Team '{team}' not found. Run 'python3 fetch.py sync-teams' first.")
            teams_to_sync = [t]
        else:
            teams_to_sync = db_list_teams(conn)
            if not teams_to_sync:
                # Fall back to ADO_TEAM env var
                ado_team = os.getenv("ADO_TEAM")
                if not ado_team:
                    raise click.UsageError(
                        "No teams in DB and ADO_TEAM not set. "
                        "Run 'python3 fetch.py sync-teams' first, or set ADO_TEAM in .env."
                    )
                teams_to_sync = [{"name": ado_team, "id": ado_team}]

        total = 0
        for t in teams_to_sync:
            team_name = t["name"]
            click.echo(f"  Syncing sprints for team: {team_name} ...", err=True)

            url = f"https://dev.azure.com/{client.org}/{client.project}/{team_name}/_apis/work/teamsettings/iterations"
            response = req.get(url, headers=client.headers, params={"api-version": "7.1"}, timeout=30)
            if not response.ok:
                click.echo(f"  Warning: could not fetch iterations for '{team_name}': {response.status_code}", err=True)
                continue

            iterations = response.json().get("value", [])
            for it in iterations:
                attrs = it.get("attributes", {})
                upsert_sprint(conn, {
                    "id": it.get("id"),
                    "name": it.get("name"),
                    "team_name": team_name,
                    "path": it.get("path"),
                    "start_date": attrs.get("startDate"),
                    "end_date": attrs.get("finishDate"),
                    "time_frame": attrs.get("timeFrame"),
                })
            conn.commit()
            total += len(iterations)
            click.echo(f"  {len(iterations)} sprints synced for '{team_name}'.")

    click.echo(f"\nDone. {total} sprints total saved to azdopal.db.")


@cli.command()
@click.option("--team", default=None, help="Filter by team name (partial match).")
@handle_errors
def list_sprints(team):
    """List all synced sprints."""
    from db import list_sprints as db_list_sprints, get_team_by_name
    init_db()
    with get_connection() as conn:
        team_name = None
        if team:
            t = get_team_by_name(conn, team)
            team_name = t["name"] if t else team
        sprints = db_list_sprints(conn, team_name)
    if not sprints:
        click.echo("No sprints in DB. Run 'python3 fetch.py sync-sprints' first.")
        return
    click.echo(f"\n{'Name':<40} {'Team':<35} {'Start':<12} {'End':<12} {'Timeframe'}")
    click.echo("-" * 105)
    for s in sprints:
        click.echo(f"  {s['name']:<38} {s.get('team_name',''):<33} {(s['start_date'] or '')[:10]:<12} {(s['end_date'] or '')[:10]:<12} {s['time_frame'] or ''}")


@cli.command()
@click.option("--output-dir", "-d", default="repos", show_default=True, help="Directory to write namespace files into.")
@handle_errors
def split_repos(output_dir):
    """Split repos.json into per-namespace files based on the first part of the repo name."""
    if not REPOS_FILE.exists():
        click.echo("repos.json not found.", err=True)
        return
    repos = json.loads(REPOS_FILE.read_text())
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    namespaces: dict[str, list] = {}
    for repo in repos:
        name = repo.get("name", "")
        namespace = name.split(".")[0] if "." in name else name
        namespaces.setdefault(namespace, []).append(repo)
    for namespace, ns_repos in sorted(namespaces.items()):
        out_file = out_dir / f"repos_{namespace}.json"
        out_file.write_text(json.dumps(ns_repos, indent=2))
        click.echo(f"  {namespace}: {len(ns_repos)} repos → {out_file}")
    click.echo(f"\n{len(namespaces)} namespace files written to {out_dir}.")


@cli.command()
@handle_errors
def dedup_repos():
    """Remove duplicate entries from repos.json."""
    if not REPOS_FILE.exists():
        click.echo("repos.json not found.", err=True)
        return
    repos = json.loads(REPOS_FILE.read_text())
    seen, unique = set(), []
    for r in repos:
        if r["id"] not in seen:
            seen.add(r["id"])
            unique.append(r)
    removed = len(repos) - len(unique)
    REPOS_FILE.write_text(json.dumps(unique, indent=2))
    click.echo(f"Removed {removed} duplicates. {len(unique)} unique repos in repos.json.")


@cli.command()
@click.option("--from", "from_date", default=None, callback=parse_date, is_eager=True, help="Start date dd-mm-yyyy.")
@click.option("--to", "to_date", default=None, callback=parse_date, is_eager=True, help="End date dd-mm-yyyy.")
@click.option("--sprint", default=None, help="Sprint name or number (alternative to --from/--to).")
@click.option("--team", default=None, help="Team name to scope the sprint lookup (partial match).")
@click.option("--eng", default=None, help="Filter by engineer email. If omitted, fetches all items in the sprint.")
@click.option("--with-pr-links", is_flag=True, default=False, help="Also fetch linked PRs for each work item (slower — one extra API call per item).")
@handle_errors
def work_items(from_date, to_date, sprint, team, eng, with_pr_links):
    """Fetch ADO work items for a sprint/date range and save to DB.

    Without --eng: fetches all work items in the sprint iteration path.
    With --eng: fetches items assigned to that engineer.
    """
    from db import upsert_work_item

    client = ADOClient()
    init_db()

    fields = [
        "System.Id", "System.Title", "System.WorkItemType",
        "System.State", "System.AreaPath", "System.IterationPath",
        "System.AssignedTo", "System.Parent",
        "Microsoft.VSTS.Common.ActivatedDate",
        "Microsoft.VSTS.Common.ClosedDate",
        "Microsoft.VSTS.Scheduling.StoryPoints",
        "Microsoft.VSTS.Scheduling.Effort",
        "Microsoft.VSTS.Scheduling.RemainingWork",
        "Microsoft.VSTS.Scheduling.OriginalEstimate",
        "Microsoft.VSTS.Scheduling.CompletedWork",
        "System.CreatedDate", "System.ChangedDate",
    ]

    with get_connection() as conn:
        from_dt, to_dt, period = resolve_date_range(from_date, to_date, sprint, conn, team)
        from_str = from_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        to_str = to_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        if eng:
            # Per-engineer mode: query by AssignedTo + date range
            click.echo(f"\nFetching work items for {eng} in {period} ...", err=True)
            wiql = {
                "query": f"""
                    SELECT [System.Id] FROM WorkItems
                    WHERE [System.AssignedTo] = '{eng}'
                    AND [System.ChangedDate] >= '{from_str}'
                    AND [System.ChangedDate] <= '{to_str}'
                    ORDER BY [System.ChangedDate] DESC
                """
            }
            _fetch_and_save_work_items(client, conn, wiql, fields, period, eng, with_pr_links)
        elif team:
            # Team mode: fetch all items in the team's sprint iteration path
            from db import get_sprint_by_name, get_team_by_name
            t = get_team_by_name(conn, team)
            if not t:
                raise click.UsageError(f"Team '{team}' not found. Run 'python3 fetch.py sync-teams' first.")

            # Get the sprint record scoped to this team
            sprint_record = get_sprint_by_name(conn, sprint, t["name"]) if sprint else None
            if sprint_record and sprint_record.get("path"):
                iter_path = sprint_record["path"].replace("'", "''")
                click.echo(f"\nFetching all work items in '{iter_path}' for team '{t['name']}' ...", err=True)
                wiql = {
                    "query": f"SELECT [System.Id] FROM WorkItems WHERE [System.IterationPath] = '{iter_path}' ORDER BY [System.AssignedTo] ASC"
                }
                # assigned_to=None so each item uses its own AssignedTo field
                _fetch_and_save_work_items(client, conn, wiql, fields, period, assigned_to=None, with_pr_links=with_pr_links)
            else:
                raise click.UsageError(f"Could not find iteration path for sprint '{sprint}' in team '{team}'. Run 'python3 fetch.py sync-sprints --team \"{team}\"' first.")
        else:
            # Sprint-wide mode: query by iteration path
            # Get the sprint's iteration path from DB
            from db import get_sprint_by_name
            sprint_record = get_sprint_by_name(conn, sprint) if sprint else None
            if sprint_record and sprint_record.get("path"):
                iter_path = sprint_record["path"].replace("'", "''")  # escape single quotes
                click.echo(f"\nFetching all work items in '{iter_path}' ({period}) ...", err=True)
                wiql = {
                    "query": f"SELECT [System.Id] FROM WorkItems WHERE [System.IterationPath] = '{iter_path}' ORDER BY [System.ChangedDate] DESC"
                }
            else:
                # Fall back to date range with no engineer filter
                click.echo(f"\nFetching all work items changed in {period} ...", err=True)
                wiql = {
                    "query": f"""
                        SELECT [System.Id] FROM WorkItems
                        WHERE [System.ChangedDate] >= '{from_str}'
                        AND [System.ChangedDate] <= '{to_str}'
                        ORDER BY [System.ChangedDate] DESC
                    """
                }
            _fetch_and_save_work_items(client, conn, wiql, fields, period, assigned_to=None, with_pr_links=with_pr_links)

    click.echo(f"\nDone. Work items saved to azdopal.db.")


def _fetch_and_save_work_items(client, conn, wiql: dict, fields: list,
                                period: str, assigned_to: str | None,
                                with_pr_links: bool = False) -> int:
    """Returns the number of work items found."""
    from db import upsert_work_item

    try:
        result = client.post("/wit/wiql", wiql)
    except RuntimeError as e:
        click.echo(f"  Error querying work items: {e}", err=True)
        return 0

    work_item_refs = result.get("workItems", [])
    if not work_item_refs:
        return 0

    click.echo(f"  Found {len(work_item_refs)} work items.", err=True)
    ids = [r["id"] for r in work_item_refs]

    for batch_start in range(0, len(ids), 200):
        batch = ids[batch_start:batch_start + 200]
        try:
            details = client.post("/wit/workitemsbatch", {"ids": batch, "fields": fields})
        except RuntimeError as e:
            click.echo(f"  Error fetching batch: {e}", err=True)
            continue

        for item in details.get("value", []):
            f = item.get("fields", {})
            assigned = assigned_to or (f.get("System.AssignedTo") or {}).get("uniqueName", "unassigned")
            wi_id = item.get("id")
            parent_id = f.get("System.Parent")
            wi = {
                "id": wi_id,
                "title": f.get("System.Title"),
                "type": f.get("System.WorkItemType"),
                "state": f.get("System.State"),
                "area_path": f.get("System.AreaPath"),
                "iteration_path": f.get("System.IterationPath"),
                "story_points": f.get("Microsoft.VSTS.Scheduling.StoryPoints"),
                "effort": f.get("Microsoft.VSTS.Scheduling.Effort"),
                "remaining_work": f.get("Microsoft.VSTS.Scheduling.RemainingWork"),
                "original_estimate": f.get("Microsoft.VSTS.Scheduling.OriginalEstimate"),
                "completed_work": f.get("Microsoft.VSTS.Scheduling.CompletedWork"),
                "parent_id": parent_id,
                "activated_date": f.get("Microsoft.VSTS.Common.ActivatedDate"),
                "resolved_date": f.get("Microsoft.VSTS.Common.ClosedDate"),
                "created_date": f.get("System.CreatedDate"),
                "changed_date": f.get("System.ChangedDate"),
                "url": f"https://dev.azure.com/{client.org}/{client.project}/_workitems/edit/{wi_id}",
            }
            upsert_work_item(conn, period, assigned, wi)

            # Fetch relations separately to get linked PRs
            if with_pr_links:
                from db import upsert_work_item_pr
                import re, time as _time
                try:
                    rel_data = client.get(f"/wit/workitems/{wi_id}", {"$expand": "relations"})
                    for rel in rel_data.get("relations", []) or []:
                        rel_url = rel.get("url", "")
                        match = re.search(r'PullRequestId/[^/]+/([^/]+)/(\d+)', rel_url)
                        if match:
                            repo_name = match.group(1)
                            pr_id = int(match.group(2))
                            pr_url = f"https://dev.azure.com/{client.org}/{client.project}/_git/{repo_name}/pullrequest/{pr_id}"
                            upsert_work_item_pr(conn, wi_id, period, pr_id, repo_name, pr_url)
                    _time.sleep(0.1)  # avoid rate limiting
                except RuntimeError:
                    pass

        conn.commit()

    return len(work_item_refs)


@cli.command()
@click.option("--from", "from_date", required=True, callback=parse_date, is_eager=True, help="Start date dd-mm-yyyy.")
@click.option("--to", "to_date", required=True, callback=parse_date, is_eager=True, help="End date dd-mm-yyyy.")
@click.option("--namespaces", "-n", default=None, help="Comma-separated glob patterns to limit scope.")
@handle_errors
def update_pr_lines(from_date, to_date, namespaces):
    """Backfill lines_added/lines_deleted for PRs that are missing line counts."""
    from engineer_activity import _fetch_pr_line_counts
    from db import upsert_pr

    period = f"{from_date.strftime('%Y/%m/%d')} - {to_date.strftime('%Y/%m/%d')}"
    client = ADOClient()
    init_db()

    with get_connection() as conn:
        ns_list = [n.strip() for n in namespaces.split(",")] if namespaces else None
        repo_filter = ""
        params = [period]
        if ns_list:
            placeholders = " OR ".join("repo GLOB ?" for _ in ns_list)
            repo_filter = f"AND ({placeholders})"
            for ns in ns_list:
                params.append(ns if ("*" in ns or "?" in ns) else f"{ns}.*")

        rows = conn.execute(f"""
            SELECT pr_id, repo, engineer_email, title, status,
                   source_branch, target_branch, created_date, closed_date,
                   review_time_hours, url
            FROM   pull_requests
            WHERE  period = ?
            AND    (lines_added IS NULL OR lines_deleted IS NULL)
            {repo_filter}
        """, params).fetchall()

        if not rows:
            click.echo("No PRs with missing line counts found.")
            return

        click.echo(f"Updating line counts for {len(rows)} PRs in period: {period}")

        repo_id_map = {r["name"]: r["id"] for r in conn.execute(
            "SELECT name, id FROM repos"
        ).fetchall()}

        updated = 0
        for i, row in enumerate(rows):
            repo_name = row["repo"]
            pr_id = row["pr_id"]
            repo_id = repo_id_map.get(repo_name)

            sys.stderr.write(f"  [{i + 1}/{len(rows)}] PR #{pr_id} in {repo_name} ... ")
            sys.stderr.flush()

            if not repo_id:
                sys.stderr.write("repo not in DB, skipped\n")
                continue

            lines_added, lines_deleted = _fetch_pr_line_counts(client, repo_id, pr_id)
            pr_dict = dict(row)
            pr_dict["lines_added"] = lines_added
            pr_dict["lines_deleted"] = lines_deleted

            upsert_pr(conn, period, row["engineer_email"], pr_dict)
            conn.commit()
            updated += 1
            sys.stderr.write(f"+{lines_added}/-{lines_deleted}\n")

        click.echo(f"\nDone. Updated {updated}/{len(rows)} PRs.")


if __name__ == "__main__":
    cli()
