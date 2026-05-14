import sys
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from client import ADOClient

REPO_CACHE = Path(__file__).parent / "repos.json"


def _parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _load_repos(repos_override: list[dict] | None) -> list[dict]:
    if repos_override is not None:
        # Deduplicate by id
        seen: set[str] = set()
        unique = []
        for r in repos_override:
            rid = r.get("id") or r.get("name")
            if rid not in seen:
                seen.add(rid)
                unique.append(r)
        return unique
    if not REPO_CACHE.exists():
        sys.stderr.write("  Warning: repos.json not found. Run with --refresh-repos to build the cache.\n")
        sys.stderr.flush()
        return []
    repos = json.loads(REPO_CACHE.read_text())
    seen: set[str] = set()
    unique = []
    for r in repos:
        rid = r.get("id") or r.get("name")
        if rid not in seen:
            seen.add(rid)
            unique.append(r)
    return unique


def _make_summary(prs: list[dict], commits: list[dict]) -> dict:
    return {
        "total_commits": len(commits),
        "total_prs": len(prs),
        "prs_completed": sum(1 for p in prs if p["status"] == "completed"),
        "prs_active": sum(1 for p in prs if p["status"] == "active"),
        "prs_abandoned": sum(1 for p in prs if p["status"] == "abandoned"),
    }


def _flush_repo_to_db(
    conn: sqlite3.Connection,
    period: str,
    from_date: str,
    to_date: str,
    repo_name: str,
    repo_prs: dict[str, dict],       # email -> {branch -> count}
    repo_commits: dict[str, dict],   # email -> {branch -> count}
    all_prs: dict[str, list],        # email -> [pr dicts]
    all_commits: dict[str, list],    # email -> [commit dicts]
):
    """Upsert all engineer/branch rows and individual records for one repo."""
    from db import upsert_activity, upsert_commit, upsert_pr

    all_keys: set[tuple] = set()
    for email, branches in repo_prs.items():
        for branch in branches:
            all_keys.add((email, branch))
    for email, branches in repo_commits.items():
        for branch in branches:
            all_keys.add((email, branch))

    for email, branch in all_keys:
        upsert_activity(
            conn,
            period=period,
            from_date=from_date,
            to_date=to_date,
            engineer_email=email,
            repo=repo_name,
            branch=branch,
            pr_count=repo_prs.get(email, {}).get(branch, 0),
            commit_count=repo_commits.get(email, {}).get(branch, 0),
        )

    # Write individual commits for this repo
    for email, commits in all_commits.items():
        for c in commits:
            if c.get("repo") == repo_name:
                upsert_commit(conn, period, email, c)

    # Write individual PRs for this repo
    for email, prs in all_prs.items():
        for pr in prs:
            if pr.get("repo") == repo_name:
                upsert_pr(conn, period, email, pr)

    conn.commit()


def _fetch_pr_line_counts(client: ADOClient, repo_id: str, pr_id: int) -> tuple[int, int]:
    """
    Fetch lines added and deleted for a PR via its iterations.
    Returns (lines_added, lines_deleted). Returns (0, 0) on failure.
    """
    try:
        data = client.get(
            f"/git/repositories/{repo_id}/pullrequests/{pr_id}/iterations",
            {"includeCommits": "false"},
        )
        iterations = data.get("value", [])
        if not iterations:
            return 0, 0
        # Use the last iteration (most recent) for the overall diff stats
        last = iterations[-1]
        stats = last.get("changeList", {})
        # ADO doesn't return line counts in iterations directly —
        # use the iteration changes endpoint for the last iteration
        iter_id = last.get("id")
        changes_data = client.get(
            f"/git/repositories/{repo_id}/pullrequests/{pr_id}/iterations/{iter_id}/changes"
        )
        added = 0
        deleted = 0
        for change in changes_data.get("changeEntries", []):
            counts = change.get("lineCounts", {})
            added += counts.get("added", 0)
            deleted += counts.get("deleted", 0)
        return added, deleted
    except RuntimeError:
        return 0, 0


def _scan_repo(
    client: ADOClient,
    repo: dict,
    emails: set[str] | None,
    from_str: str,
    to_str: str,
    # accumulators passed in by reference
    prs_by_eng: dict,
    commits_by_eng: dict,
    # DB params
    conn: sqlite3.Connection | None,
    period: str,
    from_date: str,
    to_date: str,
):
    repo_id = repo["id"]
    repo_name = repo["name"]

    # Per-repo accumulators for DB flush
    repo_prs: dict[str, dict] = defaultdict(lambda: defaultdict(int))
    repo_commits: dict[str, dict] = defaultdict(lambda: defaultdict(int))

    # --- PRs ---
    for status in ("active", "completed", "abandoned"):
        params = {
            "searchCriteria.status": status,
            "searchCriteria.minTime": from_str,
            "searchCriteria.maxTime": to_str,
        }
        try:
            prs = client.get_paginated(
                f"/git/repositories/{repo_id}/pullrequests", params
            )
        except RuntimeError:
            continue

        for pr in prs:
            creator_email = pr.get("createdBy", {}).get("uniqueName", "").lower()
            if not creator_email:
                continue
            if emails is not None and creator_email not in emails:
                continue

            created = _parse_dt(pr.get("creationDate"))
            closed = _parse_dt(pr.get("closedDate"))
            review_hours = None
            if created and closed:
                review_hours = round((closed - created).total_seconds() / 3600, 2)

            source_branch = pr.get("sourceRefName", "").replace("refs/heads/", "")
            pr_id = pr.get("pullRequestId")
            lines_added, lines_deleted = _fetch_pr_line_counts(client, repo_id, pr_id)
            entry = {
                "repo": repo_name,
                "pr_id": pr_id,
                "title": pr.get("title"),
                "status": pr.get("status"),
                "source_branch": source_branch,
                "target_branch": pr.get("targetRefName", "").replace("refs/heads/", ""),
                "created_date": pr.get("creationDate"),
                "closed_date": pr.get("closedDate"),
                "review_time_hours": review_hours,
                "lines_added": lines_added,
                "lines_deleted": lines_deleted,
                "url": (
                    f"https://dev.azure.com/{client.org}/{client.project}"
                    f"/_git/{repo_name}/pullrequest/{pr_id}"
                ),
            }
            prs_by_eng[creator_email].append(entry)
            repo_prs[creator_email][source_branch] += 1

    # --- Commits (all branches) ---
    try:
        refs_data = client.get(
            f"/git/repositories/{repo_id}/refs",
            {"filter": "heads/", "$top": 1000},
        )
        branches = [
            r.get("name", "").replace("refs/heads/", "")
            for r in refs_data.get("value", [])
        ]
    except RuntimeError:
        branches = []

    seen: dict[str, set] = defaultdict(set)

    for branch in branches:
        try:
            commits = client.get_paginated(
                f"/git/repositories/{repo_id}/commits",
                {
                    "searchCriteria.fromDate": from_str,
                    "searchCriteria.toDate": to_str,
                    "searchCriteria.itemVersion.version": branch,
                    "searchCriteria.itemVersion.versionType": "branch",
                },
            )
        except RuntimeError:
            continue

        for c in commits:
            author_email = c.get("author", {}).get("email", "").lower()
            if not author_email:
                continue
            if emails is not None and author_email not in emails:
                continue
            commit_id = c.get("commitId")
            if commit_id in seen[author_email]:
                continue
            seen[author_email].add(commit_id)
            entry = {
                "repo": repo_name,
                "branch": branch,
                "commit_id": commit_id,
                "message": (c.get("comment") or "").splitlines()[0],
                "date": c.get("author", {}).get("date"),
                "url": c.get("remoteUrl"),
            }
            commits_by_eng[author_email].append(entry)
            repo_commits[author_email][branch] += 1

    # --- Flush this repo to DB ---
    if conn is not None:
        _flush_repo_to_db(
            conn, period, from_date, to_date, repo_name,
            repo_prs, repo_commits,
            prs_by_eng, commits_by_eng,
        )
        from db import mark_repo_scanned
        mark_repo_scanned(conn, period, repo_name)

    pr_total = sum(len(v) for v in repo_prs.values())
    commit_total = sum(sum(v.values()) for v in repo_commits.values())
    return pr_total, commit_total, len(branches)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_engineer_activity(
    client: ADOClient,
    email: str,
    from_dt: datetime,
    to_dt: datetime,
    refresh_repos: bool = False,
    repos_override: list[dict] | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict:
    results = fetch_all_engineers_activity(
        client, [email], from_dt, to_dt,
        refresh_repos=refresh_repos,
        repos_override=repos_override,
        conn=conn,
    )
    return results[email]


def fetch_all_engineers_activity(
    client: ADOClient,
    emails: list[str] | None,
    from_dt: datetime,
    to_dt: datetime,
    refresh_repos: bool = False,
    repos_override: list[dict] | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, dict]:
    if refresh_repos:
        _refresh_repo_cache(client)

    repos = _load_repos(repos_override)
    if not repos:
        return {}

    email_set = {e.lower() for e in emails} if emails is not None else None
    label = f"{len(emails)} engineer(s)" if emails else "all engineers"
    sys.stderr.write(f"\nFetching data for {label} across {len(repos)} repos...\n")
    sys.stderr.flush()

    from_str = from_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    to_str = to_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    from_date = from_dt.strftime("%Y-%m-%d")
    to_date = to_dt.strftime("%Y-%m-%d")
    period = f"{from_date.replace('-', '/')} - {to_date.replace('-', '/')}"

    prs_by_eng: dict[str, list] = defaultdict(list)
    commits_by_eng: dict[str, list] = defaultdict(list)

    # Check which repos are already scanned for this period
    scanned: set[str] = set()
    if conn is not None:
        from db import get_scanned_repos
        scanned = get_scanned_repos(conn, period)
        if scanned:
            sys.stderr.write(f"  Resuming — {len(scanned)} repos already scanned, skipping them.\n")
            sys.stderr.flush()

    for i, repo in enumerate(repos):
        repo_name = repo["name"]
        if repo_name in scanned:
            sys.stderr.write(f"  [{i + 1}/{len(repos)}] {repo_name} ... skipped (already scanned)\n")
            sys.stderr.flush()
            continue

        sys.stderr.write(f"  [{i + 1}/{len(repos)}] {repo_name} ... ")
        sys.stderr.flush()

        pr_count, commit_count, branch_count = _scan_repo(
            client, repo, email_set,
            from_str, to_str,
            prs_by_eng, commits_by_eng,
            conn, period, from_date, to_date,
        )
        sys.stderr.write(f"{pr_count} PRs, {commit_count} commits across {branch_count} branches\n")
        sys.stderr.flush()

    # Build per-engineer result dicts
    all_emails = set(prs_by_eng.keys()) | set(commits_by_eng.keys())
    ordered = emails if emails is not None else sorted(all_emails)

    results = {}
    for email in ordered:
        key = email.lower()
        prs = sorted(prs_by_eng.get(key, []), key=lambda p: p.get("created_date") or "", reverse=True)
        commits = sorted(commits_by_eng.get(key, []), key=lambda c: c.get("date") or "", reverse=True)
        results[email] = {
            "engineer": email,
            "from": from_date,
            "to": to_date,
            "summary": _make_summary(prs, commits),
            "commits": commits,
            "pull_requests": prs,
        }

    return results


def _refresh_repo_cache(client: ADOClient):
    seen_ids: set[str] = set()
    repos: list[dict] = []
    if REPO_CACHE.exists():
        for r in json.loads(REPO_CACHE.read_text()):
            if r["id"] not in seen_ids:
                seen_ids.add(r["id"])
                repos.append(r)
        sys.stderr.write(f"  Found {len(repos)} unique repos in existing cache.\n")
        sys.stderr.flush()
        return  # Use cache if it exists

    top = 1000
    sys.stderr.write(f"  Fetching project repos from ADO...\n")
    sys.stderr.flush()

    # Fetch repos scoped to the project (not the entire org)
    data = client.get("/git/repositories")
    page = data.get("value", [])
    for r in page:
        if r["id"] not in seen_ids and not r.get("isDisabled"):
            seen_ids.add(r["id"])
            repos.append(r)

    REPO_CACHE.write_text(json.dumps(repos, indent=2))
    sys.stderr.write(f"  Done. {len(repos)} repos cached to {REPO_CACHE}.\n")
    sys.stderr.flush()
