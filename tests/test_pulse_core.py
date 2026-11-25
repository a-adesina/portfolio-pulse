"""
Tests — pulse_core.py
========================
Pure logic, no network dependency, so these run identically every time
regardless of GitHub's rate limit. Deliberately targets boundary
conditions and priority ordering, not just the happy path, the same
"where does this actually break" discipline as the rest of this build.

Run directly:
    python3 -m unittest tests.test_pulse_core -v
Or via the aggregate runner:
    python3 run_tests.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pulse_core


def gh_row(repo="test/repo", days_since_commit=5, stale=False, ci_status="success",
           open_issues=10, tickets_opened=2, tickets_closed=2, prs_merged=3,
           default_branch="main"):
    """A minimal, valid github_status_pull.py-shaped record for one repo."""
    return {
        repo: {
            "default_branch": default_branch,
            "days_since_last_commit": days_since_commit,
            "stale": stale,
            "ci_status": ci_status,
            "open_issues": open_issues,
            "tickets_opened_recent": tickets_opened,
            "tickets_closed_recent": tickets_closed,
            "prs_merged_last_30d": prs_merged,
        }
    }


def budget_row(repo="test/repo", planned=10000.0, spent=5000.0):
    return {repo: {"planned": planned, "spent": spent, "notes": "test"}}


class BudgetBoundaryTests(unittest.TestCase):
    """The exact edges of BUDGET_NEAR_LIMIT_PCT and the OVER/on-track line."""

    def test_exactly_at_near_limit_threshold(self):
        # 90.0% exactly should trip "near limit" (>=, not >)
        rows = pulse_core.build_rows(gh_row(), budget_row(planned=10000, spent=9000))
        self.assertEqual(rows[0]["budget_flag"], "near limit")

    def test_just_under_near_limit_threshold(self):
        rows = pulse_core.build_rows(gh_row(), budget_row(planned=10000, spent=8999))
        self.assertEqual(rows[0]["budget_flag"], "on track")

    def test_exactly_100_percent_is_on_track_not_over(self):
        # variance == 0 at exactly 100% spent; OVER requires variance > 0
        # strictly, so spending exactly the plan is "near limit", not OVER.
        rows = pulse_core.build_rows(gh_row(), budget_row(planned=10000, spent=10000))
        self.assertEqual(rows[0]["budget_flag"], "near limit")
        self.assertEqual(rows[0]["variance"], 0)

    def test_one_dollar_over_is_over(self):
        rows = pulse_core.build_rows(gh_row(), budget_row(planned=10000, spent=10000.01))
        self.assertEqual(rows[0]["budget_flag"], "OVER")

    def test_planned_zero_does_not_crash(self):
        # Real division-by-zero risk if unguarded. Must not raise, and the
        # percentage-based "near limit" branch must not fire on a zero base.
        rows = pulse_core.build_rows(gh_row(), budget_row(planned=0, spent=500))
        self.assertEqual(rows[0]["budget_flag"], "OVER")  # variance (500) > 0 still fires
        rows_zero_spend = pulse_core.build_rows(gh_row(), budget_row(planned=0, spent=0))
        self.assertEqual(rows_zero_spend[0]["budget_flag"], "on track")


class MissingDataTests(unittest.TestCase):
    """A project present in one source but not the other, a real, common
    state (budget tracked before the repo is wired up, or vice versa)."""

    def test_missing_github_data(self):
        rows = pulse_core.build_rows({}, budget_row())
        self.assertEqual(rows[0]["delivery_flag"], "NO DATA (not pulled)")
        self.assertEqual(rows[0]["code_health"], "NO DATA")
        self.assertIsNone(rows[0]["days_since_commit"])

    def test_missing_budget_data(self):
        rows = pulse_core.build_rows(gh_row(), {})
        self.assertEqual(rows[0]["budget_flag"], "NO DATA")
        self.assertIsNone(rows[0]["variance"])

    def test_missing_both_sources_entirely(self):
        rows = pulse_core.build_rows({}, {})
        self.assertEqual(rows, [])

    def test_risk_tier_unknown_when_no_data_either_side(self):
        # One repo tracked in budget only, github pull never ran for it.
        rows = pulse_core.build_rows({}, budget_row())
        self.assertEqual(rows[0]["risk_tier"], "unknown")


class CodeHealthPriorityTests(unittest.TestCase):
    """_code_health_flag has a deliberate priority order. Each test proves
    one specific priority decision rather than just the common case."""

    def test_ci_failure_overrides_active_delivery(self):
        rows = pulse_core.build_rows(
            gh_row(stale=False, ci_status="failure"), budget_row()
        )
        self.assertEqual(rows[0]["code_health"], "BROKEN")

    def test_stale_overrides_no_ci_configured(self):
        # A stale AND unmonitored project should read as STALE, the more
        # urgent state, not "ACTIVE (unmonitored)", which would understate it.
        rows = pulse_core.build_rows(
            gh_row(stale=True, ci_status="no_ci_configured"), budget_row()
        )
        self.assertEqual(rows[0]["code_health"], "STALE")

    def test_ci_failure_overrides_stale_too(self):
        # Failure is checked first in the priority order; confirm that
        # holds even when the project is ALSO stale.
        rows = pulse_core.build_rows(
            gh_row(stale=True, ci_status="failure"), budget_row()
        )
        self.assertEqual(rows[0]["code_health"], "BROKEN")

    def test_no_ci_configured_on_active_project(self):
        rows = pulse_core.build_rows(
            gh_row(stale=False, ci_status="no_ci_configured"), budget_row()
        )
        self.assertEqual(rows[0]["code_health"], "ACTIVE (unmonitored)")


class RiskTierAndInterpretationTests(unittest.TestCase):
    """The worst-of risk tier, and whether the written interpretation picks
    the right reason when multiple critical conditions are true at once."""

    def test_ci_failure_and_budget_over_simultaneously(self):
        rows = pulse_core.build_rows(
            gh_row(ci_status="failure"), budget_row(planned=1000, spent=2000)
        )
        self.assertEqual(rows[0]["risk_tier"], "critical")
        # code_health is checked before budget_flag in the verdict clause;
        # confirm the interpretation actually says so, not the other reason.
        self.assertIn("a failing build", rows[0]["interpretation"])
        self.assertNotIn("spend over plan", rows[0]["interpretation"])

    def test_budget_over_alone_gives_correct_reason(self):
        rows = pulse_core.build_rows(
            gh_row(ci_status="success"), budget_row(planned=1000, spent=2000)
        )
        self.assertEqual(rows[0]["risk_tier"], "critical")
        self.assertIn("spend over plan", rows[0]["interpretation"])

    def test_ticket_net_exactly_at_watch_threshold(self):
        rows = pulse_core.build_rows(
            gh_row(tickets_opened=10, tickets_closed=5), budget_row()  # net = 5
        )
        self.assertEqual(rows[0]["ticket_net"], 5)
        self.assertEqual(rows[0]["risk_tier"], "watch")

    def test_ticket_net_just_under_watch_threshold(self):
        rows = pulse_core.build_rows(
            gh_row(tickets_opened=9, tickets_closed=5), budget_row()  # net = 4
        )
        self.assertEqual(rows[0]["ticket_net"], 4)
        self.assertEqual(rows[0]["risk_tier"], "clear")

    def test_negative_ticket_net_reads_as_shrinking(self):
        rows = pulse_core.build_rows(
            gh_row(tickets_opened=2, tickets_closed=8), budget_row()
        )
        self.assertEqual(rows[0]["ticket_net"], -6)
        self.assertIn("shrank", rows[0]["interpretation"])


class PortfolioInterpretationTests(unittest.TestCase):

    def test_empty_portfolio_does_not_crash(self):
        summary = pulse_core.interpret_portfolio([])
        self.assertIn("0 tracked projects", summary)

    def test_all_clear_portfolio_says_no_action(self):
        rows = pulse_core.build_rows(gh_row(), budget_row())
        summary = pulse_core.interpret_portfolio(rows)
        self.assertIn("No projects currently require attention", summary)


if __name__ == "__main__":
    unittest.main(verbosity=2)
