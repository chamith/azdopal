# Requirements: Sync Toggle PRs & Commits

## Requirement 1: Default Sync Behavior (PRs Only)

### User Story
As a user viewing the Sprint Summary page, I want the sync button to only sync PRs by default, so that I get faster sync times without waiting for commit scanning.

### Acceptance Criteria
- 1.1 When the user clicks the Sync button without changing any toggle, only PRs are fetched from Azure DevOps
- 1.2 The `/api/sync-code` endpoint defaults `sync_prs_only` to `true` when the parameter is not provided
- 1.3 When `sync_prs_only=true`, no commit records are created or updated in the database for that sync run
- 1.4 When `sync_prs_only=true`, the response message reflects that only PRs were synced (e.g., "Synced 23 PRs from 5 engineers")
- 1.5 When `sync_prs_only=true`, the response `commits` field is 0

## Requirement 2: Include Commits Toggle

### User Story
As a user, I want a toggle control that lets me include commits in the sync operation, so that I can fetch commit data when I need it.

### Acceptance Criteria
- 2.1 A checkbox/toggle labeled "Include Commits" is displayed next to the Sync button in the page header
- 2.2 The toggle defaults to OFF (unchecked) on page load
- 2.3 When the toggle is ON and the user clicks Sync, both PRs and commits are fetched from Azure DevOps
- 2.4 When the toggle is ON, the API is called with `sync_prs_only=false`
- 2.5 The toggle state persists during the current page session (does not reset between syncs)
- 2.6 The toggle is disabled while a sync operation is in progress

## Requirement 3: Backend `skip_commits` Support

### User Story
As the system, I need to conditionally skip commit scanning in the engineer activity module, so that PR-only syncs are faster and don't make unnecessary API calls.

### Acceptance Criteria
- 3.1 The `fetch_all_engineers_activity` function accepts a `skip_commits` boolean parameter (default `False`)
- 3.2 The `_scan_repo` function accepts a `skip_commits` boolean parameter (default `False`)
- 3.3 When `skip_commits=True`, no branch listing API calls are made to Azure DevOps
- 3.4 When `skip_commits=True`, no commit fetching API calls are made to Azure DevOps
- 3.5 When `skip_commits=True`, PRs are still fetched and stored normally
- 3.6 When `skip_commits=False`, the behavior is identical to the current implementation (no regression)

## Requirement 4: API Response Consistency

### User Story
As a frontend consumer, I want the sync API response to accurately reflect what was synced, so that I can display correct feedback to the user.

### Acceptance Criteria
- 4.1 When `sync_prs_only=true`, the response `commits` field equals 0
- 4.2 When `sync_prs_only=false`, the response `commits` field equals the total commits synced
- 4.3 The response `message` string indicates whether only PRs or both PRs and commits were synced
- 4.4 The response structure (fields: `engineers`, `commits`, `prs`, `message`) remains unchanged
