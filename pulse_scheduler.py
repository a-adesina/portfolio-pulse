"""
Portfolio Pulse — Priority-Aware Pull Scheduler
===================================================
Built to the corrected spec the user gave directly (their words, not a
restatement): "Build option 1. modify pull to once every 24 hours unless
prompted for more. no more than 3 pulls in a 24 hour window."

What "option 1" means, and why it's an honest approximation rather than
real event-driven ingestion: a true "refresh when the author updates the
code" trigger requires a webhook configured ON the tracked repo, which
requires admin access to it. All five `TRACKED_REPOS` in
`github_status_pull.py` are third-party repos this project does not
administer — tiangolo/fastapi, pallets/flask, psf/requests,
github/gitignore, octocat/Hello-World. No webhook can be registered on any
of them from here. "Option 1" substitutes a cheap, rate-limit-light
POLLING check for that: a conditional HTTP request (ETag / If-None-Match)
against each repo, run more often than a real pull, that can detect "did
something change" without spending real pull quota on repos that haven't
moved. This file is that scheduler. It is explicitly NOT a webhook
receiver and does not claim to be one.

The decision logic, in priority order, every time this runs:

  1. HARD CAP — never more than MAX_PULLS_PER_WINDOW (3) real pulls in any
     trailing ROLLING_WINDOW_HOURS (24) window. This wins over everything
     else below, including a detected change. "No more than 3 pulls in a
     24 hour window" was stated as an unconditional ceiling, not a ceiling
     that priority triggers get to ignore.
  2. BASELINE — if it's been >= BASELINE_INTERVAL_HOURS (24) since the
     last real pull (or there has never been one), pull now. This is the
     floor cadence: "once every 24 hours" happens regardless of whether
     anything changed.
  3. PRIORITY TRIGGER — if the baseline isn't due yet, but the cheap
     conditional check finds that at least one tracked repo actually
     changed since last checked, pull now anyway ("prompted for more").
     This is the one case that can pull before the 24h baseline elapses.
  4. Otherwise: skip this tick. Nothing is due.

What decide() depends on, and a real limitation stated plainly rather
than glossed over: the cap and baseline calculations read `run_started`
events out of `pulse_log.LOG_PATH` (the same structured log
`github_status_pull.py` already writes), and the priority check reads/
writes `etag_cache.json` (latest-commit SHAs; see below) next to it. In a GitHub Actions scheduled run,
every tick starts from a fresh checkout — neither file survives between
ticks unless something commits them back to the repo between runs. The
`.github/workflows/tests.yml` `unattended-pull` job does that explicitly
(see its "Persist scheduler state for the next tick" step) because
without it, every tick would see an empty log, call "baseline_due" every
single time, and this entire cadence would silently never apply. That's
a real dependency this mechanism has on how it's hosted, named here
on purpose, the same discipline as every other "this needs a real hosted
repo to actually prove" limitation already in SOW.md and README.md. It
has not been observed running end-to-end in a real hosted repo (same
stated boundary as the rest of the unattended-pull job).

What the change check compares, and why it changed twice after the first
hosted runs. Version 1 sent a conditional request (ETag / If-None-Match)
to the plain repo record. That record changes on any metadata movement
(stars, issue counts), so it would have fired early pulls on busy repos.
Version 2 moved to `GET /repos/{owner}/{repo}/commits?per_page=1` (the
default branch's newest commit), still compared by ETag. Observed on the
hosted repo: between the pull at 2026-11-25T16:06Z and the pull at
2026-11-26T07:26Z, the stored ETag changed for all five repos, including
octocat/Hello-World, while the newest-commit date recorded by the two
pulls was identical for all five (only the days-since count moved). A
matching date is strong but not conclusive evidence that no commit
landed. The ETag therefore changed with, as far as the data shows, no new
commit. The cause has NOT been established; candidate
explanations (ETag varying with the per-run GITHUB_TOKEN, or the endpoint
not honouring the conditional request) are unverified. Version 3, here,
stops depending on the ETag: each tick fetches the newest commit and
compares its SHA with the SHA saved on the previous tick. A SHA changes
only when a commit lands on the default branch. The cost is one small
unconditional request per repo per tick (per_page=1), which is cheap
against the authenticated rate limit. Cache keys carry a `sha:` prefix, so
values saved under earlier schemes are ignored and every repo gets one
first observation (recorded, never reported as a change). The cache file
is still named `etag_cache.json`; it now holds commit SHAs, and the name
was kept so the workflow's persist step did not need to change.
Not yet observed live with this version: a quiet tick that correctly
reports "no change" for all five repos. The decision log
(`scheduler_last_decision.json` and the `scheduler_decision` events)
records which repos were seen as changed on every tick, so the next
ticks will show whether it behaves as intended.

Usage:
    python3 pulse_scheduler.py
    # Logs a "scheduler_decision" event (so the decision itself is part of
    # the same structured history pulse_alert.py and this file both read),
    # writes scheduler_last_decision.json for the CI step that gates the
    # rest of the job on whether a real pull happened, and — only if the
    # decision is to pull — calls github_status_pull.main() directly.
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta

import requests

import pulse_log
import github_status_pull

ROLLING_WINDOW_HOURS = 24      # the cap's window
MAX_PULLS_PER_WINDOW = 3       # "no more than 3 pulls in a 24 hour window"
BASELINE_INTERVAL_HOURS = 24   # "once every 24 hours unless prompted for more"

ETAG_CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "etag_cache.json")
DECISION_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scheduler_last_decision.json")


def _trigger():
    """What started this run. In GitHub Actions the runner sets
    GITHUB_EVENT_NAME ("schedule", "workflow_dispatch", "push"); anywhere
    else it is "local". Recorded in every decision so the log itself can
    say whether a tick was scheduled or started by hand, instead of that
    being known only from someone's recollection of the Actions page."""
    return os.environ.get("GITHUB_EVENT_NAME") or "local"


def _parse_ts(ts):
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _load_run_started_times(log_path=None):
    """Every `run_started` event written by github_status_pull.main() is
    one real pull attempt, successful or not — a failed pull still spent
    quota and still counts against the cap. Malformed lines are skipped,
    not fatal, same discipline as pulse_alert.py's _load_events."""
    if log_path is None:
        log_path = pulse_log.LOG_PATH
    times = []
    if not os.path.exists(log_path):
        return times
    with open(log_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("event") == "run_started":
                t = _parse_ts(entry.get("ts"))
                if t is not None:
                    times.append(t)
    return sorted(times)


def _load_etag_cache(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_etag_cache(cache, path):
    try:
        with open(path, "w") as f:
            json.dump(cache, f, indent=2)
    except OSError as e:
        print(f"  ! Could not write ETag cache ({e.__class__.__name__}: {e}), "
              f"continuing without it — next tick will just see every repo as "
              f"'changed' once, costing at most one extra, still-capped pull.",
              file=sys.stderr)


def _fetch_latest_sha(owner_repo):
    """Returns (status_code_or_None, latest_commit_sha_or_None). None
    status means the request itself failed or was blocked (this sandbox's
    own outbound network policy, same block already documented for the
    real pull path), treated as unknown, never as a change, so a blocked
    network can only cause a missed priority trigger (the 24h baseline
    still catches it), never a false pull. A 200 with no commit in the
    body is also reported as unknown."""
    try:
        resp = requests.get(
            f"{github_status_pull.API_BASE}/repos/{owner_repo}/commits",
            params={"per_page": 1},
            headers=github_status_pull._headers(), timeout=10,
        )
    except requests.exceptions.RequestException as e:
        print(f"  ! Change-check for {owner_repo} failed "
              f"({e.__class__.__name__}), treating as unknown, not as a change.",
              file=sys.stderr)
        return None, None
    if resp.status_code != 200:
        return resp.status_code, None
    try:
        body = resp.json()
        return 200, body[0]["sha"]
    except (ValueError, IndexError, KeyError, TypeError):
        return None, None


def check_repo_changed(owner_repo, cache, get_fn=None):
    """Returns True (the newest commit on the default branch differs from
    the one saved last tick), False (same commit, or a first observation
    with nothing to compare against), or None (unknown: request failed or
    returned no usable commit). `get_fn(owner_repo) -> (status, sha)` is
    injectable so tests never touch the network.

    First-observation rule: with no saved SHA there is nothing to compare
    to, so the first check of a repo only RECORDS the SHA and returns
    False; a change can only be reported against a prior SHA. The saved
    SHA is updated on every successful check, so each change is reported
    once."""
    if get_fn is None:
        get_fn = _fetch_latest_sha
    cache_key = f"sha:{owner_repo}"
    prior_sha = cache.get(cache_key)
    status, sha = get_fn(owner_repo)
    if status != 200 or not sha:
        return None
    cache[cache_key] = sha
    if prior_sha is None:
        return False
    return sha != prior_sha


def decide(now=None, log_path=None, repos=None, etag_cache_path=None, change_check_fn=None):
    """The scheduling decision itself, pure enough to unit-test: given a
    point in time and the run history on disk, returns
    (should_pull: bool, reason: str, detail: dict). See the module
    docstring for what each reason string means and why the cap always
    wins. `repos=None` deliberately skips the priority-trigger check
    entirely rather than silently treating "no repos passed" as "no
    changes" — a caller that wants the change check has to ask for it."""
    if now is None:
        now = datetime.now(timezone.utc)

    run_starts = _load_run_started_times(log_path)
    window_start = now - timedelta(hours=ROLLING_WINDOW_HOURS)
    pulls_in_window = [t for t in run_starts if t >= window_start]

    detail = {
        "checked_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pulls_in_last_24h": len(pulls_in_window),
        "cap": MAX_PULLS_PER_WINDOW,
    }

    if len(pulls_in_window) >= MAX_PULLS_PER_WINDOW:
        detail["reason_detail"] = (
            f"{len(pulls_in_window)} pulls already in the trailing "
            f"{ROLLING_WINDOW_HOURS}h window, at the cap of {MAX_PULLS_PER_WINDOW}. "
            f"This wins over baseline and priority both."
        )
        return False, "cap_reached", detail

    last_pull = run_starts[-1] if run_starts else None
    detail["last_pull_at"] = last_pull.strftime("%Y-%m-%dT%H:%M:%SZ") if last_pull else None

    if last_pull is None or (now - last_pull) >= timedelta(hours=BASELINE_INTERVAL_HOURS):
        detail["reason_detail"] = (
            "no prior pull on record" if last_pull is None else
            f"{(now - last_pull).total_seconds() / 3600:.1f}h since the last pull, "
            f">= the {BASELINE_INTERVAL_HOURS}h baseline."
        )
        return True, "baseline_due", detail

    hours_since = (now - last_pull).total_seconds() / 3600

    if repos:
        cache_path = etag_cache_path or ETAG_CACHE_PATH
        cache = _load_etag_cache(cache_path)
        check_fn = change_check_fn or check_repo_changed
        changed_repos, unknown_repos = [], []
        for r in repos:
            result = check_fn(r, cache)
            if result is True:
                changed_repos.append(r)
            elif result is None:
                unknown_repos.append(r)
        _save_etag_cache(cache, cache_path)
        detail["changed_repos"] = changed_repos
        detail["unknown_repos"] = unknown_repos

        if changed_repos:
            detail["reason_detail"] = (
                f"only {hours_since:.1f}h since the last pull (< {BASELINE_INTERVAL_HOURS}h "
                f"baseline), but a change was detected on {len(changed_repos)} tracked "
                f"repo(s) ({', '.join(changed_repos)}) and the cap allows one more pull."
            )
            return True, "priority_change_detected", detail

    detail["reason_detail"] = (
        f"only {hours_since:.1f}h since the last pull (< {BASELINE_INTERVAL_HOURS}h baseline) "
        f"and no change detected (or no repos were given to check)."
    )
    return False, "not_due", detail


def main():
    should_pull, reason, detail = decide(repos=github_status_pull.TRACKED_REPOS)
    detail["trigger"] = _trigger()

    run_id = pulse_log.new_run_id()
    pulse_log.log_event(run_id, "scheduler_decision", should_pull=should_pull, reason=reason, **detail)

    try:
        with open(DECISION_PATH, "w") as f:
            json.dump({"should_pull": should_pull, "reason": reason, **detail}, f, indent=2)
    except OSError as e:
        print(f"  ! Could not write {DECISION_PATH} ({e.__class__.__name__}: {e}), "
              f"continuing — this only affects the CI step that reads it, not the decision itself.",
              file=sys.stderr)

    print(f"pulse_scheduler: should_pull={should_pull} reason={reason}")
    for k, v in detail.items():
        print(f"  {k}: {v}")

    if not should_pull:
        print("Not due this tick — skipping the real pull. See reason above.")
        return

    print("Due — running the real pull now.")
    github_status_pull.main()


if __name__ == "__main__":
    main()
