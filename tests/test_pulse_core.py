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


def _rows(*specs, include_budget=False):
    gh = {}
    for kw in specs:
        gh.update(gh_row(**kw))
    return pulse_core.build_rows(gh, {}, include_budget=include_budget)


class BudgetOptionalTests(unittest.TestCase):
    """With include_budget=False, spend must play no part at all."""

    def test_budget_data_is_ignored_when_not_included(self):
        rows = pulse_core.build_rows(gh_row(), budget_row(planned=100, spent=9999), include_budget=False)
        self.assertEqual(rows[0]["budget_flag"], "NOT TRACKED")
        self.assertEqual(rows[0]["risk_tier"], "clear")

    def test_over_budget_does_not_make_a_project_critical_when_not_included(self):
        with_budget = pulse_core.build_rows(gh_row(), budget_row(planned=100, spent=9999))
        without = pulse_core.build_rows(gh_row(), budget_row(planned=100, spent=9999), include_budget=False)
        self.assertEqual(with_budget[0]["risk_tier"], "critical")
        self.assertEqual(without[0]["risk_tier"], "clear")

    def test_a_repo_only_in_the_budget_file_does_not_appear(self):
        rows = pulse_core.build_rows({}, budget_row(), include_budget=False)
        self.assertEqual(rows, [])

    def test_position_text_never_mentions_spend_or_budget(self):
        rows = _rows(dict(), dict(repo="b/b", ci_status="failure"))
        for r in rows:
            self.assertNotIn("pend", r["interpretation"])
            self.assertNotIn("udget", r["interpretation"])
        self.assertNotIn("pend", pulse_core.interpret_portfolio(rows))

    def test_default_behaviour_is_unchanged_with_budget(self):
        rows = pulse_core.build_rows(gh_row(), budget_row(planned=10000, spent=5000))
        self.assertEqual(rows[0]["budget_flag"], "on track")
        self.assertIn("Spend is on track", rows[0]["interpretation"])

    def test_load_and_merge_without_a_budget_path_tracks_no_budget(self):
        import json, tempfile
        d = tempfile.mkdtemp()
        path = os.path.join(d, "pull.json")
        rec = gh_row()["test/repo"]
        rec["repo"] = "test/repo"
        with open(path, "w") as f:
            json.dump([rec], f)
        rows = pulse_core.load_and_merge(path)
        self.assertEqual(rows[0]["budget_flag"], "NOT TRACKED")


class DeriveDecisionsTests(unittest.TestCase):
    def _titles(self, items):
        return [i["title"] for i in items]

    def test_failing_build_is_critical_and_cites_its_evidence(self):
        items = pulse_core.derive_decisions(_rows(dict(repo="a/a", ci_status="failure", days_since_commit=8, prs_merged=16)))
        self.assertEqual(items[0]["severity"], "critical")
        self.assertIn("a/a", items[0]["title"])
        self.assertIn("8 days", " ".join(items[0]["evidence"]))
        self.assertIn("16 PRs", " ".join(items[0]["evidence"]))
        self.assertIsNotNone(items[0]["caveat"])

    def test_critical_items_come_before_watch_and_clear(self):
        items = pulse_core.derive_decisions(_rows(
            dict(repo="ok/ok"),
            dict(repo="old/old", stale=True, days_since_commit=40),
            dict(repo="red/red", ci_status="failure"),
        ))
        self.assertEqual([i["severity"] for i in items], ["critical", "watch", "clear"])

    def test_stale_under_a_year_is_a_check_on_it_question(self):
        items = pulse_core.derive_decisions(_rows(dict(repo="q/q", stale=True, days_since_commit=40)))
        self.assertIn("gone quiet", items[0]["title"])

    def test_stale_over_a_year_is_an_archive_question(self):
        items = pulse_core.derive_decisions(_rows(dict(repo="o/o", stale=True, days_since_commit=500)))
        self.assertIn("over a year", items[0]["title"])
        self.assertIn("archive", items[0]["decision"])

    def test_year_boundary_is_exclusive(self):
        at = pulse_core.derive_decisions(_rows(dict(repo="o/o", stale=True, days_since_commit=pulse_core.STALE_ARCHIVE_CANDIDATE_DAYS)))
        over = pulse_core.derive_decisions(_rows(dict(repo="o/o", stale=True, days_since_commit=pulse_core.STALE_ARCHIVE_CANDIDATE_DAYS + 1)))
        self.assertIn("gone quiet", at[0]["title"])
        self.assertIn("over a year", over[0]["title"])

    def test_open_work_with_no_merges_needs_both_conditions(self):
        n = pulse_core.BACKLOG_NO_THROUGHPUT_OPEN_ISSUES
        both = pulse_core.derive_decisions(_rows(dict(repo="b/b", open_issues=n, prs_merged=0)))
        many_but_merging = pulse_core.derive_decisions(_rows(dict(repo="b/b", open_issues=n, prs_merged=2)))
        few_no_merges = pulse_core.derive_decisions(_rows(dict(repo="b/b", open_issues=n - 1, prs_merged=0)))
        self.assertTrue(any("no merges" in t for t in self._titles(both)))
        self.assertFalse(any("no merges" in t for t in self._titles(many_but_merging)))
        self.assertFalse(any("no merges" in t for t in self._titles(few_no_merges)))

    def test_a_project_is_not_listed_twice_for_backlog(self):
        items = pulse_core.derive_decisions(_rows(
            dict(repo="b/b", open_issues=50, prs_merged=0, tickets_opened=40, tickets_closed=1)))
        backlog_items = [i for i in items if "growing" in i["title"] or "no merges" in i["title"]]
        self.assertEqual(len(backlog_items), 1)

    def test_growing_backlog_with_merges_is_its_own_item(self):
        items = pulse_core.derive_decisions(_rows(
            dict(repo="g/g", open_issues=10, prs_merged=5, tickets_opened=20, tickets_closed=2)))
        self.assertTrue(any("growing backlog" in t for t in self._titles(items)))

    def test_all_clear_gives_a_single_no_action_item(self):
        items = pulse_core.derive_decisions(_rows(dict(repo="a/a"), dict(repo="b/b")))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["severity"], "clear")
        self.assertEqual(items[0]["decision"], "None this cycle.")

    def test_unpulled_repo_is_a_data_gap_not_a_clean_bill(self):
        rows = pulse_core.build_rows({}, {"x/x": {"planned": 1, "spent": 1, "notes": ""}})
        items = pulse_core.derive_decisions(rows)
        self.assertEqual([i["severity"] for i in items], ["unknown"])
        self.assertIn("x/x", items[0]["evidence"][0])

    def test_wording_is_plain_english_for_one_and_many(self):
        one = pulse_core.derive_decisions(_rows(dict(repo="a/a", ci_status="failure", days_since_commit=1, prs_merged=1)))
        self.assertIn("1 day since", " ".join(one[0]["evidence"]))
        self.assertIn("1 PR merged", " ".join(one[0]["evidence"]))
        many = pulse_core.derive_decisions(_rows(dict(repo="a/a", stale=True, days_since_commit=40),
                                                 dict(repo="b/b", stale=True, days_since_commit=50)))
        self.assertTrue(many[0]["title"].startswith("2 projects"))
        single = pulse_core.derive_decisions(_rows(dict(repo="a/a", stale=True, days_since_commit=40)))
        self.assertTrue(single[0]["title"].startswith("1 project "))

    def test_no_machine_style_plurals_anywhere_in_the_output(self):
        rows = _rows(dict(repo="a/a", ci_status="failure"), dict(repo="b/b", stale=True, days_since_commit=500),
                     dict(repo="c/c", open_issues=40, prs_merged=0), dict(repo="d/d"))
        text = " ".join(str(v) for i in pulse_core.derive_decisions(rows) for v in i.values())
        text += pulse_core.interpret_portfolio(rows) + " ".join(r["interpretation"] for r in rows)
        self.assertNotIn("(s)", text)

    def test_empty_portfolio_gives_no_decisions(self):
        self.assertEqual(pulse_core.derive_decisions([]), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
