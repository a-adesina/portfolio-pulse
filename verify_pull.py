"""
Portfolio Pulse — Pull Verification
======================================
Answers a specific, practical question: how do you confirm the pulled
delivery data is actually correct, without gambling on a live demo
working in the room?

This script cross-checks each repo's recorded last-commit signal against
an INDEPENDENT source, `git clone --depth 1` directly against github.com's
git protocol, not api.github.com's REST endpoint. That distinction
matters twice over: it's a different rate-limit pool entirely (git clone
isn't subject to the same 60-requests-per-hour unauthenticated cap that
github_status_pull.py can hit, which has happened twice during this
build), and it's a genuinely different code path reading the same
underlying fact, which is what makes it a real check rather than the
same call run twice.

WHAT THIS VERIFIER'S ROLE ACTUALLY WAS, AND WHAT IT IS NOW:
The first time this ran, it caught a real bug: the primary pull was using
the repo's `pushed_at` field, which reflects a push to ANY branch, not the
default branch specifically. That's now fixed, github_status_pull.py
queries the commits endpoint scoped to the actual default branch, the
same signal `git log` reads here. That means this verifier now checks the
SAME fact via two independent methods (REST API vs. git protocol), so a
tight match is the expected normal case, not a coincidence. A divergence
found now would mean something different and rarer than before, API
propagation lag, a caching quirk, or a genuine new bug, not the
wrong-field class of error already fixed.

The intended workflow is NOT "run this live in an interview either."
Run it once, ahead of time, save verification_report.md, and that saved
report is the evidence. Showing a saved, dated verification report is a
stronger claim than a live demo anyway: a live demo only proves it worked
once, in that moment, with a favorable network. A saved report you can
walk through line by line, including where it caught a real discrepancy,
proves you verified it and know what "wrong" would have looked like.

Usage:
    python3 verify_pull.py
    (reads pull_results.json in the same directory; point PULL_RESULTS_PATH
    at a saved snapshot instead if you want to verify an older pull)
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

# Point this at any saved pull_results.json snapshot to verify it after
# the fact, not just the most recent live pull.
PULL_RESULTS_PATH = os.path.join(os.path.dirname(__file__), "pull_results.json")

# A day-level match, not exact-timestamp equality, is the right bar here.
# See the note on pushed_at vs. default-branch commit date below.
MATCH_TOLERANCE_DAYS = 1


def days_since(iso_ts):
    dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - dt).days


def git_last_commit_date(owner_repo):
    """Shallow-clone the default branch and read its last commit date.
    Zero calls to api.github.com; this talks to github.com's git protocol
    directly, a genuinely separate code path and a separate rate limit
    pool (git clone has no comparable hourly cap for occasional use)."""
    url = f"https://github.com/{owner_repo}.git"
    tmp = tempfile.mkdtemp(prefix="pulse_verify_")
    try:
        subprocess.run(
            ["git", "clone", "--quiet", "--depth", "1", "--single-branch", url, tmp],
            check=True, capture_output=True, timeout=30,
        )
        result = subprocess.run(
            ["git", "-C", tmp, "log", "-1", "--format=%cI"],
            check=True, capture_output=True, text=True,
        )
        return result.stdout.strip()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    if not os.path.exists(PULL_RESULTS_PATH):
        print(f"No pull results found at {PULL_RESULTS_PATH}.", file=sys.stderr)
        print("Run github_status_pull.py first, or point PULL_RESULTS_PATH at a saved snapshot.", file=sys.stderr)
        sys.exit(1)

    with open(PULL_RESULTS_PATH) as f:
        results = json.load(f)

    lines = [
        "# Pull Verification Report",
        "",
        f"Run {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC. "
        "Independent check via `git clone --depth 1`, zero GitHub API calls. "
        "Works even when api.github.com's rate limit is fully exhausted.",
        "",
        "Post-fix status: the primary pull now reads the same default-branch "
        "commit signal this verifier checks, via a different code path (REST "
        "API vs. git protocol). A tight match is the expected normal case. A "
        "divergence here now points to something new, API propagation lag, "
        "a caching quirk, or a genuine bug, worth investigating on its own "
        "terms rather than assumed benign.",
        "",
        "| Repo | Recorded last_commit_date | Recorded days | git log last commit | git log days | Result |",
        "|---|---|---|---|---|---|",
    ]

    all_match = True
    for r in results:
        repo = r["repo"]
        recorded_push = r.get("last_commit_date")
        recorded_days = r.get("days_since_last_commit")
        print(f"Checking {repo} via git clone (no API call)...")
        try:
            git_date = git_last_commit_date(repo)
            git_days = days_since(git_date)
        except Exception as e:
            lines.append(f"| {repo} | {recorded_push} | {recorded_days} | ERROR: {e} | — | error |")
            all_match = False
            continue

        match = isinstance(recorded_days, int) and abs(git_days - recorded_days) <= MATCH_TOLERANCE_DAYS
        all_match = all_match and match
        lines.append(
            f"| {repo} | {recorded_push} | {recorded_days} | {git_date} | {git_days} | "
            f"{'match' if match else 'DIVERGES'} |"
        )

    lines.append("")
    lines.append(
        "**All repos match an independent git-based check.**" if all_match
        else "**At least one repo diverged from the independent check.** "
        "See the divergence note above before treating this as a pull error, "
        "then investigate the specific repo if the gap isn't explained by it."
    )

    report = "\n".join(lines)
    out_path = os.path.join(os.path.dirname(__file__), "verification_report.md")
    with open(out_path, "w") as f:
        f.write(report)

    print("\n" + report)
    print(f"\n\nWritten to {out_path}")


if __name__ == "__main__":
    main()
