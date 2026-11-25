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
writes `etag_cache.json` next to it. In a GitHub Actions scheduled run,
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

A second limitation, same honesty standard as METHODOLOGY.md's pushed_at
fix: the conditional check here hits the plain repo resource
(`GET /repos/{owner}/{repo}`), not the default-branch-scoped commit
endpoint `github_status_pull.py` uses for the real staleness number. That
makes it the SAME kind of imprecise signal `pushed_at` was (any branch
moving, or any repo metadata field changing, can flip the ETag) — but
unlike that earlier bug, the imprecision here is safe by construction:
this check is only ever allowed to CAUSE an extra pull inside the cap,
never to suppress a due pull or report a status itself. A false-positive
"changed" here costs one extra, correctly-capped pull; it can never
produce a wrong answer, which is the failure mode the pushed_at bug
actually had. Worth stating the difference explicitly rather than letting
the surface similarity read as the same mistake twice.

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


def _conditional_get(owner_repo, etag):
    """Returns (status_code_or_None, new_etag_or_None). None status means
    the request itself failed or was blocked (this sandbox's own outbound
    network policy, same block already documented for the real pull path)
    — treated as unknown, never as a change, so a blocked network can only
    ever cause a missed priority trigger (falls back to the 24h baseline
    still catching it), never a false pull."""
    headers = github_status_pull._headers()
    if etag:
        headers["If-None-Match"] = etag
    try:
        resp = requests.get(
            f"{github_status_pull.API_BASE}/repos/{owner_repo}",
            headers=headers, timeout=10,
        )
    except requests.exceptions.RequestException as e:
        print(f"  ! Conditional change-check for {owner_repo} failed "
              f"({e.__class__.__name__}), treating as unknown, not as a change.",
              file=sys.stderr)
        return None, None
    return resp.status_code, resp.headers.get("ETag")


def check_repo_changed(owner_repo, etag_cache, get_fn=None):
    """Returns True (changed), False (confirmed unchanged, a real 304), or
    None (unknown — request failed, or returned something other than
    200/304). `get_fn` is injectable so tests never touch the network."""
    if get_fn is None:
        get_fn = _conditional_get
    prior_etag = etag_cache.get(owner_repo)
    status, new_etag = get_fn(owner_repo, prior_etag)
    if status == 304:
        return False
    if status == 200:
        if new_etag:
            etag_cache[owner_repo] = new_etag
        return True
    return None


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
