"""
Portfolio Pulse — Dashboard Renderer
=======================================
Renders the merged data (pulse_core.py) as a static HTML dashboard: a
portfolio-level headline, a compact triage table, and a written position
for every tracked project. The other of two renderers over the same
data; see generate_report.py for the markdown view.

"Refreshes per pull" means exactly this: a static snapshot regenerated
fresh every time the pipeline runs, not a live page polling a server.

Usage:
    python3 generate_dashboard.py
"""

import os
import sys
from datetime import datetime, timezone

import pulse_core

RISK_COLOR = {
    "critical": "#C1554A",
    "watch": "#D9A441",
    "clear": "#6FAE8C",
    "unknown": "#565C66",
}

CODE_HEALTH_COLOR = {
    "HEALTHY": "#6FAE8C",
    "BROKEN": "#C1554A",
    "STALE": "#D9A441",
    "ACTIVE (unmonitored)": "#4FB8AE",
    "ACTIVE (checks running)": "#4FB8AE",
    "NO DATA": "#565C66",
    "UNKNOWN": "#565C66",
}


def _fmt_num(v):
    return f"{v:,}" if isinstance(v, int) else "—"


def _fmt_days(days):
    return f"{days}d ago" if isinstance(days, int) else "—"


def _fmt_money(v):
    if not isinstance(v, (int, float)):
        return "—"
    sign = "+" if v > 0 else ""
    return f"{sign}${v:,.0f}"


def _fmt_tickets(opened, closed):
    if opened is None:
        return "—"
    return f"{opened}↑ / {closed}↓"


def render_row(r):
    color = RISK_COLOR[r["risk_tier"]]
    health_color = CODE_HEALTH_COLOR.get(r["code_health"], "#8B909B")
    return f"""
    <tr style="border-left-color:{color}">
      <td class="repo">{r['repo']}</td>
      <td><span class="pill" style="color:{health_color}">{r['code_health'].lower()}</span></td>
      <td class="num">{_fmt_days(r['days_since_commit'])}</td>
      <td class="num">{_fmt_tickets(r['tickets_opened'], r['tickets_closed'])}</td>
      <td>{r['budget_flag']}</td>
      <td class="num">{_fmt_money(r['variance'])}</td>
    </tr>"""


def render_position(r):
    color = RISK_COLOR[r["risk_tier"]]
    return f"""
    <div class="position" style="border-left-color:{color}">
      <div class="position-repo">{r['repo']}</div>
      <div class="position-text">{r['interpretation']}</div>
    </div>"""


def render_dashboard(rows, portfolio_position, generated_at, data_note):
    counts = {"critical": 0, "watch": 0, "clear": 0, "unknown": 0}
    for r in rows:
        counts[r["risk_tier"]] += 1

    summary_bits = []
    if counts["critical"]:
        summary_bits.append(f'<span class="stat"><span class="dot" style="background:{RISK_COLOR["critical"]}"></span>{counts["critical"]} critical</span>')
    if counts["watch"]:
        summary_bits.append(f'<span class="stat"><span class="dot" style="background:{RISK_COLOR["watch"]}"></span>{counts["watch"]} need a look</span>')
    if counts["clear"]:
        summary_bits.append(f'<span class="stat"><span class="dot" style="background:{RISK_COLOR["clear"]}"></span>{counts["clear"]} clear</span>')
    if counts["unknown"]:
        summary_bits.append(f'<span class="stat"><span class="dot" style="background:{RISK_COLOR["unknown"]}"></span>{counts["unknown"]} no data</span>')
    summary_html = "".join(summary_bits)

    rows_html = "\n".join(render_row(r) for r in rows)
    positions_html = "\n".join(render_position(r) for r in rows)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Portfolio Pulse</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600&family=IBM+Plex+Sans:wght@400;500&family=IBM+Plex+Mono:wght@400;500&display=swap');

  :root {{
    --bg: #14171C; --surface: #1B1F26; --border: #262B34;
    --text: #E7E4DE; --text-muted: #8B909B; --accent: #4FB8AE;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 48px 24px; background: var(--bg); color: var(--text);
    font-family: 'IBM Plex Sans', ui-sans-serif, system-ui, -apple-system, sans-serif;
    -webkit-font-smoothing: antialiased;
  }}
  .page {{ max-width: 920px; margin: 0 auto; }}
  header {{ display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 8px 24px; margin-bottom: 6px; }}
  h1 {{ font-family: 'Space Grotesk', ui-sans-serif, system-ui, sans-serif; font-weight: 600; font-size: 26px; letter-spacing: -0.01em; margin: 0; }}
  .generated {{ font-family: 'IBM Plex Mono', ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; color: var(--text-muted); white-space: nowrap; }}
  .tagline {{ color: var(--text-muted); font-size: 14px; margin: 0 0 24px 0; max-width: 68ch; }}

  .headline {{
    background: var(--surface); border: 1px solid var(--border); border-radius: 4px;
    padding: 18px 20px; margin-bottom: 24px; font-size: 14.5px; line-height: 1.6;
  }}
  .headline-label {{ font-family: 'Space Grotesk', sans-serif; font-size: 12px; letter-spacing: 0.02em; color: var(--accent); margin-bottom: 8px; }}

  .summary {{ display: flex; flex-wrap: wrap; gap: 6px 24px; font-size: 13.5px; margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid var(--border); }}
  .stat {{ display: inline-flex; align-items: center; white-space: nowrap; margin-right: 24px; }}
  .stat:last-child {{ margin-right: 0; }}
  .dot {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 7px; }}

  table {{ width: 100%; border-collapse: collapse; background: var(--surface); margin-bottom: 32px; }}
  thead th {{ text-align: left; font-weight: 500; font-size: 12.5px; color: var(--text-muted); padding: 10px 14px; border-bottom: 1px solid var(--border); }}
  thead th.num {{ text-align: right; }}
  tbody tr {{ border-left: 3px solid transparent; border-bottom: 1px solid var(--border); transition: background 0.12s ease; }}
  tbody tr:hover {{ background: rgba(255,255,255,0.03); }}
  tbody tr:last-child {{ border-bottom: none; }}
  td {{ padding: 12px 14px; font-size: 14px; }}
  td.repo {{ font-weight: 500; }}
  td.num {{ font-family: 'IBM Plex Mono', ui-monospace, SFMono-Regular, Menlo, monospace; text-align: right; font-size: 13px; }}
  .pill {{ font-size: 13px; font-weight: 500; }}

  .positions-label {{ font-family: 'Space Grotesk', sans-serif; font-size: 15px; font-weight: 600; margin-bottom: 12px; }}
  .position {{ background: var(--surface); border-left: 3px solid transparent; border-radius: 0 4px 4px 0; padding: 12px 16px; margin-bottom: 10px; }}
  .position-repo {{ font-weight: 500; font-size: 13.5px; margin-bottom: 4px; }}
  .position-text {{ font-size: 13.5px; color: var(--text-muted); line-height: 1.55; }}

  footer {{ margin-top: 24px; font-size: 12.5px; color: var(--text-muted); line-height: 1.6; }}

  @media (max-width: 640px) {{
    body {{ padding: 28px 16px; }}
    table {{ font-size: 13px; }}
    td, thead th {{ padding: 9px 8px; }}
  }}
</style>
</head>
<body>
  <div class="page">
    <header>
      <h1>Portfolio Pulse</h1>
      <div class="generated">generated {generated_at} UTC</div>
    </header>
    <p class="tagline">Delivery, CI, ticket, and budget signal pulled directly from source, not collected through status updates. {data_note}</p>

    <div class="headline">
      <div class="headline-label">Portfolio position</div>
      {portfolio_position}
    </div>

    <div class="summary">{summary_html}</div>

    <table>
      <thead>
        <tr>
          <th>Project</th>
          <th>Code health</th>
          <th class="num">Last commit</th>
          <th class="num">Tickets (30d)</th>
          <th>Budget</th>
          <th class="num">Spend vs. plan</th>
        </tr>
      </thead>
      <tbody>{rows_html}
      </tbody>
    </table>

    <div class="positions-label">Project positions</div>
    {positions_html}

    <footer>
      Delivery, CI, and ticket data pulled live from GitHub's API. Budget data is representative, see methodology.
      Regenerated fresh on every pipeline run, this file is a snapshot, not a live feed. Full parameter definitions and interpretation logic in METHODOLOGY.md.
    </footer>
  </div>
</body>
</html>"""


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

    data_note = ("Data below is a schema-accurate test fixture used to verify the render, "
                  "not a full live pull, see README.")

    html = render_dashboard(rows, portfolio_position, generated_at, data_note)

    out_path = os.path.join(base, "dashboard.html")
    with open(out_path, "w") as f:
        f.write(html)

    print(f"Dashboard written to {out_path}")


if __name__ == "__main__":
    main()
