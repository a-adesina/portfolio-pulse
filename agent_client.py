"""
Portfolio Pulse — Agent Client
================================
The actual "pulls, analyses, generates insights" loop. This is the layer
that was deliberately kept separate from pulse_core.py's deterministic
interpretations, not a replacement for them.

The boundary, stated once here and enforced by the system prompt below:
Claude may synthesize, compare, and phrase answers conversationally. It
may NOT state a number, a status, or a flag that didn't come from an
actual tool call in this conversation. The system prompt makes this an
explicit instruction, not an assumption, and the tool results are the
only source of truth Claude is given, it has no other way to know
anything about these projects.

This connects to mcp_server.py as a real MCP client (not a hand-rolled
approximation), giving Claude the server's tools and letting Claude
decide which to call and when, the standard agent tool-use loop.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    python3 agent_client.py "What needs my attention this week?"
    python3 agent_client.py "Compare fastapi and flask"

REQUIRES a live Anthropic API key to run end-to-end against a real model,
this file's model-reasoning behavior has NOT been executed against a live
model in this build environment, no key was available here. The MCP
server side of this system (mcp_server.py) HAS been independently
verified with a real MCP client, see verification notes in README.md. Be
precise about that distinction if this comes up: the tool layer is
tested, this reasoning layer is written correctly against the documented
SDK APIs but its behavior has not been observed against a live model.

WHAT CHANGED since that was last written (see tests/test_agent_eval.py):
`run_agent` below is now a thin CLI wrapper around `run_agent_loop`, which
takes an injected `client` object instead of always constructing a real
`Anthropic()`. That's a pure refactor for testability, not a new claim —
it lets an eval harness drive the REAL tool-use loop against the REAL
mcp_server.py subprocess while substituting a scripted stand-in only for
the Anthropic call itself, since that's the one piece that genuinely
needs a live key. It does not change, and does not pretend to change,
the one fact stated above: no live model has driven this loop.
"""

import asyncio
import json
import os
import sys

from anthropic import Anthropic
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

SYSTEM_PROMPT = """You are a portfolio status assistant for Portfolio Pulse.

You have tools that return VERIFIED, already-computed data about tracked
software projects: delivery status, code health, ticket activity, and
budget position. Every fact in that data has already been checked, see
METHODOLOGY.md for how.

Hard rule, no exceptions: every specific claim you make, a number, a
status, a flag, a name, must come from a tool result in THIS conversation.
Never state a fact about a project from memory, assumption, or general
knowledge, you have none, these are private tracked projects you cannot
know anything about except through the tools. If you haven't called a
tool that would answer the question, call it before answering. If a tool
returns an error, report that plainly rather than guessing at an answer.

You may synthesize, compare across projects, and phrase things
conversationally, that's the value you add on top of the raw data. You
may not invent or round a number, or state a status you didn't actually
receive from a tool."""


MODEL_NAME = "claude-sonnet-4-6"
MAX_TOOL_ROUNDS = 6  # hard cap, never loop indefinitely


async def run_agent_loop(question: str, client, server_params, model: str = MODEL_NAME,
                          max_rounds: int = MAX_TOOL_ROUNDS, verbose: bool = True,
                          tool_log: list | None = None):
    """The actual tool-use loop, factored out so it can be driven by either
    a real Anthropic client (run_agent, below) or a scripted stand-in
    (tests/test_agent_eval.py). `server_params` and the MCP session are
    always real in both cases — only the model call is ever substituted.

    `tool_log`, if passed a list, gets one dict appended per real tool
    call: {"tool": name, "input": ..., "result": the real result text}.
    This is what grounding_eval.py reads as ground truth to check a live
    answer's claims against — added for that purpose, optional and
    additive, no change to existing callers that don't pass it."""
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            mcp_tools = await session.list_tools()
            # Convert MCP tool definitions to Anthropic's tool-use schema.
            # NOTE: the mcp SDK's Tool type exposes this as the snake_case
            # `input_schema` attribute (confirmed directly against the
            # installed SDK, mcp==2.3.0 at time of writing, via
            # `Tool.model_fields`), not the camelCase `inputSchema` an
            # earlier version of this file used. That earlier version was
            # written against MCP_VERIFICATION_LOG.md's verification run,
            # which really did confirm `inputSchema` on whatever SDK
            # version was installed at the time — the wire protocol's JSON
            # field is camelCase, but the Python SDK's own attribute name
            # for it isn't guaranteed to stay that way release to release.
            # This drift was caught by tests/test_agent_eval.py, which
            # spawns the real mcp_server.py and hits this exact line,
            # before any live model ever would have. See INCIDENT_LOG.md,
            # incident #5.
            claude_tools = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.input_schema,
                }
                for t in mcp_tools.tools
            ]

            messages = [{"role": "user", "content": question}]

            # Standard agent tool-use loop: call the model, if it wants a
            # tool, run it against the REAL MCP server and feed the real
            # result back, repeat until the model answers in plain text.
            for _ in range(max_rounds):
                response = client.messages.create(
                    model=model,
                    max_tokens=1024,
                    system=SYSTEM_PROMPT,
                    tools=claude_tools,
                    messages=messages,
                )

                if response.stop_reason != "tool_use":
                    final_text = "".join(
                        block.text for block in response.content if block.type == "text"
                    )
                    return final_text

                messages.append({"role": "assistant", "content": response.content})
                tool_results = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue
                    if verbose:
                        print(f"  [calling {block.name}({block.input})]", file=sys.stderr)
                    result = await session.call_tool(block.name, block.input)
                    # A tool returning a Python list (list_projects, with
                    # one row per project) comes back from the installed
                    # mcp SDK as ONE content block PER LIST ITEM, not one
                    # block holding the whole list. Reading only
                    # content[0] silently dropped every project but the
                    # first, a real correctness bug caught by
                    # tests/test_agent_eval.py (see INCIDENT_LOG.md,
                    # incident #6) before any live model ever would have.
                    # Joining every block's text is the fix: Claude reads
                    # this as plain text, not parsed JSON, so several
                    # JSON objects in sequence is a correct, readable
                    # tool result, not a malformed one.
                    if result.content:
                        result_text = "\n".join(
                            block_.text for block_ in result.content if hasattr(block_, "text")
                        )
                    else:
                        result_text = "{}"
                    if tool_log is not None:
                        tool_log.append({"tool": block.name, "input": block.input, "result": result_text})
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_text,
                        "is_error": result.is_error,
                    })
                messages.append({"role": "user", "content": tool_results})

            return "Agent did not reach a final answer within the call budget."


async def run_agent(question: str):
    """CLI entry point. Unchanged behavior: still requires a live
    ANTHROPIC_API_KEY, still constructs a real Anthropic client, still
    exits if neither is available. See run_agent_loop above for the part
    that's now shared with the eval harness."""
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
    return await run_agent_loop(question, client, server_params)


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "What needs my attention this week?"
    answer = asyncio.run(run_agent(q))
    print("\n" + answer)
