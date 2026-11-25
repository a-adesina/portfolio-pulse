"""
Tests — pulse_scheduler.py
==============================
Deterministic tests over hand-built timestamps and a stubbed change-check
function, same discipline as test_pulse_alert.py: reliably reproducing
"exactly 3 pulls landed in the last 24h" or "GitHub actually returned a
changed ETag" against anything real isn't practical, so the run history
and the network call are both built/mocked by hand here.

Run directly:
    python3 -m unittest tests.test_pulse_scheduler -v
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pulse_scheduler


def write_log(run_started_timestamps):
    """One run_started line per timestamp given (ISO8601 Z strings)."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    for i, ts in enumerate(run_started_timestamps):
        f.write(json.dumps({
            "ts": ts, "run_id": f"r{i}", "event": "run_started", "repo": None,
            "tracked_repo_count": 5,
        }) + "\n")
    f.close()
    return f.name


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


class DecideTests(unittest.TestCase):

    def setUp(self):
        self._log_path = None
        self._etag_path = None

    def tearDown(self):
        for p in (self._log_path, self._etag_path):
            if p and os.path.exists(p):
                os.remove(p)

    def _decide(self, timestamps, **kwargs):
        self._log_path = write_log([iso(t) for t in timestamps])
        self._etag_path = tempfile.NamedTemporaryFile(suffix=".json", delete=False).name
        os.remove(self._etag_path)  # start with no cache file, like a fresh checkout
        return pulse_scheduler.decide(
            now=NOW, log_path=self._log_path, etag_cache_path=self._etag_path, **kwargs
        )

    def test_no_history_is_baseline_due(self):
        should_pull, reason, detail = self._decide([])
        self.assertTrue(should_pull)
        self.assertEqual(reason, "baseline_due")
        self.assertIsNone(detail["last_pull_at"])

    def test_last_pull_over_24h_ago_is_baseline_due(self):
        should_pull, reason, detail = self._decide([NOW - timedelta(hours=25)])
        self.assertTrue(should_pull)
        self.assertEqual(reason, "baseline_due")

    def test_last_pull_exactly_at_boundary_is_baseline_due(self):
        should_pull, reason, _ = self._decide([NOW - timedelta(hours=24)])
        self.assertTrue(should_pull)
        self.assertEqual(reason, "baseline_due")

    def test_recent_pull_no_repos_checked_is_not_due(self):
        should_pull, reason, _ = self._decide([NOW - timedelta(hours=2)])
        self.assertFalse(should_pull)
        self.assertEqual(reason, "not_due")

    def test_recent_pull_no_change_detected_is_not_due(self):
        should_pull, reason, detail = self._decide(
            [NOW - timedelta(hours=2)],
            repos=["a/b", "c/d"],
            change_check_fn=lambda repo, cache: False,
        )
        self.assertFalse(should_pull)
        self.assertEqual(reason, "not_due")

    def test_recent_pull_with_change_is_priority_trigger(self):
        should_pull, reason, detail = self._decide(
            [NOW - timedelta(hours=2)],
            repos=["a/b", "c/d"],
            change_check_fn=lambda repo, cache: repo == "a/b",
        )
        self.assertTrue(should_pull)
        self.assertEqual(reason, "priority_change_detected")
        self.assertEqual(detail["changed_repos"], ["a/b"])
        self.assertEqual(detail["unknown_repos"], [])

    def test_unknown_change_result_never_triggers_a_pull(self):
        # A blocked/failed conditional check must never be mistaken for a
        # change — it can only ever fall back to the 24h baseline.
        should_pull, reason, detail = self._decide(
            [NOW - timedelta(hours=2)],
            repos=["a/b", "c/d"],
            change_check_fn=lambda repo, cache: None,
        )
        self.assertFalse(should_pull)
        self.assertEqual(reason, "not_due")
        self.assertEqual(sorted(detail["unknown_repos"]), ["a/b", "c/d"])

    def test_cap_reached_blocks_baseline_and_priority_both(self):
        # 3 pulls inside the trailing 24h window (even though the most
        # recent is still recent, well under the baseline on its own) —
        # the cap must win even against a confirmed detected change.
        timestamps = [NOW - timedelta(hours=20), NOW - timedelta(hours=10), NOW - timedelta(hours=1)]
        should_pull, reason, detail = self._decide(
            timestamps,
            repos=["a/b"],
            change_check_fn=lambda repo, cache: True,  # would otherwise trigger
        )
        self.assertFalse(should_pull)
        self.assertEqual(reason, "cap_reached")
        self.assertEqual(detail["pulls_in_last_24h"], 3)

    def test_cap_counts_only_the_trailing_window_not_all_history(self):
        # One pull 30h ago (outside the 24h window) plus two inside it —
        # only the two inside count toward the cap, so one more is allowed.
        timestamps = [NOW - timedelta(hours=30), NOW - timedelta(hours=10), NOW - timedelta(hours=1)]
        should_pull, reason, detail = self._decide(timestamps)
        self.assertEqual(detail["pulls_in_last_24h"], 2)
        self.assertFalse(should_pull)  # most recent pull was 1h ago, baseline not due, no repos checked
        self.assertEqual(reason, "not_due")

    def test_failed_pulls_still_count_toward_the_cap(self):
        # run_started is logged unconditionally, whether or not the pull
        # went on to succeed — a failed attempt still spent quota.
        timestamps = [NOW - timedelta(hours=20), NOW - timedelta(hours=10), NOW - timedelta(hours=1)]
        _, reason, detail = self._decide(timestamps)
        self.assertEqual(reason, "cap_reached")


class LoadRunStartedTimesTests(unittest.TestCase):

    def test_ignores_non_run_started_events(self):
        path = write_log([])
        with open(path, "a") as f:
            f.write(json.dumps({"ts": iso(NOW), "run_id": "r1", "event": "run_finished", "repo": None}) + "\n")
        try:
            self.assertEqual(pulse_scheduler._load_run_started_times(path), [])
        finally:
            os.remove(path)

    def test_skips_malformed_lines(self):
        path = write_log([iso(NOW)])
        with open(path, "a") as f:
            f.write("not valid json\n")
        try:
            times = pulse_scheduler._load_run_started_times(path)
            self.assertEqual(len(times), 1)
        finally:
            os.remove(path)

    def test_missing_log_file_is_empty_not_fatal(self):
        self.assertEqual(pulse_scheduler._load_run_started_times("/nonexistent/path.jsonl"), [])

    def test_results_are_sorted(self):
        path = write_log([iso(NOW), iso(NOW - timedelta(hours=5)), iso(NOW - timedelta(hours=1))])
        try:
            times = pulse_scheduler._load_run_started_times(path)
            self.assertEqual(times, sorted(times))
        finally:
            os.remove(path)


class CheckRepoChangedTests(unittest.TestCase):
    """The ETag interpretation logic, with the network call itself stubbed."""

    def test_304_is_not_changed(self):
        result = pulse_scheduler.check_repo_changed("a/b", {}, get_fn=lambda repo, etag: (304, None))
        self.assertFalse(result)

    def test_200_is_changed_and_updates_cache(self):
        cache = {}
        result = pulse_scheduler.check_repo_changed("a/b", cache, get_fn=lambda repo, etag: (200, "abc123"))
        self.assertTrue(result)
        self.assertEqual(cache["a/b"], "abc123")

    def test_failed_request_is_unknown_not_changed(self):
        result = pulse_scheduler.check_repo_changed("a/b", {}, get_fn=lambda repo, etag: (None, None))
        self.assertIsNone(result)

    def test_unexpected_status_is_unknown_not_changed(self):
        result = pulse_scheduler.check_repo_changed("a/b", {}, get_fn=lambda repo, etag: (500, None))
        self.assertIsNone(result)

    def test_prior_etag_is_passed_through_to_get_fn(self):
        cache = {"a/b": "prior-etag"}
        seen = {}

        def fake_get(repo, etag):
            seen["etag"] = etag
            return 304, None

        pulse_scheduler.check_repo_changed("a/b", cache, get_fn=fake_get)
        self.assertEqual(seen["etag"], "prior-etag")


if __name__ == "__main__":
    unittest.main()
