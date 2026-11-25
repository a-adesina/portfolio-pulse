"""
Portfolio Pulse — Structured Logging
=======================================
Closes a named gap from GAP_ANALYSIS.md §3.4 ("No structured logging...
stderr text only"). Scoped narrowly on purpose, the same discipline
GAP_ANALYSIS.md §6 applies to every other remediation item: this gives
every pull run a structured, appendable, machine-queryable record of
what happened, per repo and for the run as a whole. It does NOT add
metrics, alerting, or distributed tracing — those remain named, open
gaps in GAP_ANALYSIS.md, not silently closed by implication because a
log file now exists.

Why JSON-lines, not a logging framework or a database: one JSON object
per line is queryable with grep/jq/pandas without adding a dependency
this project doesn't otherwise need, and it matches the project's
existing pattern of disk-based, inspectable evidence
(pull_results.json, TEST_REPORT.md, MCP_VERIFICATION_LOG.md) over
anything that needs a running service to read back.

Each line: {"ts": ISO8601 UTC, "run_id": <12-hex>, "event": <str>,
"repo": <str or null>, ...detail}. Appended, never overwritten or
rotated — rotation/retention is a real, separate concern, named here
rather than quietly assumed solved.
"""

import json
import os
import sys
import uuid
from datetime import datetime, timezone

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pulse_run_log.jsonl")


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


def log_event(run_id: str, event: str, repo: str | None = None, log_path: str | None = None, **detail):
    """Append one structured line. Deliberately never raises: a logging
    failure (disk full, permissions) must not abort or corrupt the
    actual pull it's describing — observability is lower-severity than
    correctness, so a write failure here is reported to stderr and
    swallowed, not propagated.

    `log_path` defaults to the MODULE-LEVEL `LOG_PATH` read at CALL time
    (`globals()["LOG_PATH"]`, not a bound default argument) specifically
    so that redirecting `pulse_log.LOG_PATH` for test isolation (see
    tests/test_github_pull.py's setUpModule) actually takes effect. A
    plain `log_path: str = LOG_PATH` default binds the value once, at
    import time, and silently ignores any later reassignment — a real
    bug that would have made the test-isolation monkeypatch a no-op."""
    if log_path is None:
        log_path = LOG_PATH
    entry = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_id": run_id,
        "event": event,
        "repo": repo,
    }
    entry.update(detail)
    try:
        with open(log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError as e:
        print(f"  ! Could not write structured log entry ({e.__class__.__name__}: {e}), "
              f"continuing without it, logging failure must never block a pull.", file=sys.stderr)
