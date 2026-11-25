"""
Portfolio Pulse — Markdown Report Renderer
=============================================
Renders the merged data (see pulse_core.py) as a plain markdown report:
a compact status table plus a written position for every project and for
the portfolio as a whole. One of two renderers over the same data; see
generate_dashboard.py for the visual view.

Usage:
    python3 generate_report.py
"""

import os
import sys
from datetime import datetime, timezone

import pulse_core


def render_markdown(rows, portfolio_position, generated_at):
    lines = []
    lines.append("# Portfolio Pulse — Status Report")
    lines.append(f"\nGenerated {generated_at} UTC. Delivery, CI, and ticket data pulled live from "
                  "GitHub's API. Budget data is representative (see pulse_core.py docstring).\n")

    lines.append("## Portfolio position\n")
    lines.append(portfolio_position + "\n")

    lines.append("## At a glance\n")
    lines.append("| Project | Code health | Tickets (30d) | Budget |")
    lines.append("|---|---|---|---|")
    for r in rows:
        tickets = (f"{r['tickets_opened']} opened / {r['tickets_closed']} closed"
                   if r["tickets_opened"] is not None else "n/a")
        lines.append(f"| {r['repo']} | {r['code_health']} | {tickets} | {r['budget_flag']} |")

    lines.append("\n## Project positions\n")
    for r in rows:
        lines.append(f"**{r['repo']}** — {r['interpretation']}\n")

    return "\n".join(lines)


def main():
    base = os.path.dirname(__file__)
    gh_path = os.path.join(base, "pull_results.json")
    budget_path = os.path.join(base, "budget_data.csv")

    if not os.path.exists(gh_path):
        print("No pull_results.json found. Run github_status_pull.py first.", file=sys.stderr)
        sys.exit(1)

    rows = pulse_core.load_and_merge(gh_path, budget_path)
    portfolio_position = pulse_core.interpret_portfolio(rows)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    report = render_markdown(rows, portfolio_position, generated_at)

    out_path = os.path.join(base, "status_report.md")
    with open(out_path, "w") as f:
        f.write(report)

    print(report)
    print(f"\n\nWritten to {out_path}")


if __name__ == "__main__":
    main()
