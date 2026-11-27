"""
Portfolio Pulse — Scheduler Health
====================================
Reads the structured run log (the same `pulse_run_log.jsonl` the scheduler
itself reads for its cap and baseline) and summarises it for display: when
the last pull ran and how it went, how many pulls sit in the rolling window
against the cap, when the next baseline pull falls due, and the recent
history of scheduler decisions.

Reading the same record the scheduler uses is deliberate. A dashboard panel
that kept its own numbers could disagree with the thing it describes.

Two things this does NOT do, on purpose:
  - It never infers that a decision was wrong. A decision is annotated only
    when a person has written a note for that exact timestamp in
    `decision_annotations.json`, citing where the explanation lives
    (INCIDENT_LOG.md). The panel shows the note next to the decision.
  - It does not guess the trigger for older entries. Decisions logged before
    the trigger field existed show "not recorded".

Nothing here touches the network or writes a file.
"""

import json
import os
from datetime import datetime, timedelta, timezone

import pulse_scheduler

REASON_LABEL = {
    "baseline_due": "baseline pull",
    "priority_change_detected": "early pull (change detected)",
    "not_due": "skipped",
    "cap_reached": "blocked by cap",
}

TRIGGER_LABEL = {
    "schedule": "scheduled",
    "workflow_dispatch": "manual",
    "push": "push",
    "local": "local run",
}


def _parse_ts(ts):
    return pulse_scheduler._parse_ts(ts)


def load_events(log_path):
    """All well-formed events, in file order. Malformed lines are skipped."""
    events = []
    if not log_path or not os.path.exists(log_path):
        return events
    with open(log_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(e, dict):
                events.append(e)
    return events


def load_annotations(path):
    """{timestamp: note}. A missing or unreadable file means no notes."""
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    notes = data.get("decisions", {}) if isinstance(data, dict) else {}
    return {k: v for k, v in notes.items() if isinstance(k, str) and isinstance(v, str)}


def summarize(events, now, annotations=None, history_limit=8):
    annotations = annotations or {}
    window = timedelta(hours=pulse_scheduler.ROLLING_WINDOW_HOURS)
    baseline = timedelta(hours=pulse_scheduler.BASELINE_INTERVAL_HOURS)

    starts = sorted(t for t in (_parse_ts(e.get("ts")) for e in events if e.get("event") == "run_started") if t)
    finishes = [e for e in events if e.get("event") == "run_finished"]
    decisions = [e for e in events if e.get("event") == "scheduler_decision"]

    last_start = starts[-1] if starts else None
    last_result = None
    if last_start is not None:
        for e in reversed(finishes):
            t = _parse_ts(e.get("ts"))
            if t is not None and t >= last_start:
                last_result = {"succeeded": e.get("succeeded"), "attempted": e.get("attempted")}
                break

    pulls_in_window = sum(1 for t in starts if t >= now - window)

    history = []
    for e in decisions[-history_limit:]:
        reason = e.get("reason")
        trigger = e.get("trigger")
        history.append({
            "ts": e.get("ts"),
            "reason": reason,
            "label": REASON_LABEL.get(reason, str(reason)),
            "pulled": bool(e.get("should_pull")),
            "trigger": TRIGGER_LABEL.get(trigger, trigger) if trigger else None,
            "note": annotations.get(e.get("ts")),
        })

    last_decision = history[-1] if history else None

    return {
        "last_pull_at": last_start,
        "last_pull_result": last_result,
        "pulls_in_window": pulls_in_window,
        "cap": pulse_scheduler.MAX_PULLS_PER_WINDOW,
        "window_hours": pulse_scheduler.ROLLING_WINDOW_HOURS,
        "next_baseline_due": (last_start + baseline) if last_start else None,
        "last_decision": last_decision,
        "history": history,
        "total_pulls_on_record": len(starts),
        "total_decisions_on_record": len(decisions),
    }
