"""
Portfolio Pulse — Agent Evaluation Harness
=============================================
Closes a named gap from GAP_ANALYSIS.md §3.5: "No evaluation framework
for the agent layer." Read the honest scope below before citing this
anywhere — it is deliberately narrow, and overstating it would be the
exact kind of claim this whole project has been built to avoid.

WHAT THIS DOES TEST, for real, against real infrastructure:
  - The actual tool-use loop in agent_client.py (`run_agent_loop`), driving
    a REAL mcp_server.py subprocess over real stdio — the exact same code
    path used in production — with ONLY the Anthropic model call itself
    replaced by a scripted stand-in. The MCP server, the tool schemas, the
    tool execution, and the data underneath (a fixture, same shape
    github_status_pull.py produces) are all real.
  - Multi-round tool orchestration: a scripted "model" that calls one
    tool, receives the REAL result, and is handed that result back before
    producing a final answer.
  - The hard cap on tool-call rounds actually stops a model that never
    stops asking for tools, rather than looping forever.
  - An unknown-repo input reaches the agent loop as mcp_server.py's
    structured `{"error": ..., "known_repos": [...]}` value, not a crash
    and not an MCP-protocol-level error, confirming the error-sanitization
    fix recorded in MCP_VERIFICATION_LOG.md still holds when driven through
    the full agent loop, not just a direct tool call.
  - That `run_agent_loop`'s refactor (pulling the loop out of `run_agent`
    for testability) didn't change its behavior: same message shape, same
    stop condition, same tool-result format sent back to the model.

WHAT THIS DELIBERATELY DOES NOT TEST:
  - Whether a REAL Claude model, given these tools, chooses to call the
    right one, phrases an answer well, stays grounded under an ambiguous
    or adversarial question, or ever paraphrases a number wrong. That is
    a question about model behavior, not scaffolding, and it requires a
    live model and a live API key, neither available in this build
    environment — the same stated limit as agent_client.py's own
    docstring, MCP_VERIFICATION_LOG.md, and SOW.md §5/§6. This harness
    tests the rails the model runs on, not the model's judgment running
    on them. Don't let "there's an eval suite now" get compressed into
    "the agent's live behavior is verified" — it isn't, and this file is
    not where that would be verified.

Run directly:
    python3 -m unittest tests.test_agent_eval -v
Or via the aggregate runner:
    python3 run_tests.py
"""

import asyncio
import os
import shutil
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent_client
from mcp.client.stdio import StdioServerParameters

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE_PATH = os.path.join(BASE_DIR, "fixture_for_testing.json")
PULL_RESULTS_PATH = os.path.join(BASE_DIR, "pull_results.json")
BACKUP_PATH = os.path.join(BASE_DIR, "pull_results.json.eval_backup")


def _server_params():
    return StdioServerParameters(
        command=sys.executable,
        args=[os.path.join(BASE_DIR, "mcp_server.py")],
        cwd=BASE_DIR,
    )


def text_block(text):
    return SimpleNamespace(type="text", text=text)


def tool_use_block(name, input_, call_id):
    return SimpleNamespace(type="tool_use", name=name, input=input_, id=call_id)


def model_response(content, stop_reason):
    return SimpleNamespace(content=content, stop_reason=stop_reason)


class ScriptedClient:
    """Stands in for `Anthropic()`. Returns pre-scripted responses in
    order, one per call to `.messages.create(...)`, and records every
    call's `messages` argument so a test can assert on exactly what the
    real tool result looked like when it came back from the real server."""

    def __init__(self, script):
        self._script = list(script)
        self.calls = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._script:
            raise AssertionError("ScriptedClient ran out of scripted responses")
        return self._script.pop(0)


class AgentEvalTests(unittest.TestCase):
    """Each test spawns the REAL mcp_server.py as a subprocess, against a
    fixture-backed pull_results.json, so these exercise the real tool
    layer end to end, same as MCP_VERIFICATION_LOG.md's manual run, just
    automated and repeatable."""

    @classmethod
    def setUpClass(cls):
        # Don't clobber a real pull_results.json if one happens to exist;
        # a demo-scale eval suite shouldn't silently destroy a live pull.
        if os.path.exists(PULL_RESULTS_PATH):
            shutil.move(PULL_RESULTS_PATH, BACKUP_PATH)
        shutil.copy(FIXTURE_PATH, PULL_RESULTS_PATH)

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(PULL_RESULTS_PATH):
            os.remove(PULL_RESULTS_PATH)
        if os.path.exists(BACKUP_PATH):
            shutil.move(BACKUP_PATH, PULL_RESULTS_PATH)

    def run_loop(self, question, script, max_rounds=6):
        client = ScriptedClient(script)
        result = asyncio.run(
            agent_client.run_agent_loop(
                question, client, _server_params(), max_rounds=max_rounds, verbose=False
            )
        )
        return result, client

    def test_single_tool_call_then_final_answer(self):
        """Scripted model asks for list_projects, gets the REAL result
        back, then answers. Confirms the real tool result actually
        reaches the model-facing message list, not a stub — and,
        specifically, confirms ALL FIVE tracked projects arrive, not just
        one. `list_projects` returns a Python list; the installed mcp SDK
        serializes that as one content block PER ITEM, and an earlier
        version of this loop read only `result.content[0]`, silently
        dropping four of five projects. See INCIDENT_LOG.md, incident #6."""
        script = [
            model_response(
                [tool_use_block("list_projects", {}, "call_1")], "tool_use"
            ),
            model_response(
                [text_block("Five projects tracked; requests and Hello-World are stale.")],
                "end_turn",
            ),
        ]
        result, client = self.run_loop("What's the state of things?", script)

        self.assertEqual(result, "Five projects tracked; requests and Hello-World are stale.")
        self.assertEqual(len(client.calls), 2)
        # The second call must contain the REAL tool result from the REAL
        # server, not a placeholder or a truncated subset: all five
        # fixture repos must be present in what was sent back to "the
        # model", not just whichever one sorts first.
        second_call_messages = client.calls[1]["messages"]
        tool_result_blob = str(second_call_messages)
        for repo in ("tiangolo/fastapi", "pallets/flask", "psf/requests",
                     "github/gitignore", "octocat/Hello-World"):
            self.assertIn(repo, tool_result_blob, f"{repo} missing from tool result sent to model")
        self.assertIn("risk_tier", tool_result_blob)

    def test_multi_round_tool_orchestration(self):
        """Scripted model calls list_projects, then drills into one
        specific repo before answering — the two-step pattern the real
        system prompt asks for ('use this first... before drilling in')."""
        script = [
            model_response([tool_use_block("list_projects", {}, "c1")], "tool_use"),
            model_response(
                [tool_use_block(
                    "get_project_status", {"repo": "psf/requests"}, "c2"
                )],
                "tool_use",
            ),
            model_response(
                [text_block("psf/requests is stale with no CI configured.")],
                "end_turn",
            ),
        ]
        result, client = self.run_loop("What's going on with requests?", script)

        self.assertEqual(result, "psf/requests is stale with no CI configured.")
        self.assertEqual(len(client.calls), 3)
        third_call_messages = str(client.calls[2]["messages"])
        self.assertIn("no_ci_configured", third_call_messages)

    def test_unknown_repo_surfaces_structured_error_not_a_crash(self):
        """Re-runs the exact scenario MCP_VERIFICATION_LOG.md's bug fix
        covers, but through the full agent loop rather than a direct
        tool call: an unknown repo must come back as the structured
        {"error": ..., "known_repos": [...]} value, and the loop must not
        raise or hang, it must hand that value to "the model" like any
        other tool result."""
        script = [
            model_response(
                [tool_use_block(
                    "get_project_status", {"repo": "nonexistent/repo"}, "c1"
                )],
                "tool_use",
            ),
            model_response(
                [text_block("That repo isn't tracked. Tracked repos are listed below.")],
                "end_turn",
            ),
        ]
        result, client = self.run_loop("Tell me about nonexistent/repo", script)

        self.assertEqual(result, "That repo isn't tracked. Tracked repos are listed below.")
        second_call_messages = str(client.calls[1]["messages"])
        self.assertIn("is not a tracked project", second_call_messages)
        self.assertIn("known_repos", second_call_messages)

    def test_hard_cap_stops_a_model_that_never_stops_calling_tools(self):
        """A model that always wants another tool call must not loop
        forever. Scripts more tool_use responses than the round cap and
        confirms the loop stops exactly at the cap with the documented
        fallback message, not an infinite await."""
        script = [
            model_response([tool_use_block("list_projects", {}, f"c{i}")], "tool_use")
            for i in range(5)
        ]
        result, client = self.run_loop("Never stop asking", script, max_rounds=3)

        self.assertEqual(result, "Agent did not reach a final answer within the call budget.")
        self.assertEqual(len(client.calls), 3)  # stopped at the cap, not the script length


if __name__ == "__main__":
    unittest.main()
