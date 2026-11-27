"""
Tests — github_status_pull.py
================================
Three tiers, deliberately kept separate:

1. Pure function tests (days_since) — no network, always run.
2. Mocked negative-case tests — fake the HTTP layer with unittest.mock so
   404s, rate-limit responses, and empty-CI states can be tested
   deterministically, on demand, regardless of GitHub's actual rate limit
   at the moment these run. This is the right call for these specific
   cases, not a workaround: reliably reproducing a 404 or a rate-limit
   response on demand from a live service isn't practical, mocking it is
   the correct engineering practice here, the same way a payments
   system's tests don't wait for a real card to actually get declined.
3. Live integration tests against real public repos, for the specific
   edge cases that real, existing repos can actually provide: a
   genuinely nonexistent repo (real 404), a repo with no CI configured
   (real absence of signal), a genuinely dormant repo (real staleness).
   These require network and GitHub's rate limit to cooperate; if the
   limit is exhausted when this runs, they SKIP with an honest reason
   rather than reporting a false failure or a false pass.

Run directly:
    python3 -m unittest tests.test_github_pull -v

Structured-logging note: these tests exercise pull_repo_status() and
main() directly, which now emit structured log events via pulse_log.py
(GAP_ANALYSIS.md §3.4). setUpModule/tearDownModule below redirect
pulse_log.LOG_PATH to a throwaway temp file for the duration of this
module's tests, so running the suite never appends test noise to the
real pulse_run_log.jsonl a real pull run would produce.
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import github_status_pull as gsp
import pulse_log

_ORIGINAL_LOG_PATH = pulse_log.LOG_PATH
_TEST_LOG_FILE = None


def setUpModule():
    global _TEST_LOG_FILE
    _TEST_LOG_FILE = tempfile.NamedTemporaryFile(prefix="pulse_test_log_", suffix=".jsonl", delete=False)
    pulse_log.LOG_PATH = _TEST_LOG_FILE.name


def tearDownModule():
    pulse_log.LOG_PATH = _ORIGINAL_LOG_PATH
    if _TEST_LOG_FILE and os.path.exists(_TEST_LOG_FILE.name):
        os.remove(_TEST_LOG_FILE.name)


class DaysSinceTests(unittest.TestCase):

    def test_none_input_returns_none(self):
        self.assertIsNone(gsp.days_since(None))

    def test_empty_string_returns_none(self):
        self.assertIsNone(gsp.days_since(""))

    def test_valid_recent_timestamp(self):
        from datetime import datetime, timezone, timedelta
        ts = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.assertEqual(gsp.days_since(ts), 3)

    def test_malformed_timestamp_raises_rather_than_silently_wrong(self):
        # Documented current behavior, not a gap: a malformed timestamp
        # fails loudly (ValueError from strptime) rather than silently
        # producing a wrong day count. For a reporting system, a loud
        # failure that's visible and fixable beats a quiet wrong number
        # that erodes trust in every other figure on the report.
        with self.assertRaises(ValueError):
            gsp.days_since("not-a-real-timestamp")


class MockedNegativeCaseTests(unittest.TestCase):
    """Deterministic, on-demand reproduction of conditions a live service
    won't reliably hand you on request."""

    @patch("github_status_pull.requests.get")
    def test_404_on_repo_lookup_returns_none_not_a_crash(self, mock_get):
        mock_get.return_value = MagicMock(status_code=404, text="Not Found")
        result = gsp._get("https://api.github.com/repos/nobody/nothing")
        self.assertIsNone(result)

    @patch("github_status_pull.requests.get")
    def test_rate_limit_response_returns_none_not_a_crash(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=403, text="API rate limit exceeded for your IP."
        )
        result = gsp._get("https://api.github.com/repos/whoever/whatever")
        self.assertIsNone(result)

    @patch("github_status_pull.requests.get")
    def test_pull_repo_status_none_when_repo_itself_404s(self, mock_get):
        # The very first call (repo lookup) fails; everything downstream
        # of it must be skipped cleanly, not attempted against a None.
        mock_get.return_value = MagicMock(status_code=404, text="Not Found")
        result = gsp.pull_repo_status("nobody/nothing")
        self.assertIsNone(result)

    @patch("github_status_pull.requests.get")
    def test_ci_status_no_check_runs_and_no_legacy_status(self, mock_get):
        def fake_response(url, headers=None, params=None, timeout=None):
            if "check-runs" in url:
                return MagicMock(status_code=200, json=lambda: {"check_runs": []})
            if "/status" in url:
                return MagicMock(status_code=200, json=lambda: {"total_count": 0, "state": "pending"})
            return MagicMock(status_code=404, text="unexpected call")
        mock_get.side_effect = fake_response
        result = gsp.get_ci_status("some/repo", "deadbeef")
        self.assertEqual(result, "no_ci_configured")

    @patch("github_status_pull.requests.get")
    def test_ci_status_detects_failure_in_check_runs(self, mock_get):
        def fake_response(url, headers=None, params=None, timeout=None):
            if "check-runs" in url:
                return MagicMock(status_code=200, json=lambda: {
                    "check_runs": [
                        {"status": "completed", "conclusion": "success"},
                        {"status": "completed", "conclusion": "failure"},
                    ]
                })
            return MagicMock(status_code=404)
        mock_get.side_effect = fake_response
        result = gsp.get_ci_status("some/repo", "deadbeef")
        self.assertEqual(result, "failure")

    @patch("github_status_pull.requests.get")
    def test_ci_status_falls_back_to_legacy_when_check_runs_empty(self, mock_get):
        def fake_response(url, headers=None, params=None, timeout=None):
            if "check-runs" in url:
                return MagicMock(status_code=200, json=lambda: {"check_runs": []})
            if "/status" in url:
                return MagicMock(status_code=200, json=lambda: {"total_count": 2, "state": "failure"})
            return MagicMock(status_code=404)
        mock_get.side_effect = fake_response
        result = gsp.get_ci_status("some/repo", "deadbeef")
        self.assertEqual(result, "failure")

    def test_ci_status_no_sha_returns_no_ci_configured_without_any_call(self):
        # No commit found upstream means there's nothing to check CI
        # against; this must short-circuit rather than call the API with
        # a None sha.
        result = gsp.get_ci_status("some/repo", None)
        self.assertEqual(result, "no_ci_configured")

    @patch("github_status_pull.requests.get")
    def test_partial_failure_on_commit_lookup_does_not_report_false_active(self, mock_get):
        # The real bug this guards against: repo lookup succeeds, but the
        # commits lookup fails partway through (a rate limit hit at
        # exactly that point, not on the initial call). The old logic
        # let staleness_days=None silently evaluate to is_stale=False,
        # reporting a project with NO data as falsely "active"/healthy.
        # Caught by actually running this repeatedly under real flaky
        # network conditions, not found by inspection. This test
        # reproduces that exact partial-failure shape deterministically.
        def fake_response(url, headers=None, params=None, timeout=None):
            if url.endswith("/repos/some/repo"):
                return MagicMock(status_code=200, json=lambda: {
                    "default_branch": "main", "open_issues_count": 5,
                })
            if "/commits" in url:
                # Simulates the rate limit hitting on THIS specific call,
                # not the initial repo lookup.
                return MagicMock(status_code=403, text="API rate limit exceeded")
            return MagicMock(status_code=200, json=lambda: [])
        mock_get.side_effect = fake_response

        result = gsp.pull_repo_status("some/repo")

        # The correct behavior: no misleading partial result at all, an
        # honest None, the same path a 404 on the repo itself already
        # takes, not a result claiming stale=False with no evidence.
        self.assertIsNone(result)


class RetryLogicTests(unittest.TestCase):
    """The narrowly-scoped retry behavior: transient failures (connection
    errors, 5xx) retry with backoff; non-transient ones (403 rate limit,
    404) do not, retrying those either wastes a call against a limit
    that won't reset in time, or retries a request that can never
    succeed. time.sleep is patched throughout so these run instantly
    rather than actually waiting out the backoff."""

    @patch("github_status_pull.time.sleep")
    @patch("github_status_pull.requests.get")
    def test_5xx_retries_then_succeeds(self, mock_get, mock_sleep):
        responses = [
            MagicMock(status_code=503, text="Service Unavailable"),
            MagicMock(status_code=503, text="Service Unavailable"),
            MagicMock(status_code=200, json=lambda: {"ok": True}),
        ]
        mock_get.side_effect = responses
        result = gsp._get("https://api.github.com/repos/some/repo")
        self.assertEqual(result, {"ok": True})
        self.assertEqual(mock_get.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)  # backed off twice, then succeeded

    @patch("github_status_pull.time.sleep")
    @patch("github_status_pull.requests.get")
    def test_5xx_exhausts_retries_and_returns_none(self, mock_get, mock_sleep):
        mock_get.return_value = MagicMock(status_code=500, text="Internal Server Error")
        result = gsp._get("https://api.github.com/repos/some/repo")
        self.assertIsNone(result)
        self.assertEqual(mock_get.call_count, gsp.MAX_RETRIES)

    @patch("github_status_pull.time.sleep")
    @patch("github_status_pull.requests.get")
    def test_connection_error_retries_then_succeeds(self, mock_get, mock_sleep):
        import requests as real_requests
        mock_get.side_effect = [
            real_requests.exceptions.ConnectionError("connection reset"),
            MagicMock(status_code=200, json=lambda: {"ok": True}),
        ]
        result = gsp._get("https://api.github.com/repos/some/repo")
        self.assertEqual(result, {"ok": True})
        self.assertEqual(mock_get.call_count, 2)

    @patch("github_status_pull.time.sleep")
    @patch("github_status_pull.requests.get")
    def test_403_rate_limit_never_retries(self, mock_get, mock_sleep):
        # The deliberate exception to the retry policy: confirm exactly
        # ONE call is made, not MAX_RETRIES, because retrying this
        # specific condition is pointless, not just unhelpful.
        mock_get.return_value = MagicMock(status_code=403, text="API rate limit exceeded")
        result = gsp._get("https://api.github.com/repos/some/repo")
        self.assertIsNone(result)
        self.assertEqual(mock_get.call_count, 1)
        mock_sleep.assert_not_called()

    @patch("github_status_pull.time.sleep")
    @patch("github_status_pull.requests.get")
    def test_404_never_retries(self, mock_get, mock_sleep):
        mock_get.return_value = MagicMock(status_code=404, text="Not Found")
        result = gsp._get("https://api.github.com/repos/some/repo")
        self.assertIsNone(result)
        self.assertEqual(mock_get.call_count, 1)
        mock_sleep.assert_not_called()


class InputValidationTests(unittest.TestCase):
    """get_default_branch_last_commit must degrade to (None, None) on an
    unexpected response shape, not raise, so one malformed repo can't
    take down the whole batch."""

    @patch("github_status_pull.requests.get")
    def test_empty_commit_list_returns_none_none(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200, json=lambda: [])
        sha, date = gsp.get_default_branch_last_commit("some/repo", "main")
        self.assertIsNone(sha)
        self.assertIsNone(date)

    @patch("github_status_pull.requests.get")
    def test_commit_entry_not_a_dict_handled_gracefully(self, mock_get):
        # A genuinely malformed shape: a list of strings instead of
        # commit objects. Must not raise.
        mock_get.return_value = MagicMock(status_code=200, json=lambda: ["not-a-commit-object"])
        sha, date = gsp.get_default_branch_last_commit("some/repo", "main")
        self.assertIsNone(sha)
        self.assertIsNone(date)

    @patch("github_status_pull.requests.get")
    def test_commit_missing_nested_fields_handled_gracefully(self, mock_get):
        # Present, but missing the nested commit.committer.date path a
        # schema change or a partial response could produce.
        mock_get.return_value = MagicMock(status_code=200, json=lambda: [
            {"sha": "abc123"}  # no "commit" key at all
        ])
        sha, date = gsp.get_default_branch_last_commit("some/repo", "main")
        self.assertIsNone(sha)
        self.assertIsNone(date)

    @patch("github_status_pull.requests.get")
    def test_well_formed_commit_extracts_correctly(self, mock_get):
        # The happy path, confirmed alongside the negative cases so this
        # test class proves both "rejects bad shape" and "still accepts
        # good shape", not just the former.
        mock_get.return_value = MagicMock(status_code=200, json=lambda: [
            {"sha": "abc123", "commit": {"committer": {"date": "2026-09-01T00:00:00Z"}}}
        ])
        sha, date = gsp.get_default_branch_last_commit("some/repo", "main")
        self.assertEqual(sha, "abc123")
        self.assertEqual(date, "2026-09-01T00:00:00Z")


class BatchResilienceTests(unittest.TestCase):
    """main()'s per-repo try/except: one repo raising an unhandled
    exception must not silently drop every repo after it in the batch."""

    @patch("github_status_pull.pull_repo_status")
    def test_one_repo_raising_does_not_abort_the_batch(self, mock_pull):
        good_result = {"repo": "good/repo", "stale": False}

        def side_effect(repo):
            if repo == "bad/repo":
                raise RuntimeError("simulated unexpected failure")
            return good_result

        mock_pull.side_effect = side_effect
        original_repos = gsp.TRACKED_REPOS
        gsp.TRACKED_REPOS = ["bad/repo", "good/repo"]

        # gsp.main() writes pull_results.json. An earlier version of this
        # test deleted that file afterwards, which destroyed a real pull
        # whenever the suite was run in a working copy that held one
        # (INCIDENT_LOG.md addendum F). Move any existing file aside and
        # put it back, byte for byte.
        import os as _os
        import shutil as _shutil
        out_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "pull_results.json")
        backup_path = out_path + ".test_backup"
        original_bytes = None
        if _os.path.exists(out_path):
            with open(out_path, "rb") as f:
                original_bytes = f.read()
            _shutil.move(out_path, backup_path)
        try:
            results = gsp.main()
        finally:
            gsp.TRACKED_REPOS = original_repos
            if _os.path.exists(out_path):
                _os.remove(out_path)
            if _os.path.exists(backup_path):
                _shutil.move(backup_path, out_path)

        if original_bytes is not None:
            with open(out_path, "rb") as f:
                self.assertEqual(f.read(), original_bytes,
                                 "an existing pull_results.json must survive this test unchanged")

        # The bad repo is skipped, but the good one still makes it
        # through, that's the whole point of the fix.
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["repo"], "good/repo")


class LiveIntegrationTests(unittest.TestCase):
    """Real network calls against real public repos, for the edge cases
    real repos can actually provide. Each test checks whether GitHub's
    rate limit is currently available before asserting anything, and
    skips with an explicit, honest reason rather than reporting a false
    result if it isn't. This is the tier that's genuinely
    'achievable with the repos' rather than simulated.

    DESIGN NOTE, itself a real finding: an earlier version of this class
    checked quota ONCE in setUpClass and skipped upfront if it was too
    low. That's provably unreliable, caught by actually running these
    tests repeatedly in this build's sandbox: the quota can, and did,
    change in the moments between the check and the actual pull, this
    environment's shared IP is under enough concurrent external load
    that a pre-check can read 'enough quota' and the real call can still
    hit a 403 seconds later. Checking AFTER the attempt, and diagnosing
    a None result by re-checking quota at that point, is the only
    version of this that's actually correct given that reality, not a
    theoretical one."""

    def _current_rate_remaining(self):
        import requests
        try:
            resp = requests.get("https://api.github.com/rate_limit", timeout=10)
            rate = resp.json().get("rate")
        except Exception:
            rate = None
        # None, not 0, whenever GitHub did not actually report a quota: a
        # request that failed, or an answer with no "rate" block (an error
        # body from a proxy or a block page). "Could not read the quota" is
        # a different condition from "GitHub says the quota is used up",
        # and the skip message must not claim the second when it was the
        # first (INCIDENT_LOG.md addendum G).
        if not isinstance(rate, dict) or not isinstance(rate.get("remaining"), int):
            return None
        return rate["remaining"]

    def _skip_if_result_none_due_to_rate_limit(self, result, context):
        """Called when a test expected a non-None result and got None.
        Distinguishes 'the rate limit hit during this specific attempt'
        (skip, honestly, not a code issue) from 'quota is fine but the
        result was still None' (a real potential defect, fail on it)."""
        remaining = self._current_rate_remaining()
        if remaining is None:
            self.skipTest(
                f"{context}: the GitHub API quota could not be read from this "
                f"environment (no usable answer from the rate-limit endpoint, for "
                f"example because the network is blocked), so the live check could "
                f"not run. Not a code failure, and the equivalent logic path is "
                f"covered deterministically by MockedNegativeCaseTests above."
            )
        elif remaining == 0:
            self.skipTest(
                f"{context}: GitHub API rate limit was exhausted during this "
                f"attempt (0 remaining, confirmed immediately after). Not a code "
                f"failure, an external quota state, and the equivalent logic path "
                f"is covered deterministically by MockedNegativeCaseTests above."
            )
        else:
            self.fail(
                f"{context}: result was unexpectedly None, but {remaining} API "
                f"calls remain, so this is NOT a rate-limit condition and may be "
                f"a genuine defect worth investigating, not a quota issue."
            )

    def test_an_unreadable_quota_is_reported_as_unreadable_not_as_rate_limited(self):
        import requests
        from unittest.mock import patch as _patch

        class _Resp:
            def __init__(self, body):
                self._body = body

            def json(self):
                return self._body

        cases = {
            "request fails": dict(side_effect=requests.exceptions.ConnectionError("blocked")),
            "answer has no rate block": dict(return_value=_Resp({"message": "blocked by policy"})),
            "answer is not json": dict(return_value=type("R", (), {"json": lambda self: (_ for _ in ()).throw(ValueError("x"))})()),
        }
        for name, kwargs in cases.items():
            with self.subTest(name):
                with _patch.object(requests, "get", **kwargs):
                    self.assertIsNone(self._current_rate_remaining())
                    with self.assertRaises(unittest.SkipTest) as cm:
                        self._skip_if_result_none_due_to_rate_limit(None, "ctx")
                self.assertIn("could not be read", str(cm.exception))
                self.assertNotIn("rate limit was exhausted", str(cm.exception))

    def test_a_genuinely_exhausted_quota_is_still_reported_as_exhausted(self):
        import requests
        from unittest.mock import patch as _patch

        class _Resp:
            def json(self):
                return {"rate": {"remaining": 0}}

        with _patch.object(requests, "get", return_value=_Resp()):
            with self.assertRaises(unittest.SkipTest) as cm:
                self._skip_if_result_none_due_to_rate_limit(None, "ctx")
        self.assertIn("rate limit was exhausted", str(cm.exception))

    def test_a_quota_with_calls_remaining_makes_a_none_result_a_failure(self):
        import requests
        from unittest.mock import patch as _patch

        class _Resp:
            def json(self):
                return {"rate": {"remaining": 4000}}

        with _patch.object(requests, "get", return_value=_Resp()):
            with self.assertRaises(self.failureException):
                self._skip_if_result_none_due_to_rate_limit(None, "ctx")

    def test_live_nonexistent_repo_returns_none(self):
        # A None result here is correct either way, a genuine 404 or a
        # rate limit both produce None from pull_repo_status, and both
        # are a legitimate "nothing to report" outcome for this specific
        # test. That ambiguity is real and acceptable here specifically
        # because the assertion doesn't need to know which one occurred.
        result = gsp.pull_repo_status("octocat/this-repo-genuinely-does-not-exist-xyz")
        self.assertIsNone(result)

    def test_live_repo_returns_a_valid_ci_status(self):
        # Replaces test_live_repo_with_no_ci_configured, which asserted
        # that octocat/Hello-World has NO CI. That was an unpinned claim
        # about a repo this project does not control, and nothing pinned
        # it: in this build's recorded runs the test was skipped (rate
        # limit, then this sandbox's network policy), so the assertion was
        # not being exercised. The first hosted CI run executed it and got
        # 'success', so some check run or commit status exists on that
        # repo's latest commit now. get_ci_status reporting it
        # is correct behavior, not a defect.
        # What a live test can honestly assert is that the real response
        # maps onto the documented vocabulary. The specific
        # 'no_ci_configured' outcome is covered deterministically, with
        # controlled inputs, by test_ci_status_no_check_runs_and_no_legacy_status
        # and test_ci_status_no_sha_returns_no_ci_configured_without_any_call
        # in MockedNegativeCaseTests above.
        result = gsp.pull_repo_status("octocat/Hello-World")
        if result is None:
            self._skip_if_result_none_due_to_rate_limit(result, "live CI status vocabulary check")
            return
        self.assertIn(
            result["ci_status"],
            ("success", "failure", "pending", "no_ci_configured"),
        )

    def test_live_dormant_repo_is_stale(self):
        result = gsp.pull_repo_status("octocat/Hello-World")
        if result is None:
            self._skip_if_result_none_due_to_rate_limit(result, "dormant-repo staleness check")
            return
        self.assertTrue(result["stale"])
        self.assertGreater(result["days_since_last_commit"], gsp.STALENESS_THRESHOLD_DAYS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
