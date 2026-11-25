"""
Portfolio Pulse — Alerting
=============================
Closes the remaining half of GAP_ANALYSIS.md §3.4's "No metrics or
alerting" gap. `pulse_log.py` already produces structured, queryable
run/repo events; this reads those events and actually pages someone (or,
with no webhook configured, says plainly what it would have paged)
when a REAL condition is met — not on every run, and not on a condition
invented to make this file look busier than the actual risk warrants.

Three conditions, each named because it's the thing that would actually
matter to someone relying on this pipeline, not an arbitrary threshold:

1. **The latest run never finished.** A `run_started` event with no
   matching `run_finished` means the process crashed or was killed
   mid-run, not a a clean "zero projects pulled" outcome. Different
   failure mode, different message.
2. **The latest run finished with zero successes out of however many
   were attempted.** Total failure, not degraded, the condition this
   project's own build hit for real today (see MATURITY_ASSESSMENT.md),
   when this build environment's network policy blocked every repo.
3. **The last several finished runs were ALL degraded or failed.**
   One bad run can be a blip (GitHub's rate limit, a transient network
   issue). Several in a row, in sequence, is the pattern worth paging
   someone over — "repeated," not "a one-off."

Usage:
    python3 pulse_alert.py
    # Reads pulse_log.LOG_PATH. If PULSE_ALERT_WEBHOOK_URL is set, POSTs
    # a JSON payload there for each triggered condition. If not set,
    # prints what it would have sent, to stderr, and still exits 0 —
    # alerting's own failure must never fail the pipeline run it's
    # describing, the same severity ordering pulse_log.py uses.
"""

import json
import os
import sys
from collections import OrderedDict

import pulse_log

CONSECUTIVE_FAILURE_WINDOW = 3   # how many recent finished runs to look at
CONSECUTIVE_FAILURE_THRESHOLD = 2  # how many of those, in a row, trigger "repeated"
DEGRADED_SUCCESS_RATE_PCT = 50   # a finished run below this rate is "degraded"


def _load_events(log_path=None):
    if log_path is None:
        log_path = pulse_log.LOG_PATH
    if not os.path.exists(log_path):
        return []
    events = []
    with open(log_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                # A malformed line must not take down alerting entirely;
                # skip it and keep going, the same "one bad record
                # shouldn't abort the batch" discipline as everywhere
                # else in this project.
                continue
    return events


def _runs_in_order(events):
    """Group events by run_id, preserving first-seen order, so 'the last
    N runs' means something chronological, not a dict's arbitrary order."""
    runs = OrderedDict()
    for e in events:
        rid = e.get("run_id")
        runs.setdefault(rid, []).append(e)
    return runs


def check_alerts(log_path=None):
    """Returns a list of (severity, message) tuples, one per triggered
    condition. Empty list means healthy — nothing to alert on, and that
    is the expected, common case, not a surprise worth logging loudly."""
    events = _load_events(log_path)
    if not events:
        return []

    runs = _runs_in_order(events)
    run_ids = list(runs.keys())
    latest_run_id = run_ids[-1]
    latest_events = runs[latest_run_id]

    alerts = []

    latest_finished = next((e for e in latest_events if e["event"] == "run_finished"), None)

    if latest_finished is None:
        alerts.append((
            "critical",
            f"Run {latest_run_id} started but never reported run_finished — "
            f"the process likely crashed or was killed mid-run, not a clean "
            f"zero-result outcome.",
        ))
        return alerts  # nothing further to say about a run that didn't finish

    succeeded = latest_finished.get("succeeded", 0)
    attempted = latest_finished.get("attempted", 0)
    rate = (succeeded / attempted * 100) if attempted else 0

    if attempted and succeeded == 0:
        failed_repos = [e.get("repo") for e in latest_events if e["event"] == "repo_pull_failed"]
        reasons = sorted({e.get("reason") for e in latest_events if e["event"] == "repo_pull_failed"})
        alerts.append((
            "critical",
            f"Run {latest_run_id}: 0 of {attempted} repos pulled successfully. "
            f"Reasons seen: {', '.join(r for r in reasons if r) or 'unknown'}. "
            f"Affected: {', '.join(r for r in failed_repos if r) or 'unknown'}.",
        ))
    elif attempted and rate < DEGRADED_SUCCESS_RATE_PCT:
        alerts.append((
            "warning",
            f"Run {latest_run_id}: only {succeeded}/{attempted} repos pulled "
            f"successfully ({rate:.0f}%), below the {DEGRADED_SUCCESS_RATE_PCT}% "
            f"degraded-run threshold.",
        ))

    # Consecutive-failure check, across the last CONSECUTIVE_FAILURE_WINDOW
    # finished runs, oldest-to-newest within that window.
    finished_runs = [
        (rid, next(e for e in evs if e["event"] == "run_finished"))
        for rid, evs in runs.items()
        if any(e["event"] == "run_finished" for e in evs)
    ]
    recent = finished_runs[-CONSECUTIVE_FAILURE_WINDOW:]
    failed_count = sum(1 for _, fin in recent if fin.get("attempted") and fin.get("succeeded") == 0)
    if len(recent) >= CONSECUTIVE_FAILURE_THRESHOLD and failed_count >= CONSECUTIVE_FAILURE_THRESHOLD:
        # Only add this if it's not just restating the single-run alert
        # above under a different name, i.e. there's more than one failed
        # run in the window, not one run counted twice.
        if failed_count > 1:
            alerts.append((
                "critical",
                f"{failed_count} of the last {len(recent)} finished runs had zero "
                f"successes — a repeated pattern, not a one-off blip.",
            ))

    return alerts


def send_alert(severity, message, webhook_url=None):
    """Posts to a webhook if one is configured; otherwise prints plainly
    to stderr what WOULD have been sent, and never raises either way —
    an alerting failure must not be mistaken for, or cause, a pipeline
    failure."""
    if webhook_url is None:
        webhook_url = os.environ.get("PULSE_ALERT_WEBHOOK_URL")

    payload = {"severity": severity, "source": "portfolio-pulse", "message": message}

    if not webhook_url:
        print(f"  [no webhook configured; would have sent {severity.upper()} alert] {message}",
              file=sys.stderr)
        return False

    try:
        import requests
        resp = requests.post(webhook_url, json=payload, timeout=10)
        if resp.status_code >= 400:
            print(f"  ! Alert webhook returned {resp.status_code}, alert NOT confirmed delivered: {message}",
                  file=sys.stderr)
            return False
        return True
    except Exception as e:
        # Same rule as everywhere else: a failure in the observability
        # path must never raise into, or be confused with, the pipeline
        # it's describing.
        print(f"  ! Could not deliver alert ({e.__class__.__name__}: {e}), not sent: {message}",
              file=sys.stderr)
        return False


def main():
    alerts = check_alerts()
    if not alerts:
        print("pulse_alert: no alert conditions met, pipeline healthy by these checks.")
        return
    for severity, message in alerts:
        print(f"[{severity.upper()}] {message}")
        send_alert(severity, message)


if __name__ == "__main__":
    main()
