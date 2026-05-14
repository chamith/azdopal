# Tasks: Sync Toggle PRs & Commits

## Task 1: Add `skip_commits` parameter to `_scan_repo`

**Requirements covered**: 3.2, 3.3, 3.4, 3.5

**File**: `engineer_activity.py`

- [ ] 1.1 Add `skip_commits: bool = False` parameter to `_scan_repo` function signature
- [ ] 1.2 Wrap the "Commits (all branches)" section in an `if not skip_commits:` guard
- [ ] 1.3 When `skip_commits=True`, set `branches = []` and skip branch/commit API calls
- [ ] 1.4 Ensure PR scanning logic remains unchanged regardless of `skip_commits` value
- [ ] 1.5 Return `(pr_count, 0, 0)` when `skip_commits=True`

## Task 2: Add `skip_commits` parameter to `fetch_all_engineers_activity`

**Requirements covered**: 3.1, 3.6

**File**: `engineer_activity.py`

- [ ] 2.1 Add `skip_commits: bool = False` parameter to `fetch_all_engineers_activity` function signature
- [ ] 2.2 Pass `skip_commits` through to each `_scan_repo` call
- [ ] 2.3 Add `skip_commits` parameter to `fetch_engineer_activity` wrapper and pass it through
- [ ] 2.4 Verify that `skip_commits=False` produces identical behavior to current implementation

## Task 3: Add `sync_prs_only` query parameter to `/api/sync-code` endpoint

**Requirements covered**: 1.1, 1.2, 1.3, 1.4, 1.5, 4.1, 4.2, 4.3, 4.4

**File**: `web/api/main.py`

- [ ] 3.1 Add `sync_prs_only: bool = True` parameter to the `sync_code` function signature
- [ ] 3.2 Pass `skip_commits=sync_prs_only` to `fetch_all_engineers_activity`
- [ ] 3.3 Update the response message: when `sync_prs_only=True`, show "Synced N PRs from M engineers" (omit commits count)
- [ ] 3.4 When `sync_prs_only=False`, keep the existing message format "Synced X commits, Y PRs from M engineers"
- [ ] 3.5 Ensure response `commits` field is 0 when `sync_prs_only=True`

## Task 4: Add "Include Commits" toggle to SprintSummary UI

**Requirements covered**: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6

**File**: `web/ui/src/pages/SprintSummary.tsx`

- [ ] 4.1 Add `includeCommits` state with `useState(false)`
- [ ] 4.2 Add a checkbox/toggle labeled "Include Commits" next to the Sync button in the header
- [ ] 4.3 Modify `handleSync` to pass `sync_prs_only: String(!includeCommits)` in the POST params
- [ ] 4.4 Disable the toggle while `syncing` is true
- [ ] 4.5 Add CSS styling for the toggle (`.sync-toggle` class) to align inline with the sync button

## Task 5: Verify end-to-end behavior

**Requirements covered**: 1.1, 2.3, 3.6, 4.1

- [ ] 5.1 Test: Click Sync with toggle OFF → verify only PRs are synced (commits = 0 in response)
- [ ] 5.2 Test: Click Sync with toggle ON → verify both PRs and commits are synced
- [ ] 5.3 Test: Verify toggle defaults to OFF on page load
- [ ] 5.4 Test: Verify toggle is disabled during sync operation
