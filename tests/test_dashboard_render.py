"""
Tests — generate_dashboard.py
===============================
Renders from in-memory rows and a synthetic log, then checks the HTML for
the things that would embarrass the page in front of a reader: stale claims,
invented spend, unescaped text, machine-style plurals.
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import generate_dashboard
import pulse_core
import pulse_health

NOW = datetime(2026, 11, 27, 12, 0, 0, tzinfo=timezone.utc)


def _gh(repo, **kw):
    base = dict(repo=repo, default_branch="main", last_commit_date="2026-11-20T00:00:00Z",
                days_since_last_commit=5, stale=False, ci_status="success", open_issues=3,
                tickets_opened_recent=2, tickets_closed_recent=2, prs_merged_last_30d=4)
    base.update(kw)
    return base


def _render(gh_records, events=None, annotations=None, note="Demo scope note."):
    rows = pulse_core.build_rows({r["repo"]: r for r in gh_records}, {}, include_budget=False)
    health = pulse_health.summarize(events or [], NOW, annotations or {})
    return generate_dashboard.render_dashboard(
        rows, pulse_core.interpret_portfolio(rows), pulse_core.derive_decisions(rows),
        health, "2026-11-27 12:00", note)


class RenderTests(unittest.TestCase):
    def test_no_spend_or_budget_anywhere_on_the_page(self):
        out = _render([_gh("a/a"), _gh("b/b", ci_status="failure")])
        self.assertNotIn("$", out)
        self.assertNotIn("Spend", out)
        self.assertNotIn("Budget", out)

    def test_no_stale_fixture_claim(self):
        out = _render([_gh("a/a")])
        self.assertNotIn("test fixture", out)
        self.assertNotIn("not a full live pull", out)

    def test_scope_note_is_shown(self):
        self.assertIn("Demo scope note.", _render([_gh("a/a")]))

    def test_table_has_the_six_expected_columns(self):
        out = _render([_gh("a/a")])
        for col in ("Project", "Code health", "Last commit", "Open issues", "Tickets, 30d", "PRs merged, 30d"):
            self.assertIn(f">{col}<", out)

    def test_ticket_flow_is_shown_per_repo(self):
        out = _render([_gh("a/a", tickets_opened_recent=14, tickets_closed_recent=1)])
        self.assertIn("14↑ / 1↓", out)

    def test_decisions_section_and_evidence_are_present(self):
        out = _render([_gh("a/a", ci_status="failure")])
        self.assertIn("Decisions this data supports", out)
        self.assertIn("Failing build on a/a", out)

    def test_no_machine_style_plurals(self):
        out = _render([_gh("a/a", ci_status="failure"), _gh("b/b", stale=True, days_since_last_commit=40)])
        self.assertNotIn("(s)", out)

    def test_run_record_shows_trigger_when_recorded_and_says_so_when_not(self):
        ev = [
            {"ts": "2026-11-27T06:00:00Z", "event": "scheduler_decision", "reason": "not_due", "should_pull": False, "trigger": "schedule"},
            {"ts": "2026-11-27T10:00:00Z", "event": "scheduler_decision", "reason": "not_due", "should_pull": False},
        ]
        out = _render([_gh("a/a")], ev)
        self.assertIn("scheduled", out)
        self.assertIn("trigger not recorded", out)

    def test_annotated_decision_is_flagged_and_its_note_shown(self):
        ev = [{"ts": "2026-11-26T07:26:47Z", "event": "scheduler_decision", "reason": "priority_change_detected", "should_pull": True}]
        out = _render([_gh("a/a")], ev, {"2026-11-26T07:26:47Z": "Explained in the incident log."})
        self.assertIn("chip-flag", out)
        self.assertIn("Explained in the incident log.", out)

    def test_unannotated_early_pull_is_not_flagged(self):
        ev = [{"ts": "2026-11-27T07:00:00Z", "event": "scheduler_decision", "reason": "priority_change_detected", "should_pull": True}]
        out = _render([_gh("a/a")], ev)
        self.assertNotIn('class="chip chip-flag"', out)

    def test_text_from_data_files_is_escaped(self):
        ev = [{"ts": "2026-11-26T07:26:47Z", "event": "scheduler_decision", "reason": "not_due", "should_pull": False}]
        out = _render([_gh("a/a")], ev, {"2026-11-26T07:26:47Z": "<script>alert(1)</script>"})
        self.assertNotIn("<script>alert(1)</script>", out)
        self.assertIn("&lt;script&gt;", out)

    def test_empty_log_renders_without_error(self):
        out = _render([_gh("a/a")], [])
        self.assertIn("No decisions on record.", out)

    def test_stale_threshold_shown_is_the_real_one(self):
        import github_status_pull
        out = _render([_gh("a/a")])
        self.assertIn(f"more than {github_status_pull.STALENESS_THRESHOLD_DAYS} days", out)

    def test_cadence_statement_matches_scheduler_constants(self):
        import pulse_scheduler
        out = _render([_gh("a/a")])
        self.assertIn(f"never more than {pulse_scheduler.MAX_PULLS_PER_WINDOW} in any rolling {pulse_scheduler.ROLLING_WINDOW_HOURS} hours", out)

    def test_main_runs_end_to_end_without_a_budget_file(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "pull_results.json"), "w") as f:
            json.dump([_gh("a/a")], f)
        with unittest.mock.patch.object(generate_dashboard, "__file__", os.path.join(d, "generate_dashboard.py")), \
             unittest.mock.patch.object(generate_dashboard.pulse_log, "LOG_PATH", os.path.join(d, "none.jsonl")):
            generate_dashboard.main()
        with open(os.path.join(d, "dashboard.html")) as f:
            self.assertIn("a/a", f.read())


import unittest.mock  # noqa: E402

if __name__ == "__main__":
    unittest.main()
