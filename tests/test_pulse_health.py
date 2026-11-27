"""
Tests — pulse_health.py
=========================
Pure logic over a log held in memory or a temp file. No network.
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pulse_health

NOW = datetime(2026, 11, 27, 12, 0, 0, tzinfo=timezone.utc)


def dec(ts, reason, pulled=False, trigger=None):
    e = {"ts": ts, "event": "scheduler_decision", "reason": reason, "should_pull": pulled}
    if trigger:
        e["trigger"] = trigger
    return e


def start(ts):
    return {"ts": ts, "event": "run_started"}


def finish(ts, ok=5, attempted=5):
    return {"ts": ts, "event": "run_finished", "succeeded": ok, "attempted": attempted}


class SummarizeTests(unittest.TestCase):
    def test_empty_log_has_no_pulls_and_no_next_due(self):
        s = pulse_health.summarize([], NOW)
        self.assertIsNone(s["last_pull_at"])
        self.assertIsNone(s["next_baseline_due"])
        self.assertEqual(s["pulls_in_window"], 0)
        self.assertEqual(s["history"], [])
        self.assertIsNone(s["last_decision"])

    def test_last_pull_and_its_result(self):
        ev = [start("2026-11-27T10:49:22Z"), finish("2026-11-27T10:49:41Z", ok=4, attempted=5)]
        s = pulse_health.summarize(ev, NOW)
        self.assertEqual(s["last_pull_at"], datetime(2026, 11, 27, 10, 49, 22, tzinfo=timezone.utc))
        self.assertEqual(s["last_pull_result"], {"succeeded": 4, "attempted": 5})

    def test_a_pull_that_never_finished_has_no_result(self):
        s = pulse_health.summarize([start("2026-11-27T10:49:22Z")], NOW)
        self.assertIsNone(s["last_pull_result"])

    def test_result_is_not_taken_from_an_earlier_run(self):
        ev = [start("2026-11-26T07:26:47Z"), finish("2026-11-26T07:27:08Z"), start("2026-11-27T10:49:22Z")]
        s = pulse_health.summarize(ev, NOW)
        self.assertIsNone(s["last_pull_result"])

    def test_pulls_in_window_only_counts_the_trailing_24h(self):
        ev = [start("2026-11-26T11:59:59Z"), start("2026-11-26T12:00:01Z"), start("2026-11-27T10:49:22Z")]
        self.assertEqual(pulse_health.summarize(ev, NOW)["pulls_in_window"], 2)

    def test_next_baseline_is_24h_after_the_last_pull(self):
        s = pulse_health.summarize([start("2026-11-27T10:49:22Z")], NOW)
        self.assertEqual(s["next_baseline_due"], datetime(2026, 11, 28, 10, 49, 22, tzinfo=timezone.utc))

    def test_cap_and_window_come_from_the_scheduler_constants(self):
        import pulse_scheduler
        s = pulse_health.summarize([], NOW)
        self.assertEqual(s["cap"], pulse_scheduler.MAX_PULLS_PER_WINDOW)
        self.assertEqual(s["window_hours"], pulse_scheduler.ROLLING_WINDOW_HOURS)

    def test_history_is_limited_to_the_most_recent_in_order(self):
        ev = [dec(f"2026-11-27T0{i}:00:00Z", "not_due") for i in range(9)]
        s = pulse_health.summarize(ev, NOW, history_limit=3)
        self.assertEqual([h["ts"] for h in s["history"]], ["2026-11-27T06:00:00Z", "2026-11-27T07:00:00Z", "2026-11-27T08:00:00Z"])
        self.assertEqual(s["total_decisions_on_record"], 9)

    def test_reason_labels(self):
        ev = [dec("2026-11-27T01:00:00Z", "baseline_due", True), dec("2026-11-27T02:00:00Z", "not_due"),
              dec("2026-11-27T03:00:00Z", "cap_reached"), dec("2026-11-27T04:00:00Z", "priority_change_detected", True)]
        labels = [h["label"] for h in pulse_health.summarize(ev, NOW)["history"]]
        self.assertEqual(labels, ["baseline pull", "skipped", "blocked by cap", "early pull (change detected)"])

    def test_unknown_reason_is_shown_as_is_not_hidden(self):
        h = pulse_health.summarize([dec("2026-11-27T01:00:00Z", "something_new")], NOW)["history"][0]
        self.assertEqual(h["label"], "something_new")

    def test_trigger_is_none_when_not_recorded_and_never_guessed(self):
        h = pulse_health.summarize([dec("2026-11-27T01:00:00Z", "not_due")], NOW)["history"][0]
        self.assertIsNone(h["trigger"])

    def test_trigger_is_labelled_when_recorded(self):
        ev = [dec("2026-11-27T01:00:00Z", "not_due", trigger="schedule"),
              dec("2026-11-27T02:00:00Z", "baseline_due", True, trigger="workflow_dispatch")]
        h = pulse_health.summarize(ev, NOW)["history"]
        self.assertEqual([x["trigger"] for x in h], ["scheduled", "manual"])

    def test_note_attaches_only_on_an_exact_timestamp_match(self):
        ev = [dec("2026-11-27T01:00:00Z", "priority_change_detected", True), dec("2026-11-27T02:00:00Z", "not_due")]
        h = pulse_health.summarize(ev, NOW, annotations={"2026-11-27T01:00:00Z": "a note"})["history"]
        self.assertEqual(h[0]["note"], "a note")
        self.assertIsNone(h[1]["note"])

    def test_last_decision_is_the_newest(self):
        ev = [dec("2026-11-27T01:00:00Z", "not_due"), dec("2026-11-27T02:00:00Z", "baseline_due", True)]
        self.assertEqual(pulse_health.summarize(ev, NOW)["last_decision"]["reason"], "baseline_due")


class LoadTests(unittest.TestCase):
    def test_load_events_skips_malformed_lines(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "log.jsonl")
        with open(p, "w") as f:
            f.write(json.dumps(start("2026-11-27T10:49:22Z")) + "\nnot json\n\n[1,2]\n")
        self.assertEqual(len(pulse_health.load_events(p)), 1)

    def test_missing_log_is_empty_not_an_error(self):
        self.assertEqual(pulse_health.load_events("/no/such/file"), [])

    def test_annotations_missing_or_broken_means_no_notes(self):
        self.assertEqual(pulse_health.load_annotations("/no/such/file"), {})
        d = tempfile.mkdtemp()
        p = os.path.join(d, "a.json")
        with open(p, "w") as f:
            f.write("{broken")
        self.assertEqual(pulse_health.load_annotations(p), {})

    def test_annotations_ignores_non_string_values(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "a.json")
        with open(p, "w") as f:
            json.dump({"decisions": {"a": "ok", "b": 5}}, f)
        self.assertEqual(pulse_health.load_annotations(p), {"a": "ok"})

    def test_shipped_annotations_file_parses_and_has_notes(self):
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "decision_annotations.json")
        notes = pulse_health.load_annotations(p)
        self.assertGreaterEqual(len(notes), 2)
        for ts in notes:
            self.assertIsNotNone(pulse_health._parse_ts(ts), f"{ts} is not a valid log timestamp")


if __name__ == "__main__":
    unittest.main()
