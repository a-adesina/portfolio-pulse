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
from unittest import mock
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
    """The commit-SHA comparison, with the network call itself stubbed."""

    @staticmethod
    def _get(status, sha):
        return lambda repo: (status, sha)

    def test_same_sha_as_last_tick_is_not_changed(self):
        cache = {"sha:a/b": "abc123"}
        self.assertFalse(pulse_scheduler.check_repo_changed("a/b", cache, get_fn=self._get(200, "abc123")))
        self.assertEqual(cache["sha:a/b"], "abc123")

    def test_different_sha_is_changed_and_updates_cache(self):
        cache = {"sha:a/b": "old-sha"}
        self.assertTrue(pulse_scheduler.check_repo_changed("a/b", cache, get_fn=self._get(200, "new-sha")))
        self.assertEqual(cache["sha:a/b"], "new-sha")

    def test_first_observation_records_sha_and_is_not_a_change(self):
        cache = {}
        self.assertFalse(pulse_scheduler.check_repo_changed("a/b", cache, get_fn=self._get(200, "abc123")))
        self.assertEqual(cache["sha:a/b"], "abc123")

    def test_change_is_reported_once_then_quiet(self):
        cache = {}
        results = [pulse_scheduler.check_repo_changed("a/b", cache, get_fn=self._get(200, sha))
                   for sha in ("v1", "v2", "v2")]
        self.assertEqual(results, [False, True, False])

    def test_values_saved_under_earlier_schemes_are_ignored(self):
        # Bare repo-name keys (repo-record ETags) and `commits:` keys
        # (commit-list ETags) must never be compared against a SHA; a repo
        # with only those entries counts as a first observation.
        cache = {"a/b": "W/\"legacy\"", "commits:a/b": "W/\"etag\""}
        self.assertFalse(pulse_scheduler.check_repo_changed("a/b", cache, get_fn=self._get(200, "abc123")))
        self.assertEqual(cache["sha:a/b"], "abc123")

    def test_etag_churn_with_same_commit_is_not_a_change(self):
        # Regression for the hosted tick at 2026-11-26T07:26Z: the ETag
        # changed on every repo with no new commit. The check never sees
        # or sends an ETag now; only the SHA decides.
        cache = {"sha:octocat/Hello-World": "sha-of-a-long-dormant-repo"}
        result = pulse_scheduler.check_repo_changed(
            "octocat/Hello-World", cache, get_fn=self._get(200, "sha-of-a-long-dormant-repo"))
        self.assertFalse(result)

    def test_failed_request_is_unknown_and_leaves_cache_alone(self):
        cache = {"sha:a/b": "abc123"}
        self.assertIsNone(pulse_scheduler.check_repo_changed("a/b", cache, get_fn=self._get(None, None)))
        self.assertEqual(cache["sha:a/b"], "abc123")

    def test_unexpected_status_is_unknown_not_changed(self):
        self.assertIsNone(pulse_scheduler.check_repo_changed("a/b", {}, get_fn=self._get(500, None)))

    def test_ok_status_without_a_sha_is_unknown(self):
        self.assertIsNone(pulse_scheduler.check_repo_changed("a/b", {}, get_fn=self._get(200, None)))


class FetchLatestShaTests(unittest.TestCase):
    """The HTTP wrapper, with requests.get stubbed."""

    class _Resp:
        def __init__(self, status, body=None, bad_json=False):
            self.status_code, self._body, self._bad = status, body, bad_json

        def json(self):
            if self._bad:
                raise ValueError("not json")
            return self._body

    def _run(self, resp=None, exc=None):
        def fake_get(*a, **k):
            if exc:
                raise exc
            return resp
        with mock.patch.object(pulse_scheduler.requests, "get", fake_get):
            return pulse_scheduler._fetch_latest_sha("a/b")

    def test_reads_sha_from_first_commit(self):
        self.assertEqual(self._run(self._Resp(200, [{"sha": "abc"}, {"sha": "def"}])), (200, "abc"))

    def test_empty_list_is_unknown(self):
        self.assertEqual(self._run(self._Resp(200, [])), (None, None))

    def test_malformed_body_is_unknown(self):
        self.assertEqual(self._run(self._Resp(200, bad_json=True)), (None, None))
        self.assertEqual(self._run(self._Resp(200, [{"no_sha": 1}])), (None, None))

    def test_http_error_status_is_passed_through(self):
        self.assertEqual(self._run(self._Resp(409)), (409, None))

    def test_network_error_is_unknown(self):
        import requests
        self.assertEqual(self._run(exc=requests.exceptions.ConnectionError("x")), (None, None))


if __name__ == "__main__":
    unittest.main()
