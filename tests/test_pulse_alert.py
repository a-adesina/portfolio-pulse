"""
Tests — pulse_alert.py
=========================
Deterministic, mocked tests over hand-built log lines, same discipline
as test_github_pull.py's MockedNegativeCaseTests: reliably reproducing
"this is the third bad run in a row" on demand isn't practical against a
real log, mocking the log content is the correct call here.

Run directly:
    python3 -m unittest tests.test_pulse_alert -v
"""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pulse_alert


def write_log(lines):
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    for line in lines:
        f.write(json.dumps(line) + "\n")
    f.close()
    return f.name


def started(run_id, n=5):
    return {"ts": "t", "run_id": run_id, "event": "run_started", "repo": None,
            "tracked_repo_count": n}


def finished(run_id, succeeded, attempted):
    return {"ts": "t", "run_id": run_id, "event": "run_finished", "repo": None,
            "succeeded": succeeded, "attempted": attempted}


def failed(run_id, repo, reason):
    return {"ts": "t", "run_id": run_id, "event": "repo_pull_failed", "repo": repo,
            "reason": reason}


class AlertConditionTests(unittest.TestCase):

    def setUp(self):
        self._log_path = None

    def tearDown(self):
        if self._log_path and os.path.exists(self._log_path):
            os.remove(self._log_path)

    def _check(self, lines):
        self._log_path = write_log(lines)
        return pulse_alert.check_alerts(self._log_path)

    def test_no_log_file_is_healthy(self):
        self.assertEqual(pulse_alert.check_alerts("/nonexistent/path.jsonl"), [])

    def test_healthy_run_triggers_nothing(self):
        alerts = self._check([
            started("r1"),
            finished("r1", succeeded=5, attempted=5),
        ])
        self.assertEqual(alerts, [])

    def test_run_never_finished_is_critical(self):
        alerts = self._check([started("r1")])
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0][0], "critical")
        self.assertIn("never reported run_finished", alerts[0][1])

    def test_total_failure_is_critical_and_names_repos_and_reasons(self):
        alerts = self._check([
            started("r1", n=2),
            failed("r1", "a/b", "repo_lookup_failed"),
            failed("r1", "c/d", "repo_lookup_failed"),
            finished("r1", succeeded=0, attempted=2),
        ])
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0][0], "critical")
        self.assertIn("0 of 2", alerts[0][1])
        self.assertIn("a/b", alerts[0][1])
        self.assertIn("repo_lookup_failed", alerts[0][1])

    def test_degraded_run_is_a_warning_not_critical(self):
        # 1 of 5 succeeded = 20%, below the 50% degraded threshold, but
        # not zero, so this is a warning, not the total-failure critical.
        alerts = self._check([
            started("r1", n=5),
            finished("r1", succeeded=1, attempted=5),
        ])
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0][0], "warning")
        self.assertIn("20%", alerts[0][1])

    def test_healthy_run_above_threshold_is_not_degraded(self):
        # 4 of 5 = 80%, comfortably above the 50% threshold.
        alerts = self._check([
            started("r1", n=5),
            finished("r1", succeeded=4, attempted=5),
        ])
        self.assertEqual(alerts, [])

    def test_two_consecutive_total_failures_trigger_the_repeated_alert(self):
        alerts = self._check([
            started("r1", n=2), finished("r1", succeeded=0, attempted=2),
            started("r2", n=2), finished("r2", succeeded=0, attempted=2),
        ])
        # The latest run's own total-failure alert, PLUS the repeated-pattern alert.
        severities_and_texts = [a[1] for a in alerts]
        self.assertTrue(any("repeated pattern" in t for t in severities_and_texts))
        self.assertTrue(any("0 of 2" in t for t in severities_and_texts))

    def test_single_bad_run_after_good_ones_is_not_called_repeated(self):
        alerts = self._check([
            started("r1", n=2), finished("r1", succeeded=2, attempted=2),
            started("r2", n=2), finished("r2", succeeded=2, attempted=2),
            started("r3", n=2), finished("r3", succeeded=0, attempted=2),
        ])
        texts = [a[1] for a in alerts]
        self.assertFalse(any("repeated pattern" in t for t in texts))
        self.assertTrue(any("0 of 2" in t for t in texts))

    def test_malformed_log_line_is_skipped_not_fatal(self):
        self._log_path = write_log([])
        with open(self._log_path, "a") as f:
            f.write("not valid json\n")
            f.write(json.dumps(started("r1")) + "\n")
            f.write(json.dumps(finished("r1", 3, 3)) + "\n")
        alerts = pulse_alert.check_alerts(self._log_path)
        self.assertEqual(alerts, [])  # proves the bad line didn't crash the check


class SendAlertTests(unittest.TestCase):
    """Alerting's delivery mechanism, mocked — never hits a real network."""

    def test_no_webhook_configured_prints_and_returns_false(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("sys.stderr"):
                result = pulse_alert.send_alert("critical", "test message", webhook_url=None)
        self.assertFalse(result)

    @patch("requests.post")
    def test_successful_webhook_post_returns_true(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        result = pulse_alert.send_alert("warning", "test message", webhook_url="https://example.com/hook")
        self.assertTrue(result)
        mock_post.assert_called_once()
        self.assertEqual(mock_post.call_args.kwargs["json"]["message"], "test message")

    @patch("requests.post")
    def test_webhook_error_response_returns_false_not_raises(self, mock_post):
        mock_post.return_value = MagicMock(status_code=500)
        with patch("sys.stderr"):
            result = pulse_alert.send_alert("critical", "test message", webhook_url="https://example.com/hook")
        self.assertFalse(result)

    @patch("requests.post", side_effect=ConnectionError("network down"))
    def test_network_failure_returns_false_not_raises(self, mock_post):
        with patch("sys.stderr"):
            result = pulse_alert.send_alert("critical", "test message", webhook_url="https://example.com/hook")
        self.assertFalse(result)  # the key assertion: no exception propagated


if __name__ == "__main__":
    unittest.main()
