from datetime import datetime, timezone
from pathlib import Path
from client import ADOClient


def _parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    # ADO returns ISO 8601 with optional fractional seconds
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _review_time_hours(pr: dict) -> float | None:
    created = _parse_dt(pr.get("creationDate"))
    closed = _parse_dt(pr.get("closedDate"))
    if created and closed:
        return round((closed - created).total_seconds() / 3600, 2)
    return None


def fetch_pr_metrics(client: ADOClient, days: int = 90) -> dict:
    """
    Returns PR metrics for the configured repo over the last `days` days.
    Includes open/closed counts, average review time, and merge rate.
    """
    path = f"/git/repositories/{client.repo}/pullrequests"

    # Fetch completed PRs
    completed = client.get_paginated(path, {"searchCriteria.status": "completed"})
    # Fetch active PRs
    active = client.get_paginated(path, {"searchCriteria.status": "active"})
    # Fetch abandoned PRs
    abandoned = client.get_paginated(path, {"searchCriteria.status": "abandoned"})

    # Filter completed/abandoned to the requested time window
    cutoff = datetime.now(timezone.utc).timestamp() - days * 86400

    def within_window(pr):
        closed = _parse_dt(pr.get("closedDate"))
        return closed and closed.timestamp() >= cutoff

    completed_window = [p for p in completed if within_window(p)]
    abandoned_window = [p for p in abandoned if within_window(p)]

    review_times = [_review_time_hours(p) for p in completed_window]
    review_times = [t for t in review_times if t is not None]

    total_closed = len(completed_window) + len(abandoned_window)
    merge_rate = (
        round(len(completed_window) / total_closed * 100, 1) if total_closed else 0
    )

    # Per-author breakdown
    author_counts: dict[str, int] = {}
    for pr in completed_window:
        author = pr.get("createdBy", {}).get("displayName", "unknown")
        author_counts[author] = author_counts.get(author, 0) + 1

    return {
        "window_days": days,
        "open": len(active),
        "completed": len(completed_window),
        "abandoned": len(abandoned_window),
        "merge_rate_pct": merge_rate,
        "avg_review_time_hours": (
            round(sum(review_times) / len(review_times), 2) if review_times else None
        ),
        "min_review_time_hours": min(review_times) if review_times else None,
        "max_review_time_hours": max(review_times) if review_times else None,
        "completed_by_author": dict(
            sorted(author_counts.items(), key=lambda x: x[1], reverse=True)
        ),
    }
