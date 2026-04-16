import json
import sys
from datetime import datetime, timezone
from pathlib import Path
import click
from client import ADOClient
from pr_metrics import fetch_pr_metrics
from commit_stats import fetch_commit_stats
from engineer_activity import fetch_engineer_activity, fetch_all_engineers_activity
from db import save_engineer_results, init_db, get_connection, upsert_repo, get_repos_by_pattern, get_all_repos

ENGINEERS_FILE = Path(__file__).parent / "engineers.json"
REPOS_FILE = Path(__file__).parent / "repos.json"
REPOS_DIR = Path(__file__).parent / "repos"


def _parse_date(ctx, param, value: str) -> datetime:
    try:
        return datetime.strptime(value, "%d-%m-%Y").replace(tzinfo=timezone.utc)
    except ValueError:
        raise click.BadParameter("Expected format: dd-mm-yyyy (e.g. 01-01-2026)")


def _load_repos_for_patterns(patterns: list[str], conn) -> list[dict]:
    """
    Load repos from DB matching glob patterns like 'Sports.*', 'Racing.DataTools.*'.
    Falls back to namespace file lookup if DB has no repos.
    """
    # Check if repos table is populated
    count = conn.execute("SELECT COUNT(*) FROM repos").fetchone()[0]
    if count == 0:
        # Fall back to namespace JSON files
        click.echo("  No repos in DB — falling back to namespace JSON files.", err=True)
        return _load_repos_for_namespaces(patterns)

    repos = []
    for pattern in patterns:
        # If pattern has no wildcard, treat as namespace prefix: "Sports" -> "Sports.*"
        if "*" not in pattern and "?" not in pattern:
            glob = f"{pattern}.*"
            # Also match exact name (repos without dots)
            exact = get_repos_by_pattern(conn, pattern)
            matched = get_repos_by_pattern(conn, glob) + exact
        else:
            matched = get_repos_by_pattern(conn, pattern)

        if not matched:
            click.echo(f"  Warning: no repos matched pattern '{pattern}'.", err=True)
        else:
            click.echo(f"  Pattern '{pattern}': {len(matched)} repos", err=True)
        repos.extend(matched)

    # Deduplicate by id
    seen, unique = set(), []
    for r in repos:
        if r["id"] not in seen:
            seen.add(r["id"])
            unique.append(r)
    return unique


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
    """Azure DevOps PAL (azdopal) — repo stats CLI."""


@cli.command()
@click.option("--days", default=90, show_default=True, help="Lookback window in days.")
@click.option("--output", "-o", default=None, help="Write JSON to this file path.")
def prs(days, output):
    """Fetch PR metrics (open/closed counts, review times, merge rate)."""
    client = ADOClient()
    data = fetch_pr_metrics(client, days=days)
    _emit(data, output)


@cli.command()
@click.option("--days", default=90, show_default=True, help="Lookback window in days.")
@click.option("--output", "-o", default=None, help="Write JSON to this file path.")
def commits(days, output):
    """Fetch commit activity (frequency, contributors, file hotspots)."""
    client = ADOClient()
    data = fetch_commit_stats(client, days=days)
    _emit(data, output)


@cli.command()
@click.option("--days", default=90, show_default=True, help="Lookback window in days.")
@click.option("--output", "-o", default=None, help="Write JSON to this file path.")
def all_stats(days, output):
    """Fetch all stats and combine into a single JSON output."""
    client = ADOClient()
    data = {
        "pr_metrics": fetch_pr_metrics(client, days=days),
        "commit_stats": fetch_commit_stats(client, days=days),
    }
    _emit(data, output)


@cli.command()
@click.option("--eng", default=None, help="Engineer email. If omitted, reads from engineers.json.")
@click.option("--from", "from_date", required=True, callback=_parse_date, is_eager=True, help="Start date dd-mm-yyyy.")
@click.option("--to", "to_date", required=True, callback=_parse_date, is_eager=True, help="End date dd-mm-yyyy.")
@click.option("--namespaces", "-n", default=None, help="Comma-separated glob patterns, e.g. 'Sports.*,Racing.DataTools.*'. Scans all repos if omitted.")
@click.option("--refresh-repos", is_flag=True, default=False, help="Force re-fetch repo list from ADO.")
def engineer(eng, from_date, to_date, namespaces, refresh_repos):
    """List all commits and PRs by an engineer (or all in engineers.json) for a date range."""
    if from_date > to_date:
        raise click.UsageError("--from date must be before --to date.")

    if eng:
        engineers = [eng]
    else:
        if ENGINEERS_FILE.exists():
            engineers = json.loads(ENGINEERS_FILE.read_text())
            if engineers:
                click.echo(f"Loaded {len(engineers)} engineers from {ENGINEERS_FILE}.", err=True)
            else:
                engineers = None  # empty file → discover all
        else:
            engineers = None  # no file → discover all

        if engineers is None:
            click.echo("No engineer filter — will discover all engineers from the data.", err=True)

    client = ADOClient()
    init_db()

    with get_connection() as conn:
        # Resolve repo list from patterns or full DB/cache
        ns_list = [n.strip() for n in namespaces.split(",")] if namespaces else None
        if ns_list:
            repos_override = _load_repos_for_patterns(ns_list, conn)
            if not repos_override:
                raise click.UsageError("No repos found for the given patterns.")
            click.echo(f"Scanning {len(repos_override)} repos matching: {', '.join(ns_list)}", err=True)
        else:
            # Try loading all repos from DB first, fall back to repos.json
            db_repos = get_all_repos(conn)
            repos_override = db_repos if db_repos else None
            if repos_override:
                click.echo(f"Using {len(repos_override)} repos from database.", err=True)
        if engineers and len(engineers) == 1:
            email = engineers[0]
            click.echo(
                f"\nFetching activity for {email} from {from_date.date()} to {to_date.date()} ...",
                err=True,
            )
            data = fetch_engineer_activity(
                client, email, from_date, to_date,
                refresh_repos=refresh_repos,
                repos_override=repos_override,
                conn=conn,
            )
            summary = data["summary"]
            click.echo(f"Done. {summary['total_commits']} commits, {summary['total_prs']} PRs.", err=True)
            click.echo("Saved to database (azdopal.db).", err=True)
        else:
            click.echo(
                f"\nFetching activity from {from_date.date()} to {to_date.date()} "
                f"({'all engineers' if engineers is None else f'{len(engineers)} engineers'}) ...",
                err=True,
            )
            all_data = fetch_all_engineers_activity(
                client, engineers, from_date, to_date,
                refresh_repos=refresh_repos,
                repos_override=repos_override,
                conn=conn,
            )
            click.echo(f"\nResults for {len(all_data)} engineer(s):", err=True)
            for email, data in all_data.items():
                summary = data["summary"]
                click.echo(
                    f"  {email}: {summary['total_commits']} commits, {summary['total_prs']} PRs.",
                    err=True,
                )
            click.echo(f"Saved {len(all_data)} engineer(s) to database (azdopal.db).", err=True)


@cli.command()
@click.option("--output-dir", "-d", default="repos", show_default=True, help="Directory to write namespace files into.")
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


def main():
    try:
        cli()
    except EnvironmentError as e:
        click.echo(f"Config error: {e}", err=True)
        sys.exit(1)
    except RuntimeError as e:
        click.echo(f"API error:\n{e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Unexpected error: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
