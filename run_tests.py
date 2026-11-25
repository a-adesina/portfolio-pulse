"""
Portfolio Pulse — Test Runner
================================
Runs the full test suite (tests/test_pulse_core.py, tests/test_github_pull.py,
tests/test_agent_eval.py, tests/test_pulse_alert.py), captures structured
results, and writes a timestamped TEST_REPORT.md, the same "run it, save
the real output, that saved output is the evidence" pattern as
verify_pull.py and the MCP verification log.

A skipped test is reported as skipped, with its reason, not folded into
"passed." That distinction is the point: this report should let someone
tell, at a glance, what was actually exercised this run versus what
depended on an external condition (GitHub's rate limit) that wasn't
available at the time.

Usage:
    python3 run_tests.py
"""

import io
import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def run_suite():
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromName("tests.test_pulse_core"))
    suite.addTests(loader.loadTestsFromName("tests.test_github_pull"))
    suite.addTests(loader.loadTestsFromName("tests.test_agent_eval"))
    suite.addTests(loader.loadTestsFromName("tests.test_pulse_alert"))
    suite.addTests(loader.loadTestsFromName("tests.test_grounding_eval"))
    suite.addTests(loader.loadTestsFromName("tests.test_pulse_scheduler"))

    buf = io.StringIO()
    runner = unittest.TextTestRunner(stream=buf, verbosity=2)
    result = runner.run(suite)
    return result, buf.getvalue()


def render_report(result, raw_output, generated_at):
    total = result.testsRun
    failed = len(result.failures)
    errored = len(result.errors)
    skipped = len(result.skipped)
    passed = total - failed - errored - skipped

    lines = [
        "# Test Report",
        "",
        f"Generated {generated_at} UTC. {total} tests run: "
        f"{passed} passed, {skipped} skipped, {failed} failed, {errored} errored.",
        "",
    ]

    if failed or errored:
        lines.append("**This run has failures or errors, do not treat the pipeline as verified until these are resolved.**")
    else:
        lines.append(
            "All executed tests passed. Skipped tests (if any) are listed below with "
            "their specific reason, they are not counted as passing and should not be "
            "read as such."
        )
    lines.append("")

    if result.skipped:
        lines.append("## Skipped, with reasons")
        lines.append("")
        for test, reason in result.skipped:
            lines.append(f"- `{test.id()}`: {reason}")
        lines.append("")

    if result.failures:
        lines.append("## Failures")
        lines.append("")
        for test, tb in result.failures:
            lines.append(f"### `{test.id()}`")
            lines.append("```")
            lines.append(tb.strip())
            lines.append("```")
            lines.append("")

    if result.errors:
        lines.append("## Errors")
        lines.append("")
        for test, tb in result.errors:
            lines.append(f"### `{test.id()}`")
            lines.append("```")
            lines.append(tb.strip())
            lines.append("```")
            lines.append("")

    lines.append("## Full run output")
    lines.append("")
    lines.append("```")
    lines.append(raw_output.strip())
    lines.append("```")

    return "\n".join(lines)


def main():
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    result, raw_output = run_suite()
    report = render_report(result, raw_output, generated_at)

    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "TEST_REPORT.md")
    with open(out_path, "w") as f:
        f.write(report)

    print(raw_output)
    print(f"\nReport written to {out_path}")

    # Non-zero exit on real failure/error, but NOT on skip, a skip is an
    # honest external condition, not a code problem.
    if result.failures or result.errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
