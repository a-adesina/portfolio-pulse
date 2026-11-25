"""
Portfolio Pulse — MCP Server
==============================
Exposes the SAME verified, already-computed data every other renderer
uses, as callable tools for an MCP client (an agent, Claude Desktop, or
any MCP-compatible caller). This is deliberately a thin layer: every tool
here reads fresh from pulse_core.load_and_merge() on every call and
returns exactly what's already there. No new computation happens in this
file, and no LLM call happens in this file either.

That boundary is the whole design decision, stated plainly:
  - The FACTS (delivery status, code health, ticket counts, budget
    position, the deterministic written position) are computed once, in
    pulse_core.py, verified, and unchanged by anything downstream.
  - What an agent adds on top, natural-language querying, comparison
    across projects, flexible synthesis, is a SEPARATE layer
    (agent_client.py) that calls these tools rather than generating facts
    itself. An agent can phrase an answer conversationally; it cannot
    invent a number this server didn't return.

Three tools, each mapped directly to something pulse_core already
computes and verifies:
  - list_projects()        quick portfolio-wide overview
  - get_project_status(repo)   full detail for one project
  - get_portfolio_summary()    the portfolio-level interpretation

Usage (stdio, the standard local pattern for Claude Desktop / Claude Code):
    python3 mcp_server.py

Requires a pull_results.json in this directory (real or fixture, same as
every other renderer). Reads fresh on every call, never caches, so it
can't silently serve stale data across a session.
"""

import os
import sys

from mcp.server.mcpserver import MCPServer
import pulse_core

BASE_DIR = os.path.dirname(__file__)
PULL_RESULTS_PATH = os.path.join(BASE_DIR, "pull_results.json")
BUDGET_PATH = os.path.join(BASE_DIR, "budget_data.csv")

server = MCPServer(
    name="portfolio-pulse",
    description=(
        "Verified project delivery, code health, ticket, and budget data "
        "pulled directly from source. Every fact returned by these tools "
        "traces back to a specific, named calculation in pulse_core.py, "
        "nothing here is generated or inferred by this server itself."
    ),
)


def _rows():
    """Fresh read on every call, deliberately, so a long-running agent
    session can never serve data from an earlier point in time without
    saying so."""
    if not os.path.exists(PULL_RESULTS_PATH):
        raise FileNotFoundError(
            f"No pull_results.json at {PULL_RESULTS_PATH}. "
            "Run github_status_pull.py first."
        )
    return pulse_core.load_and_merge(PULL_RESULTS_PATH, BUDGET_PATH)


@server.tool()
def list_projects() -> list[dict]:
    """List every tracked project with its risk tier and headline flags.
    Use this first for a broad question ("what's the state of things")
    before drilling into one project with get_project_status."""
    rows = _rows()
    return [
        {
            "repo": r["repo"],
            "risk_tier": r["risk_tier"],
            "code_health": r["code_health"],
            "budget_flag": r["budget_flag"],
        }
        for r in rows
    ]


@server.tool()
def get_project_status(repo: str) -> dict:
    """Full verified status for one project: delivery, code health,
    ticket activity, budget position, and the deterministic written
    position. `repo` must match an entry from list_projects (e.g.
    'tiangolo/fastapi')."""
    rows = _rows()
    for r in rows:
        if r["repo"] == repo:
            return r
    # An unknown repo is an expected, foreseeable input error, not a bug,
    # so it's returned as a normal value, not raised as an exception.
    # MCP's default exception handling sanitizes error messages before
    # they reach the client for security reasons, a raised ValueError
    # here would reach the calling agent only as a generic "error
    # executing tool" string, losing the specific, useful detail an
    # agent actually needs to recover (which repos ARE valid). Returning
    # a structured value instead means the real message survives.
    known = [r["repo"] for r in rows]
    return {"error": f"'{repo}' is not a tracked project.", "known_repos": known}


@server.tool()
def get_portfolio_summary() -> dict:
    """The portfolio-wide written position and aggregate counts, the same
    synthesis used in the dashboard's headline. Use this for a single
    overall read before deciding whether to drill into individual
    projects."""
    rows = _rows()
    return {
        "position": pulse_core.interpret_portfolio(rows),
        "project_count": len(rows),
        "risk_tier_counts": {
            tier: sum(1 for r in rows if r["risk_tier"] == tier)
            for tier in ("critical", "watch", "clear", "unknown")
        },
    }


if __name__ == "__main__":
    server.run(transport="stdio")
