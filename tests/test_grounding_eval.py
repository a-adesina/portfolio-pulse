"""
Tests — grounding_eval.py's extraction/comparison logic
===========================================================
What's testable here, honestly: the mechanical check itself (does a
number or status word in an answer actually appear in the ground-truth
tool output), independent of any model. What's NOT testable here: a live
model's actual behavior, which requires a live ANTHROPIC_API_KEY — the
same stated limit as grounding_eval.py's own docstring. These tests
exercise check_grounding(), extract_numbers(), and extract_status_claims()
directly against hand-built answer/tool_log pairs, never a live model.

Run directly:
    python3 -m unittest tests.test_grounding_eval -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import grounding_eval as ge


class ExtractionTests(unittest.TestCase):

    def test_extract_numbers_basic(self):
        self.assertEqual(ge.extract_numbers("5 projects, 3 stale"), {"5", "3"})

    def test_extract_numbers_handles_decimals(self):
        self.assertEqual(ge.extract_numbers("spend is 90.5 percent of plan"), {"90.5"})

    def test_extract_numbers_empty_on_no_digits(self):
        self.assertEqual(ge.extract_numbers("no numbers here at all"), set())

    def test_extract_status_claims_case_insensitive(self):
        claims = ge.extract_status_claims("The project is STALE and the build is Broken.")
        self.assertEqual(claims, {"stale", "broken"})

    def test_extract_status_claims_only_matches_known_vocabulary(self):
        claims = ge.extract_status_claims("Everything looks fine and dandy, no issues.")
        self.assertEqual(claims, set())


def tool_entry(result_text):
    return {"tool": "get_project_status", "input": {}, "result": result_text}


class GroundingCheckTests(unittest.TestCase):

    def test_fully_grounded_answer_passes(self):
        tool_log = [tool_entry('{"repo": "psf/requests", "risk_tier": "watch", '
                                '"days_since_commit": 52, "open_issues": 28}')]
        answer = "psf/requests has 28 open issues and has gone 52 days without a commit, risk tier watch."
        result = ge.check_grounding(answer, tool_log)
        self.assertTrue(result["grounded"])
        self.assertEqual(result["unverified_numbers"], [])
        self.assertEqual(result["unverified_statuses"], [])

    def test_fabricated_number_fails(self):
        tool_log = [tool_entry('{"repo": "psf/requests", "open_issues": 28}')]
        # The model claims 45, which never appeared anywhere in the tool output.
        answer = "psf/requests has 45 open issues."
        result = ge.check_grounding(answer, tool_log)
        self.assertFalse(result["grounded"])
        self.assertIn("45", result["unverified_numbers"])

    def test_fabricated_status_word_fails(self):
        tool_log = [tool_entry('{"repo": "tiangolo/fastapi", "code_health": "HEALTHY"}')]
        # The model claims "broken", which the real tool output never said.
        answer = "tiangolo/fastapi is currently broken."
        result = ge.check_grounding(answer, tool_log)
        self.assertFalse(result["grounded"])
        self.assertIn("broken", result["unverified_statuses"])

    def test_empty_tool_log_with_numeric_claim_fails(self):
        # No tool was ever called, so nothing in the answer can be grounded.
        result = ge.check_grounding("There are 5 projects, all healthy.", [])
        self.assertFalse(result["grounded"])
        self.assertEqual(result["tool_calls_made"], 0)

    def test_answer_with_no_numbers_or_statuses_is_vacuously_grounded(self):
        # An answer that makes no checkable claims at all isn't a grounding
        # failure by this mechanical check — a real limitation, named in
        # grounding_eval.py's own docstring, not hidden here.
        tool_log = [tool_entry('{"repo": "psf/requests"}')]
        result = ge.check_grounding("That project exists and has some activity.", tool_log)
        self.assertTrue(result["grounded"])


class RunOneEvalGroundingLogicTests(unittest.IsolatedAsyncioTestCase):
    """Tests the requires_tool_call enforcement in run_one_eval without a
    live model: a fake agent_client.run_agent_loop stands in."""

    async def test_data_question_with_zero_tool_calls_fails_even_with_grounded_text(self):
        import unittest.mock as mock

        spec = {"id": "test_q", "question": "anything", "trap": None, "requires_tool_call": True}

        async def fake_run_agent_loop(question, client, server_params, tool_log=None, verbose=True):
            # Simulates a model that answered without calling any tool,
            # even though the system prompt says to call one first —
            # exactly the "invited_to_guess" trap scenario.
            return "There are roughly 20 open issues in total."

        with mock.patch("agent_client.run_agent_loop", fake_run_agent_loop):
            result = await ge.run_one_eval(client=None, server_params=None, spec=spec)

        self.assertFalse(result["grounded"])
        self.assertEqual(result["failure_reason"], "no_tool_called_for_a_data_question")


if __name__ == "__main__":
    unittest.main()
