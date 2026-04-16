from collections import defaultdict
from datetime import datetime, timedelta, timezone
from client import ADOClient


def fetch_commit_stats(client: ADOClient, days: int = 90) -> dict:
    """
    Returns commit activity for the configured repo over the last `days` days.
    Includes frequency by day, top contributors, and file hotspots.
    """
    from_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    path = f"/git/repositories/{client.repo}/commits"
    commits = client.get_paginated(
        path,
        {
            "searchCriteria.fromDate": from_date,
            "searchCriteria.itemVersion.version": "",  # default branch
        },
    )

    # Frequency by date
    daily: dict[str, int] = defaultdict(int)
    contributors: dict[str, int] = defaultdict(int)

    for commit in commits:
        author = commit.get("author", {})
        date_str = author.get("date", "")
        if date_str:
            day = date_str[:10]  # YYYY-MM-DD
            daily[day] += 1
        name = author.get("name", "unknown")
        contributors[name] += 1

    # File hotspots — fetch changed files for each commit (capped at 50 commits)
    file_counts: dict[str, int] = defaultdict(int)
    for commit in commits[:50]:
        commit_id = commit.get("commitId")
        if not commit_id:
            continue
        try:
            detail = client.get(
                f"/git/repositories/{client.repo}/commits/{commit_id}/changes"
            )
            for change in detail.get("changes", []):
                path_str = change.get("item", {}).get("path", "")
                if path_str:
                    file_counts[path_str] += 1
        except Exception:
            continue

    top_files = sorted(file_counts.items(), key=lambda x: x[1], reverse=True)[:20]

    return {
        "window_days": days,
        "total_commits": len(commits),
        "daily_frequency": dict(sorted(daily.items())),
        "contributors": dict(
            sorted(contributors.items(), key=lambda x: x[1], reverse=True)
        ),
        "file_hotspots": [{"path": p, "commit_count": c} for p, c in top_files],
    }
