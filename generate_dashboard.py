"""
Portfolio Pulse — Dashboard Renderer
=======================================
Renders the merged data (pulse_core.py) as a static HTML dashboard: a
portfolio-level headline, a compact triage table, and a written position
for every tracked project. The other of two renderers over the same
data; see generate_report.py for the markdown view.

"Refreshes per pull" means exactly this: a static snapshot regenerated
fresh every time the pipeline runs, not a live page polling a server.

This version shows delivery signal only (no spend: with no real budget data
the figures would be invented) and adds three things for a reader deciding
whether to trust and extend the tool: the decisions the data puts in front
of an owner (pulse_core.derive_decisions), the run record of the scheduler
that produced the data (pulse_health), and an explicit statement of what the
page is built on and what it leaves out.

Usage:
    python3 generate_dashboard.py
"""

import html
import os
import sys
from datetime import datetime, timezone

import pulse_core
import pulse_health
import pulse_log
import github_status_pull

SCOPE_NOTE = ("Demonstration portfolio: five public open-source repositories, "
              "pulled from GitHub's API. This is not data from any company's own projects.")

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
    return f"{days:,}d ago" if isinstance(days, int) else "—"


def _fmt_tickets(opened, closed):
    if opened is None:
        return "—"
    return f"{opened}↑ / {closed}↓"


def _fmt_ts(dt):
    return dt.strftime("%-d %b %H:%MZ") if dt else "—"


def _fmt_iso(ts):
    dt = pulse_health._parse_ts(ts)
    return _fmt_ts(dt)


def _e(v):
    return html.escape(str(v))


def render_row(r):
    color = RISK_COLOR[r["risk_tier"]]
    health_color = CODE_HEALTH_COLOR.get(r["code_health"], "#8B909B")
    return f"""
    <tr style="border-left-color:{color}">
      <td class="repo">{_e(r['repo'])}</td>
      <td><span class="pill" style="color:{health_color}">{_e(r['code_health'].lower())}</span></td>
      <td class="num">{_fmt_days(r['days_since_commit'])}</td>
      <td class="num">{_fmt_num(r['open_issues'])}</td>
      <td class="num">{_fmt_tickets(r['tickets_opened'], r['tickets_closed'])}</td>
      <td class="num">{_fmt_num(r['prs_merged_30d'])}</td>
    </tr>"""


def render_decision(d):
    color = RISK_COLOR.get(d["severity"], RISK_COLOR["unknown"])
    evidence = "".join(f"<li>{_e(x)}</li>" for x in d["evidence"])
    caveat = f'<div class="decision-caveat">{_e(d["caveat"])}</div>' if d.get("caveat") else ""
    return f"""
    <div class="decision" style="border-left-color:{color}">
      <div class="decision-title">{_e(d['title'])}</div>
      <ul class="decision-evidence">{evidence}</ul>
      <div class="decision-ask"><span class="decision-label">Decision</span> {_e(d['decision'])}</div>
      {caveat}
    </div>"""


def render_health(h):
    last = h["last_pull_at"]
    res = h["last_pull_result"]
    res_txt = f"{res['succeeded']} of {res['attempted']} repos" if res and res.get("attempted") is not None else "result not recorded"
    ld = h["last_decision"]
    pct = min(100, int(round(100 * h["pulls_in_window"] / h["cap"]))) if h["cap"] else 0

    chips = []
    for x in h["history"]:
        cls = "chip-pull" if x["pulled"] else "chip-skip"
        if x["note"]:
            cls = "chip-flag"
        trig = f' · {_e(x["trigger"])}' if x["trigger"] else ""
        chips.append(f'<span class="chip {cls}">{_fmt_iso(x["ts"])} {_e(x["label"])}{trig}</span>')
    chips_html = "".join(chips) or '<span class="muted">No decisions on record.</span>'

    notes = "".join(
        f'<div class="chip-note"><span class="mono">{_fmt_iso(x["ts"])}</span> {_e(x["note"])}</div>'
        for x in h["history"] if x["note"]
    )

    ld_txt = _e(ld["label"]) if ld else "—"
    ld_sub = ""
    if ld:
        ld_sub = f"{_fmt_iso(ld['ts'])}" + (f" · {_e(ld['trigger'])}" if ld["trigger"] else " · trigger not recorded")

    return f"""
    <div class="panel">
      <div class="panel-head"><span class="panel-title">Run record</span>
        <span class="muted">read from the committed run log, the same record the scheduler uses</span></div>
      <div class="facts">
        <div><div class="fact-label">Last pull</div><div class="fact-value">{_fmt_ts(last)}</div><div class="fact-sub">{_e(res_txt)}</div></div>
        <div><div class="fact-label">Pulls in last {h['window_hours']}h</div><div class="fact-value">{h['pulls_in_window']} of {h['cap']} allowed</div>
          <div class="bar"><div class="bar-fill" style="width:{pct}%"></div></div></div>
        <div><div class="fact-label">Next baseline pull due</div><div class="fact-value">{_fmt_ts(h['next_baseline_due'])}</div><div class="fact-sub">sooner only if a repo's code changes</div></div>
        <div><div class="fact-label">Last decision</div><div class="fact-value">{ld_txt}</div><div class="fact-sub">{ld_sub}</div></div>
      </div>
      <div class="fact-label" style="margin-top:14px">Decision history, oldest to newest ({len(h['history'])} of {h['total_decisions_on_record']} on record)</div>
      <div class="chips">{chips_html}</div>
      {notes}
    </div>"""


def render_position(r):
    color = RISK_COLOR[r["risk_tier"]]
    return f"""
    <div class="position" style="border-left-color:{color}">
      <div class="position-repo">{_e(r['repo'])}</div>
      <div class="position-text">{_e(r['interpretation'])}</div>
    </div>"""


def render_dashboard(rows, portfolio_position, decisions, health, generated_at, data_note):
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
    decisions_html = "\n".join(render_decision(d) for d in decisions) or '<div class="muted">No decisions to show.</div>'
    health_html = render_health(health)
    pulled = _fmt_ts(health["last_pull_at"])

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

  .scope {{ border: 1px solid var(--border); border-left: 3px solid var(--accent); border-radius: 0 4px 4px 0; padding: 10px 14px; font-size: 13.5px; color: var(--text-muted); margin-bottom: 20px; }}
  .section-label {{ font-family: 'Space Grotesk', sans-serif; font-size: 15px; font-weight: 600; margin: 8px 0 6px; }}
  .section-sub {{ font-size: 13px; color: var(--text-muted); margin: 0 0 12px; max-width: 72ch; }}
  .muted {{ color: var(--text-muted); font-size: 12.5px; }}
  .mono {{ font-family: 'IBM Plex Mono', ui-monospace, monospace; }}
  .decision {{ background: var(--surface); border-left: 3px solid transparent; border-radius: 0 4px 4px 0; padding: 12px 16px; margin-bottom: 10px; }}
  .decision-title {{ font-weight: 500; font-size: 14px; margin-bottom: 6px; }}
  .decision-evidence {{ margin: 0 0 8px 0; padding-left: 18px; font-size: 13px; color: var(--text-muted); line-height: 1.55; }}
  .decision-ask {{ font-size: 13.5px; line-height: 1.5; }}
  .decision-label {{ font-family: 'Space Grotesk', sans-serif; font-size: 11.5px; color: var(--accent); margin-right: 6px; text-transform: uppercase; letter-spacing: 0.04em; }}
  .decision-caveat {{ font-size: 12.5px; color: var(--text-muted); margin-top: 6px; font-style: italic; }}
  .panel {{ background: var(--surface); border: 1px solid var(--border); border-radius: 4px; padding: 16px 18px; margin-bottom: 32px; }}
  .panel-head {{ display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 4px 16px; margin-bottom: 12px; }}
  .panel-title {{ font-family: 'Space Grotesk', sans-serif; font-size: 15px; font-weight: 600; }}
  .facts {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 14px; }}
  .fact-label {{ font-size: 12px; color: var(--text-muted); }}
  .fact-value {{ font-size: 14.5px; margin-top: 2px; }}
  .fact-sub {{ font-size: 12px; color: var(--text-muted); margin-top: 2px; }}
  .bar {{ height: 6px; background: var(--border); border-radius: 3px; margin-top: 8px; }}
  .bar-fill {{ height: 6px; background: var(--accent); border-radius: 3px; }}
  .chips {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }}
  .chip {{ font-size: 11.5px; padding: 3px 9px; border-radius: 4px; font-family: 'IBM Plex Mono', ui-monospace, monospace; }}
  .chip-pull {{ background: rgba(79,184,174,0.16); color: #7FD6CC; }}
  .chip-skip {{ background: rgba(255,255,255,0.06); color: var(--text-muted); }}
  .chip-flag {{ background: rgba(217,164,65,0.18); color: #E8BF6A; }}
  .chip-note {{ font-size: 12.5px; color: var(--text-muted); margin-top: 8px; line-height: 1.5; }}
  .limits {{ background: var(--surface); border: 1px solid var(--border); border-radius: 4px; padding: 14px 18px; font-size: 13px; color: var(--text-muted); line-height: 1.6; }}
  .limits ul {{ margin: 6px 0 0 0; padding-left: 18px; }}
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
    <p class="tagline">Delivery, CI, and ticket signal pulled directly from source, not collected through status updates. Last pull {pulled}.</p>
    <div class="scope">{data_note}</div>

    <div class="headline">
      <div class="headline-label">Portfolio position</div>
      {_e(portfolio_position)}
    </div>

    <div class="summary">{summary_html}</div>

    <div class="section-label">Decisions this data supports</div>
    <p class="section-sub">Each item is built from the figures in the table below and shows its evidence. They are the questions an owner would need to answer, not predictions.</p>
    {decisions_html}

    <div class="section-label" style="margin-top:28px">Projects</div>
    <table>
      <thead>
        <tr>
          <th>Project</th>
          <th>Code health</th>
          <th class="num">Last commit</th>
          <th class="num">Open issues</th>
          <th class="num">Tickets, 30d</th>
          <th class="num">PRs merged, 30d</th>
        </tr>
      </thead>
      <tbody>{rows_html}
      </tbody>
    </table>

    {health_html}

    <div class="positions-label">Project positions</div>
    {positions_html}

    <div class="section-label" style="margin-top:28px">What this page is built on, and what it leaves out</div>
    <div class="limits">
      <ul>
        <li>Every figure comes from GitHub's API or from the scheduler's own run log. Nothing is estimated.</li>
        <li>No spend or budget figures: there is no real budget feed behind this demonstration, so none are shown.</li>
        <li>Activity signals, not effort or quality. A quiet repository can be a finished one; a red build can be a flaky test.</li>
        <li>"Stale" means no commit on the default branch for more than {github_status_pull.STALENESS_THRESHOLD_DAYS} days.</li>
        <li>Pull cadence: a baseline pull every {health['window_hours']} hours, an earlier pull only when a repository's code changes, never more than {health['cap']} in any rolling {health['window_hours']} hours.</li>
      </ul>
    </div>

    <footer>
      Generated {generated_at} UTC. A snapshot regenerated after each pull, not a live feed. Parameter definitions and interpretation logic are in METHODOLOGY.md.
    </footer>
  </div>
</body>
</html>"""


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    gh_path = os.path.join(base, "pull_results.json")

    if not os.path.exists(gh_path):
        print("No pull_results.json found. Run github_status_pull.py first.", file=sys.stderr)
        sys.exit(1)

    # No budget path on purpose: see the module docstring.
    rows = pulse_core.load_and_merge(gh_path)
    portfolio_position = pulse_core.interpret_portfolio(rows)
    decisions = pulse_core.derive_decisions(rows)

    now = datetime.now(timezone.utc)
    events = pulse_health.load_events(pulse_log.LOG_PATH)
    annotations = pulse_health.load_annotations(os.path.join(base, "decision_annotations.json"))
    health = pulse_health.summarize(events, now, annotations)

    generated_at = now.strftime("%Y-%m-%d %H:%M")
    html_out = render_dashboard(rows, portfolio_position, decisions, health, generated_at, SCOPE_NOTE)

    out_path = os.path.join(base, "dashboard.html")
    with open(out_path, "w") as f:
        f.write(html_out)

    print(f"Dashboard written to {out_path}")


if __name__ == "__main__":
    main()
