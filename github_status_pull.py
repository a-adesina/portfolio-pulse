"""
Portfolio Pulse — GitHub Status Pull
=====================================
Pulls delivery signal directly from GitHub's API for a set of tracked
repositories: no status forms, no developer self-reporting, no manual
updates. This is the "data-led, tells me" layer.

Five distinct signals per repo, all pulled directly:
  1. Whether the project is active or stale (commit activity on the
     DEFAULT BRANCH specifically, not just "something got pushed
     somewhere" — see the fix note below)
  2. Code delivery velocity (PRs merged)
  3. Whether the code functioned as expected or caught errors (CI/check
     status on the latest commit)
  4. Tickets/CRs raised and resolved (issues opened and closed in the
     tracking window)
  5. (Joined in pulse_core.py, not here) budget position

Usage:
    python3 github_status_pull.py

Auth:
    Unauthenticated calls are rate-limited to 60/hour by GitHub. This pull
    now makes 4-6 calls per repo (repo info, default-branch commit, CI
    check-runs, legacy status fallback, issue activity), so the
    unauthenticated ceiling covers roughly 10 repos per hour, not more.
    For real scale, 40-50 concurrent projects, set GITHUB_TOKEN to raise
    the limit to 5,000/hour:

        export GITHUB_TOKEN=ghp_xxxxxxxxxxxx

FIX IMPLEMENTED (previously a real bug, caught by verify_pull.py):
    The original version used the repo object's `pushed_at` field for
    staleness. That field reflects a push to ANY branch, so a bot branch,
    a docs branch, or a stray PR branch getting touched could make a
    genuinely stalled project look active. This version queries the
    commits endpoint scoped to the repo's actual default branch instead,
    the same signal `git log` on that branch would show, which is what
    a staleness check should actually be asking.
"""

import os
import sys
import json
import time
import requests
from datetime import datetime, timezone

import pulse_log

STALENESS_THRESHOLD_DAYS = 21  # no commit on default branch past this = stale
PR_VELOCITY_WINDOW_DAYS = 30   # window for counting merged PRs as recent delivery
TICKET_ACTIVITY_WINDOW_DAYS = 30  # window for counting issues opened/closed

# Retry scope, deliberately narrow: only conditions where retrying can
# plausibly help. A rate-limit response is NOT in this list on purpose,
# retrying immediately against an exhausted limit wastes a call and
# cannot succeed until the window resets on GitHub's side, no amount of
# local backoff fixes that. Retrying it would be the wrong lesson to
# encode: not every failure is worth retrying, only the transient ones.
MAX_RETRIES = 3
RETRY_BACKOFF_BASE_SECONDS = 1  # 1s, 2s, 4s

TRACKED_REPOS = [
    "tiangolo/fastapi",
    "pallets/flask",
    "psf/requests",
    "github/gitignore",
    "octocat/Hello-World",
]

API_BASE = "https://api.github.com"

# Set by main() at the start of a real run; left None when functions here
# are called directly (e.g. from unit tests), in which case log_event
# still writes a valid entry, just with run_id: null — never a reason to
# skip logging, only a reason the entry won't group with a specific run.
_CURRENT_RUN_ID = None


def _headers():
    token = os.environ.get("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _get(url, params=None):
    """Retries only on genuinely transient conditions: connection errors,
    timeouts, and 5xx server responses. A 403 rate-limit response and a
    404 are NOT retried, they are not transient, and retrying them would
    either waste a call against a limit that won't reset in time, or
    retry a request that will never succeed."""
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, headers=_headers(), params=params, timeout=15)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            last_error = e
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF_BASE_SECONDS * (2 ** attempt)
                print(f"  ! Connection issue on {url} ({e.__class__.__name__}), "
                      f"retrying in {wait}s ({attempt + 1}/{MAX_RETRIES})...", file=sys.stderr)
                time.sleep(wait)
                continue
            print(f"  ! Connection failed on {url} after {MAX_RETRIES} attempts: {e}", file=sys.stderr)
            return None

        if resp.status_code == 403 and "rate limit" in resp.text.lower():
            print(f"  ! Rate limited on {url}. Set GITHUB_TOKEN to raise the limit. Not retrying, this won't resolve itself within a retry window.", file=sys.stderr)
            pulse_log.log_event(_CURRENT_RUN_ID, "rate_limited", url=url)
            return None
        if resp.status_code == 404:
            return None
        if 500 <= resp.status_code < 600:
            last_error = f"{resp.status_code}: {resp.text[:150]}"
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF_BASE_SECONDS * (2 ** attempt)
                print(f"  ! Server error {resp.status_code} on {url}, "
                      f"retrying in {wait}s ({attempt + 1}/{MAX_RETRIES})...", file=sys.stderr)
                time.sleep(wait)
                continue
            print(f"  ! Server error persisted on {url} after {MAX_RETRIES} attempts: {last_error}", file=sys.stderr)
            return None
        if resp.status_code != 200:
            print(f"  ! {resp.status_code} on {url}: {resp.text[:150]}", file=sys.stderr)
            return None
        return resp.json()

    return None


def days_since(iso_timestamp):
    if not iso_timestamp:
        return None
    then = datetime.strptime(iso_timestamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    return (now - then).days


def get_default_branch_last_commit(owner_repo, default_branch):
    """The fix: ask specifically about the default branch, not repo.pushed_at.
    Now also validated: an unexpected response shape (a schema change, a
    partial response) is caught here and reported clearly, rather than
    raising an uncaught KeyError deep in the pull, which previously would
    have taken down the entire batch, not just this one repo."""
    commits = _get(
        f"{API_BASE}/repos/{owner_repo}/commits",
        params={"sha": default_branch, "per_page": 1},
    )
    if not commits or not isinstance(commits, list) or len(commits) == 0:
        return None, None

    commit_entry = commits[0]
    if not isinstance(commit_entry, dict):
        print(f"  ! Unexpected commit response shape for {owner_repo}: not a dict", file=sys.stderr)
        return None, None

    sha = commit_entry.get("sha")
    commit_date = commit_entry.get("commit", {}).get("committer", {}).get("date")

    if not sha or not commit_date:
        print(f"  ! Commit response for {owner_repo} missing expected fields "
              f"(sha or commit.committer.date), treating as no data rather than guessing", file=sys.stderr)
        return None, None

    return sha, commit_date
    commit_date = commits[0]["commit"]["committer"]["date"]
    return sha, commit_date


def get_ci_status(owner_repo, sha):
    """Checks the modern Checks API first (what GitHub Actions populates),
    falls back to the legacy combined-status API (third-party CI like
    older Travis/CircleCI setups). Returns one of:
    'success' | 'failure' | 'pending' | 'no_ci_configured'"""
    if not sha:
        return "no_ci_configured"

    check_runs = _get(f"{API_BASE}/repos/{owner_repo}/commits/{sha}/check-runs")
    runs = (check_runs or {}).get("check_runs", [])
    if runs:
        conclusions = [r.get("conclusion") for r in runs]
        statuses = [r.get("status") for r in runs]
        if "failure" in conclusions or "timed_out" in conclusions:
            return "failure"
        if any(s in ("queued", "in_progress") for s in statuses):
            return "pending"
        return "success"

    # Fall back to the legacy combined status API
    legacy = _get(f"{API_BASE}/repos/{owner_repo}/commits/{sha}/status")
    if legacy and legacy.get("total_count", 0) > 0:
        state = legacy.get("state")  # success | failure | pending, GitHub-computed
        return state if state in ("success", "failure", "pending") else "no_ci_configured"

    return "no_ci_configured"


def get_ticket_activity(owner_repo, window_days):
    """Issues opened and closed in the tracking window. Real, honest limits:
    - PRs are filtered out (GitHub's issues endpoint returns both).
    - `since` filters by updated_at, not created_at, so results are
      fetched as a superset and filtered precisely client-side against
      actual created_at / closed_at.
    - Single page (100 items), no pagination. Fine at this demo's scale;
      a genuinely high-traffic repo would need pagination in production."""
    from datetime import timedelta
    window_start = datetime.now(timezone.utc) - timedelta(days=window_days)
    window_start_iso = window_start.strftime("%Y-%m-%dT%H:%M:%SZ")

    items = _get(
        f"{API_BASE}/repos/{owner_repo}/issues",
        params={"state": "all", "since": window_start_iso, "per_page": 100},
    )
    items = [i for i in (items or []) if "pull_request" not in i]

    opened = sum(1 for i in items if i.get("created_at", "") >= window_start_iso)
    closed = sum(1 for i in items if i.get("closed_at") and i["closed_at"] >= window_start_iso)
    return opened, closed


def pull_repo_status(owner_repo):
    """Pull real delivery, code-health, and ticket signal for one repo.
    No manual input anywhere."""
    print(f"Pulling {owner_repo} ...")
    repo = _get(f"{API_BASE}/repos/{owner_repo}")
    if repo is None:
        pulse_log.log_event(_CURRENT_RUN_ID, "repo_pull_failed", repo=owner_repo,
                             reason="repo_lookup_failed")
        return None

    default_branch = repo.get("default_branch", "main")

    # THE FIX: default-branch commit date, not repo.pushed_at
    last_commit_sha, last_commit_date = get_default_branch_last_commit(owner_repo, default_branch)

    # SECOND FIX, caught the same way as the first, by actually running
    # this repeatedly under real, flaky network conditions rather than
    # trusting it because the logic looked right: if the commit lookup
    # itself failed partway through this pull (a rate limit hit here
    # specifically, not on the initial repo lookup, or a genuinely
    # commit-less repo), `last_commit_date` is None, and the old
    # `staleness_days is not None and staleness_days > THRESHOLD` check
    # silently evaluated to False in that case, reporting the project as
    # NOT stale, i.e. implying healthy, when the truth is "unknown."
    # A rate-limit hiccup could make a genuinely dead project look
    # active. Treating this as a failed pull for the repo, the same
    # honest "no data" path a 404 on the initial repo lookup already
    # takes, is the correct fix: silence should never resolve to looking
    # healthy.
    if last_commit_date is None:
        print(f"  ! Could not determine last commit for {owner_repo} (commit lookup "
              f"failed or returned no commits), treating as no data for this repo "
              f"rather than reporting a false 'active' status.", file=sys.stderr)
        pulse_log.log_event(_CURRENT_RUN_ID, "repo_pull_failed", repo=owner_repo,
                             reason="commit_lookup_failed_or_empty")
        return None

    staleness_days = days_since(last_commit_date)
    is_stale = staleness_days is not None and staleness_days > STALENESS_THRESHOLD_DAYS

    ci_status = get_ci_status(owner_repo, last_commit_sha)

    # GitHub quirk, same as before: /issues returns PRs too; filter on the
    # pull_request key's presence for a clean open-issue count.
    open_issues_and_prs = _get(
        f"{API_BASE}/repos/{owner_repo}/issues", params={"state": "open", "per_page": 100}
    )
    open_issues = [i for i in (open_issues_and_prs or []) if "pull_request" not in i]

    # /pulls?state=closed returns PRs closed without merging too; only a
    # non-null merged_at means real delivery happened.
    closed_prs = _get(
        f"{API_BASE}/repos/{owner_repo}/pulls",
        params={"state": "closed", "sort": "updated", "direction": "desc", "per_page": 30},
    )
    merged_recent = 0
    if closed_prs:
        for pr in closed_prs:
            if pr.get("merged_at"):
                d = days_since(pr["merged_at"])
                if d is not None and d <= PR_VELOCITY_WINDOW_DAYS:
                    merged_recent += 1

    tickets_opened, tickets_closed = get_ticket_activity(owner_repo, TICKET_ACTIVITY_WINDOW_DAYS)

    pulse_log.log_event(
        _CURRENT_RUN_ID, "repo_pull_succeeded", repo=owner_repo,
        stale=is_stale, ci_status=ci_status, days_since_commit=staleness_days,
        open_issues=len(open_issues),
    )

    return {
        "repo": owner_repo,
        "default_branch": default_branch,
        "last_commit_date": last_commit_date,
        "days_since_last_commit": staleness_days,
        "stale": is_stale,
        "ci_status": ci_status,
        "open_issues": len(open_issues),
        "tickets_opened_recent": tickets_opened,
        "tickets_closed_recent": tickets_closed,
        "prs_merged_last_30d": merged_recent,
        "open_issues_total_field_includes_prs": repo.get("open_issues_count"),
    }


def main():
    global _CURRENT_RUN_ID
    _CURRENT_RUN_ID = pulse_log.new_run_id()
    pulse_log.log_event(_CURRENT_RUN_ID, "run_started", tracked_repo_count=len(TRACKED_REPOS))

    results = []
    for r in TRACKED_REPOS:
        try:
            status = pull_repo_status(r)
        except Exception as e:
            # One malformed repo response must not take down the whole
            # batch. Report it plainly and continue, rather than let an
            # unhandled exception here silently drop every repo after
            # the one that failed, a worse outcome than one missing row.
            print(f"  ! Unexpected error pulling {r}: {e.__class__.__name__}: {e}", file=sys.stderr)
            pulse_log.log_event(_CURRENT_RUN_ID, "repo_pull_failed", repo=r,
                                 reason=f"unexpected_error: {e.__class__.__name__}: {e}")
            status = None
        if status:
            results.append(status)

    out_path = os.path.join(os.path.dirname(__file__), "pull_results.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)

    pulse_log.log_event(_CURRENT_RUN_ID, "run_finished",
                         succeeded=len(results), attempted=len(TRACKED_REPOS))

    print(f"\nPulled {len(results)}/{len(TRACKED_REPOS)} repos successfully.")
    print(f"Raw results written to {out_path}")
    print(f"Structured run log: {pulse_log.LOG_PATH} (run_id={_CURRENT_RUN_ID})")
    return results


if __name__ == "__main__":
    main()
