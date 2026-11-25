# MCP Server Verification Log

What was actually tested, run for real, not asserted, before this was
called working.

## What was verified

A real MCP client (the official `mcp` SDK's `ClientSession`, not a
hand-rolled stand-in) connected to `mcp_server.py` over stdio and called
every tool:

1. **`list_projects()`** — returned all 5 tracked repos with risk tier
   and headline flags. Correct.
2. **`get_project_status('pallets/flask')`** — returned the full row,
   delivery, CI status, tickets, budget, and the deterministic
   interpretation text, byte-for-byte the same data `generate_report.py`
   and `generate_dashboard.py` produce from the same input, confirming
   the MCP layer adds no new computation, exactly as designed.
3. **`get_portfolio_summary()`** — returned the correct aggregate counts
   and portfolio-level position, matching the dashboard's headline.
4. **Error handling on an unknown repo** — this caught a real bug, not a
   hypothetical one, on the first run.

## The bug this caught, and the fix

First version of `get_project_status` raised a `ValueError` with a
specific, useful message (which repos ARE valid) when given an unknown
repo name. The real client run showed that message never actually reached
the caller, MCP's default exception handling sanitizes error details
before they cross to the client, for legitimate security reasons, an
unhandled exception could otherwise leak internal state. What arrived
client-side was a generic `"Error executing tool get_project_status"`,
useless to an agent trying to recover.

**Fix:** an unknown repo is an expected, foreseeable input condition, not
a bug, so it's now returned as a normal value (`{"error": ..., "known_repos":
[...]}`), not raised as an exception. Re-ran the same client call after
the fix: the specific, useful message now arrives intact.

This is the second time in this build that actually running verification
against real infrastructure, not just reading the code, caught something
that code review alone would have missed, the first was the `pushed_at`
staleness bug, see the main METHODOLOGY.md.

## What was NOT verified here

`agent_client.py`, the layer that actually calls Claude to reason over
these tools, has not been run end to end. No `ANTHROPIC_API_KEY` was
available in this build environment. What WAS checked without a live key:

- The file parses and imports cleanly
- Every Anthropic SDK type referenced (`ToolUseBlock` and its fields:
  `id`, `input`, `name`, `type`) was checked directly against the
  installed SDK's actual type definitions, not assumed from memory or
  from documentation that might be stale
- The MCP-to-Claude tool-schema conversion uses fields (`name`,
  `description`, `inputSchema`) confirmed present on the real tool
  objects returned by `list_tools()` in the verification run above

**The honest boundary:** the tool layer is tested against real
infrastructure. The reasoning loop on top of it is correctly written
against verified APIs, but its actual behavior when a live model calls
these tools, does it call the right tool for a given question, does it
ever paraphrase a number wrong, has not been observed. Say this precisely
if asked, "verified" and "written correctly but not yet run" are
different claims, and this system's whole discipline has been keeping
that distinction honest rather than letting it blur.
