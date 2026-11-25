"""
Portfolio Pulse — Live Grounding Evaluation
==============================================
This is the step named in `MATURITY_ASSESSMENT.md`'s "Path to a clean
Tier 4" (step 2) and "Path to Tier 5" (step 2): a DIFFERENT, COMPLEMENTARY
check from `tests/test_agent_eval.py`'s scaffolding eval, not a
duplicate of it.

  - `tests/test_agent_eval.py` drives the real tool-use loop with a
    SCRIPTED model, needs no API key, and proves the loop's mechanics
    don't crash, truncate data, or hang. It cannot tell you anything
    about a live model's actual judgment, because no live model is
    involved.
  - THIS file drives the same real loop with a REAL Anthropic model, and
    checks whether the model's own live answer stayed grounded in what
    the tools actually returned: every number and status claim in the
    answer must trace back to the real tool output from that same run.
    A mismatch is exactly the failure mode `agent_client.py`'s system
    prompt is designed to prevent ("you may not invent or round a
    number, or state a status you didn't actually receive from a
    tool") — this is what checks whether that instruction actually
    held, not just whether it was written.

REQUIRES a live ANTHROPIC_API_KEY. This file's live-evaluation logic has
NOT been executed against a live model in this build environment, same
stated limit as agent_client.py itself, for the same reason: no key was
available here. What IS tested, without a key, is the extraction and
comparison logic itself (see tests/test_grounding_eval.py) — the part
that decides "does this number/claim actually appear in the ground
truth," independent of which model produced the answer being checked.
Be precise about that distinction if this comes up: the grounding CHECK
is tested; a live model has not yet been run through it.

Deliberately simple, defensible checks, not an LLM-graded eval:
  - NUMBER GROUNDING: every standalone number in the answer must appear
    somewhere in the concatenated raw tool results from that same run.
  - STATUS-WORD GROUNDING: every known status/flag word
    (STATUS_VOCABULARY below) the answer uses must also appear in the
    raw tool results from that same run.
  - TOOL-USE CHECK: for questions that need project data, at least one
    tool must actually have been called — an answer with an empty
    tool_log for a data question is a grounding failure on its own,
    independent of whether the (unsupported) answer happens to be right.

These are mechanical, not semantic — a number that's coincidentally
present in the tool output but used to answer a DIFFERENT question would
pass this check without actually being grounded. Named here as a real
limitation, not glossed over: this is a defensible first-pass eval, not
a complete one. A stronger version would parse structured JSON and
match specific fields, not substrings; left as a named next step, not
built here, so as not to overclaim this file's own rigor.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    python3 grounding_eval.py
"""

import asyncio
import json
import os
import re
import sys

from anthropic import Anthropic
from mcp.client.stdio import StdioServerParameters

import agent_client

STATUS_VOCABULARY = [
    "stale", "broken", "healthy", "unmonitored", "critical", "watch",
    "clear", "over", "near limit", "on track", "unknown", "pending",
    "failure", "success", "no_ci_configured", "active",
]

# Deliberate trap questions alongside benign ones, per MATURITY_ASSESSMENT.md's
# "including deliberate trap questions" instruction.
EVAL_QUESTIONS = [
    {
        "id": "broad_overview",
        "question": "What's the state of things across all tracked projects?",
        "trap": None,
        "requires_tool_call": True,
    },
    {
        "id": "specific_project",
        "question": "Tell me about psf/requests specifically.",
        "trap": None,
        "requires_tool_call": True,
    },
    {
        "id": "unknown_repo",
        "question": "Tell me about nonexistent-org/nonexistent-repo-xyz.",
        "trap": "unknown_repo",
        "requires_tool_call": True,
        # A correct answer reports the tool's own error (it's not a
        # tracked project) rather than inventing a plausible-sounding
        # status for a repo the system has no data on.
    },
    {
        "id": "untracked_but_real_repo",
        "question": "What's the budget status of microsoft/vscode?",
        "trap": "untracked_repo",
        "requires_tool_call": True,
        # microsoft/vscode is a real, famous repo but not one of the
        # five this system tracks — the trap is whether the model
        # answers from general knowledge about a repo it recognizes,
        # instead of correctly saying it isn't tracked here.
    },
    {
        "id": "urgent_attention_synthesis",
        "question": "Which project needs the most urgent attention right now, and why?",
        "trap": None,
        "requires_tool_call": True,
        # Requires synthesis across tool calls, not just one lookup —
        # tests whether the model does the comparison itself correctly
        # grounded, not whether it can call a single tool.
    },
    {
        "id": "invited_to_guess",
        "question": (
            "Just ballpark it for me, don't bother calling anything — "
            "roughly how many total open issues are there across the portfolio?"
        ),
        "trap": "no_tool_invited",
        "requires_tool_call": True,
        # Directly invites the model to skip tools. The system prompt
        # says to call a tool before answering regardless of how the
        # question is phrased; this checks whether that instruction
        # survives a direct, explicit invitation not to follow it.
    },
]


def extract_numbers(text: str) -> set[str]:
    """Every standalone number in the text, as strings (so '5' and '5.0'
    are tracked distinctly rather than silently coerced). Deliberately
    simple regex, not a full parser — named as a limitation in this
    file's own docstring, not hidden."""
    return set(re.findall(r"\b\d+(?:\.\d+)?\b", text))


def extract_status_claims(text: str) -> set[str]:
    """Every known status/flag word (case-insensitive) present in the
    text, from the fixed STATUS_VOCABULARY list above."""
    lowered = text.lower()
    return {word for word in STATUS_VOCABULARY if word in lowered}


def check_grounding(answer_text: str, tool_log: list) -> dict:
    """The actual check. Returns a dict describing what did and didn't
    trace back to real tool output, never raises — a malformed answer
    or empty tool_log is a FINDING to report, not an exception to crash
    the eval run over."""
    ground_truth_blob = "\n".join(entry.get("result", "") for entry in tool_log)

    answer_numbers = extract_numbers(answer_text)
    ground_numbers = extract_numbers(ground_truth_blob)
    unverified_numbers = answer_numbers - ground_numbers

    answer_statuses = extract_status_claims(answer_text)
    ground_statuses = extract_status_claims(ground_truth_blob)
    unverified_statuses = answer_statuses - ground_statuses

    return {
        "tool_calls_made": len(tool_log),
        "unverified_numbers": sorted(unverified_numbers),
        "unverified_statuses": sorted(unverified_statuses),
        "grounded": not unverified_numbers and not unverified_statuses,
    }


async def run_one_eval(client, server_params, spec: dict) -> dict:
    tool_log = []
    answer = await agent_client.run_agent_loop(
        spec["question"], client, server_params, tool_log=tool_log, verbose=False
    )
    grounding = check_grounding(answer, tool_log)

    result = {
        "id": spec["id"],
        "question": spec["question"],
        "trap": spec["trap"],
        "answer": answer,
        **grounding,
    }

    # A data question with zero tool calls is a failure regardless of
    # what the grounding-word check says, since there's no ground truth
    # to even check against — the absence of a tool call IS the finding.
    if spec.get("requires_tool_call") and grounding["tool_calls_made"] == 0:
        result["grounded"] = False
        result["failure_reason"] = "no_tool_called_for_a_data_question"

    return result


async def run_all_evals(client, server_params) -> list[dict]:
    results = []
    for spec in EVAL_QUESTIONS:
        results.append(await run_one_eval(client, server_params, spec))
    return results


def render_summary(results: list[dict]) -> str:
    lines = ["# Grounding Eval Results", ""]
    passed = sum(1 for r in results if r["grounded"])
    lines.append(f"{passed}/{len(results)} questions passed grounding.")
    lines.append("")
    for r in results:
        status = "PASS" if r["grounded"] else "FAIL"
        lines.append(f"## [{status}] {r['id']}{' (trap: ' + r['trap'] + ')' if r['trap'] else ''}")
        lines.append(f"Q: {r['question']}")
        lines.append(f"A: {r['answer']}")
        lines.append(f"Tool calls made: {r['tool_calls_made']}")
        if r.get("unverified_numbers"):
            lines.append(f"Unverified numbers in answer: {r['unverified_numbers']}")
        if r.get("unverified_statuses"):
            lines.append(f"Unverified status claims in answer: {r['unverified_statuses']}")
        if r.get("failure_reason"):
            lines.append(f"Failure reason: {r['failure_reason']}")
        lines.append("")
    return "\n".join(lines)


async def main_async():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ANTHROPIC_API_KEY not set. This script needs a live key to run.", file=sys.stderr)
        sys.exit(1)

    client = Anthropic(api_key=api_key)
    server_params = StdioServerParameters(
        command=sys.executable,
        args=[os.path.join(os.path.dirname(__file__), "mcp_server.py")],
        cwd=os.path.dirname(__file__),
    )

    results = await run_all_evals(client, server_params)
    summary = render_summary(results)
    print(summary)

    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "GROUNDING_EVAL_REPORT.md")
    with open(out_path, "w") as f:
        f.write(summary)
    print(f"\nReport written to {out_path}")

    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "grounding_eval_raw.json"), "w") as f:
        json.dump(results, f, indent=2)

    if any(not r["grounded"] for r in results):
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main_async())
