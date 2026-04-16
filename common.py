"""Shared helpers used by both fetch.py and view.py."""
import os
from datetime import datetime, timezone
from pathlib import Path
import click
from db import get_repos_by_pattern, get_all_repos, get_sprint_by_name

ENGINEERS_FILE = Path(__file__).parent / "engineers.json"
REPOS_FILE = Path(__file__).parent / "repos.json"
REPOS_DIR = Path(__file__).parent / "repos"


def parse_date(ctx, param, value: str) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.strptime(value, "%d-%m-%Y").replace(tzinfo=timezone.utc)
    except ValueError:
        raise click.BadParameter("Expected format: dd-mm-yyyy (e.g. 01-01-2026)")


def resolve_date_range(from_date, to_date, sprint, conn) -> tuple[datetime, datetime, str]:
    """
    Resolve a date range from either explicit --from/--to or a --sprint name.
    Returns (from_dt, to_dt, period_label).
    period_label is the sprint name if --sprint was used, otherwise the date range string.
    """
    if sprint:
        s = get_sprint_by_name(conn, sprint)
        if not s:
            raise click.UsageError(
                f"Sprint '{sprint}' not found in DB. Run 'python3 fetch.py sync-sprints' first."
            )
        if not s.get("start_date") or not s.get("end_date"):
            raise click.UsageError(f"Sprint '{sprint}' has no start/end dates in ADO.")
        from_dt = datetime.strptime(s["start_date"][:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        to_dt = datetime.strptime(s["end_date"][:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        period_label = s["name"]
        click.echo(f"Sprint '{period_label}': {from_dt.date()} → {to_dt.date()}", err=True)
        return from_dt, to_dt, period_label
    if not from_date or not to_date:
        raise click.UsageError("Provide either --sprint or both --from and --to.")
    period_label = f"{from_date.strftime('%Y/%m/%d')} - {to_date.strftime('%Y/%m/%d')}"
    return from_date, to_date, period_label


def load_repos_for_patterns(patterns: list[str], conn) -> list[dict]:
    """Return repos from DB matching glob patterns like 'Sports.*'."""
    count = conn.execute("SELECT COUNT(*) FROM repos").fetchone()[0]
    if count == 0:
        click.echo("  No repos in DB — falling back to repos.json.", err=True)
        import json
        if not REPOS_FILE.exists():
            return []
        all_repos = json.loads(REPOS_FILE.read_text())
        # Filter by namespace prefix
        result = []
        for pattern in patterns:
            ns = pattern.rstrip(".*")
            matched = [r for r in all_repos if r["name"].startswith(ns)]
            click.echo(f"  Pattern '{pattern}': {len(matched)} repos", err=True)
            result.extend(matched)
        return result

    repos = []
    for pattern in patterns:
        if "*" not in pattern and "?" not in pattern:
            matched = get_repos_by_pattern(conn, f"{pattern}.*") + get_repos_by_pattern(conn, pattern)
        else:
            matched = get_repos_by_pattern(conn, pattern)
        if not matched:
            click.echo(f"  Warning: no repos matched pattern '{pattern}'.", err=True)
        else:
            click.echo(f"  Pattern '{pattern}': {len(matched)} repos", err=True)
        repos.extend(matched)

    seen, unique = set(), []
    for r in repos:
        if r["id"] not in seen:
            seen.add(r["id"])
            unique.append(r)
    return unique


def handle_errors(fn):
    """Decorator that wraps a click command with standard error handling."""
    import functools
    import sys

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except EnvironmentError as e:
            click.echo(f"Config error: {e}", err=True)
            sys.exit(1)
        except RuntimeError as e:
            click.echo(f"API error:\n{e}", err=True)
            sys.exit(1)
        except Exception as e:
            click.echo(f"Unexpected error: {e}", err=True)
            sys.exit(1)
    return wrapper
