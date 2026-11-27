"""
Portfolio Pulse — Core
========================
The load, merge, flag, and interpret logic shared by every rendered view
(markdown report, HTML dashboard, anything added later). Pull, merge, and
render are three separable concerns; only rendering should differ between
outputs. If the merge and interpretation logic lived twice, once per
renderer, a fix to one could silently drift from the other.

This version adds the interpretation layer: not just flags, but a
deterministic, templated position statement per project and for the
portfolio as a whole. "Deterministic" is a deliberate choice, not a
convenience — the interpretation is built entirely from the same named,
verified flags used elsewhere in this file, not a separate live AI call
generating prose at report time. That keeps the interpretation auditable
and reproducible: the same input data always produces the same reading,
and if a reading is wrong, the fix is in named logic here, not in an
opaque model call.

Nothing in this file talks to the network or writes a file. It only
transforms data that's already been pulled.
"""

# --- Tunable parameters, named explicitly so they can be defended in the room ---

BUDGET_NEAR_LIMIT_PCT = 90
# A project flips to "near limit" once spend reaches this percentage of its
# planned budget, before it actually goes over. Standard early-warning
# threshold in budget-variance reporting: surfaces the signal while there's
# still time to act, rather than only after the line is crossed.

TICKET_BACKLOG_GROWTH_WATCH_THRESHOLD = 5
# Net ticket growth (opened minus closed) in one tracking window past this
# count flags the project for a closer look. A placeholder like the others:
# the right number depends on team size and normal ticket velocity for that
# specific project, not a single global constant.

STALE_ARCHIVE_CANDIDATE_DAYS = 365
# A stale project (no default-branch commit past github_status_pull's
# STALENESS_THRESHOLD_DAYS) with no commit in more than a year is called out
# separately in the decisions list as an archive-or-retire question rather
# than a "check on it" question. Placeholder like the others: the right
# number is a judgement about the portfolio, not a fact about GitHub.

BACKLOG_NO_THROUGHPUT_OPEN_ISSUES = 25
# A project with at least this many open issues AND no merged PRs in the
# window is flagged as open work with no delivery against it. Both halves
# must hold: many open issues alone is normal for a busy project.


def _n(count, word):
    """'1 project', '2 projects'. Plain English instead of 'project(s)'."""
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def _are(count):
    return "is" if count == 1 else "are"


def load_github_results(path):
    import json
    with open(path) as f:
        return {r["repo"]: r for r in json.load(f)}


def load_budget_data(path):
    import csv
    budgets = {}
    with open(path) as f:
        for row in csv.DictReader(f):
            budgets[row["repo"]] = {
                "planned": float(row["planned_budget_usd"]),
                "spent": float(row["spent_to_date_usd"]),
                "notes": row["notes"],
            }
    return budgets


def _budget_fields(bg):
    if not bg:
        return None, None, None, "NO DATA"
    variance = bg["spent"] - bg["planned"]
    pct = (bg["spent"] / bg["planned"] * 100) if bg["planned"] else 0
    flag = "OVER" if variance > 0 else ("near limit" if pct >= BUDGET_NEAR_LIMIT_PCT else "on track")
    return bg["planned"], bg["spent"], variance, flag


def _code_health_flag(delivery_flag, ci_status):
    """One combined read of 'did the code function as expected,' folding
    staleness and CI outcome into a single honest state rather than two
    flags a reader has to reconcile themselves."""
    if ci_status == "failure":
        return "BROKEN"
    if delivery_flag == "STALE":
        return "STALE"
    if ci_status == "no_ci_configured":
        return "ACTIVE (unmonitored)"
    if ci_status == "pending":
        return "ACTIVE (checks running)"
    if ci_status == "success":
        return "HEALTHY"
    return "UNKNOWN"


def build_rows(github_data, budget_data, include_budget=True):
    """The one place every signal gets joined, flagged, and interpreted.
    Every renderer calls this rather than re-deriving any of it itself.

    include_budget=False ignores budget data entirely: the budget flag is
    "NOT TRACKED", spend plays no part in the risk tier, and the written
    positions say nothing about spend. Used when no real budget data
    exists, so a demo figure can never shape a reading."""
    rows = []
    if not include_budget:
        budget_data = {}
    all_repos = sorted(set(github_data.keys()) | set(budget_data.keys()))
    for repo in all_repos:
        gh = github_data.get(repo)
        bg = budget_data.get(repo)

        row = {"repo": repo}

        if gh:
            row["default_branch"] = gh.get("default_branch")
            row["open_issues"] = gh["open_issues"]
            row["prs_merged_30d"] = gh["prs_merged_last_30d"]
            row["days_since_commit"] = gh["days_since_last_commit"]
            row["delivery_flag"] = "STALE" if gh["stale"] else "active"
            row["ci_status"] = gh.get("ci_status", "unknown")
            row["tickets_opened"] = gh.get("tickets_opened_recent", 0)
            row["tickets_closed"] = gh.get("tickets_closed_recent", 0)
            row["ticket_net"] = row["tickets_opened"] - row["tickets_closed"]
            row["code_health"] = _code_health_flag(row["delivery_flag"], row["ci_status"])
        else:
            row["default_branch"] = None
            row["open_issues"] = row["prs_merged_30d"] = row["days_since_commit"] = None
            row["delivery_flag"] = "NO DATA (not pulled)"
            row["ci_status"] = "unknown"
            row["tickets_opened"] = row["tickets_closed"] = row["ticket_net"] = None
            row["code_health"] = "NO DATA"

        planned, spent, variance, budget_flag = _budget_fields(bg)
        if not include_budget:
            budget_flag = "NOT TRACKED"
        row["planned"], row["spent"], row["variance"], row["budget_flag"] = planned, spent, variance, budget_flag

        # Worst-of overall risk tier, now folding in CI failure (as urgent
        # as being over budget) and a fast-growing ticket backlog.
        if row["budget_flag"] == "OVER" or row["code_health"] == "BROKEN":
            row["risk_tier"] = "critical"
        elif (
            row["delivery_flag"] == "STALE"
            or row["budget_flag"] == "near limit"
            or (row["ticket_net"] is not None and row["ticket_net"] >= TICKET_BACKLOG_GROWTH_WATCH_THRESHOLD)
        ):
            row["risk_tier"] = "watch"
        elif row["delivery_flag"] == "NO DATA (not pulled)" or row["budget_flag"] == "NO DATA":
            row["risk_tier"] = "unknown"
        else:
            row["risk_tier"] = "clear"

        row["interpretation"] = interpret_row(row)
        rows.append(row)
    return rows


def interpret_row(row):
    """Deterministic, templated position statement for one project.
    Built entirely from flags already computed above, nothing new is
    inferred here that isn't traceable to a named field."""
    parts = []

    # Delivery clause
    if row["delivery_flag"] == "STALE":
        branch = row["default_branch"] or "the default branch"
        parts.append(f"{row['repo']} has gone quiet, {row['days_since_commit']} days since the last commit on {branch}.")
    elif row["delivery_flag"] == "active":
        parts.append(f"{row['repo']} is actively shipping, {_n(row['prs_merged_30d'], 'PR')} merged in the last 30 days.")
    else:
        parts.append(f"{row['repo']} has no delivery data for this cycle.")

    # Code health / CI clause
    ci = row["ci_status"]
    if ci == "failure":
        parts.append("The latest commit is currently failing its checks, this needs confirming before treating the project as healthy.")
    elif ci == "success":
        parts.append("The latest commit passed its checks.")
    elif ci == "pending":
        parts.append("Checks are still running on the latest commit.")
    elif ci == "no_ci_configured":
        parts.append("No CI is configured, so pass/fail status can't be verified automatically, only commit activity is visible.")

    # Ticket clause
    if row["tickets_opened"] is not None:
        opened, closed, net = row["tickets_opened"], row["tickets_closed"], row["ticket_net"]
        if net > 0:
            parts.append(f"The ticket backlog grew this cycle, {opened} opened against {closed} closed ({row['open_issues']} open in total).")
        elif net < 0:
            parts.append(f"The ticket backlog shrank this cycle, {closed} closed against {opened} opened ({row['open_issues']} open in total).")
        elif opened or closed:
            parts.append(f"Ticket flow was balanced this cycle, {opened} opened and {closed} closed ({row['open_issues']} open in total).")
        else:
            parts.append(f"No ticket activity this cycle ({row['open_issues']} open in total).")

    # Budget clause
    bf = row["budget_flag"]
    if bf == "NOT TRACKED":
        pass
    elif bf == "OVER":
        parts.append(f"Spend is over plan by ${row['variance']:,.0f}.")
    elif bf == "near limit":
        parts.append("Spend is approaching its budget limit.")
    elif bf == "on track":
        parts.append("Spend is on track against plan.")
    else:
        parts.append("No budget data available for this project.")

    # Position / verdict
    tier = row["risk_tier"]
    if tier == "critical":
        reason = "a failing build" if row["code_health"] == "BROKEN" else "spend over plan"
        parts.append(f"Position: needs immediate attention, {reason}.")
    elif tier == "watch":
        parts.append("Position: worth a closer look this cycle.")
    elif tier == "clear":
        parts.append("Position: no action needed.")
    else:
        parts.append("Position: insufficient data to assess.")

    return " ".join(parts)


def interpret_portfolio(rows):
    """Deterministic portfolio-level synthesis, same rule, built only from
    fields already computed per row, nothing newly inferred."""
    total = len(rows)
    active = sum(1 for r in rows if r["delivery_flag"] == "active")
    stale = sum(1 for r in rows if r["delivery_flag"] == "STALE")
    broken = sum(1 for r in rows if r["code_health"] == "BROKEN")
    unmonitored = sum(1 for r in rows if r["code_health"] == "ACTIVE (unmonitored)")

    total_opened = sum(r["tickets_opened"] or 0 for r in rows)
    total_closed = sum(r["tickets_closed"] or 0 for r in rows)
    net_tickets = total_opened - total_closed

    total_variance = sum(r["variance"] for r in rows if isinstance(r["variance"], (int, float)))
    over_budget_projects = [r["repo"] for r in rows if r["budget_flag"] == "OVER"]

    attention = [r["repo"] for r in rows if r["risk_tier"] in ("critical", "watch")]

    parts = []
    parts.append(f"Of {total} tracked projects, {active} are active and {stale} have gone stale.")
    if broken:
        parts.append(f"{_n(broken, 'project')} {_are(broken)} currently failing CI checks and {'needs' if broken == 1 else 'need'} immediate attention.")
    if unmonitored:
        parts.append(f"{_n(unmonitored, 'project')} {'has' if unmonitored == 1 else 'have'} no CI configured, commit activity is visible but pass/fail status isn't.")

    if net_tickets > 0:
        parts.append(f"Ticket backlog is growing portfolio-wide, {total_opened} opened against {total_closed} closed this cycle.")
    elif net_tickets < 0:
        parts.append(f"Ticket backlog is shrinking portfolio-wide, {total_closed} closed against {total_opened} opened this cycle.")
    else:
        parts.append(f"Ticket flow was balanced portfolio-wide this cycle, {total_opened} opened and {total_closed} closed.")

    if all(r["budget_flag"] == "NOT TRACKED" for r in rows) and rows:
        pass
    elif total_variance > 0:
        parts.append(f"Aggregate spend is over plan by ${total_variance:,.0f}, driven by {', '.join(over_budget_projects) if over_budget_projects else 'multiple projects'}.")
    elif total_variance < 0:
        parts.append(f"Aggregate spend is under plan by ${abs(total_variance):,.0f}.")
    else:
        parts.append("Aggregate spend is exactly on plan.")

    if attention:
        parts.append(f"{_n(len(attention), 'project')} {'requires' if len(attention) == 1 else 'require'} attention this cycle: {', '.join(attention)}.")
    else:
        parts.append("No projects currently require attention.")

    return " ".join(parts)


def load_and_merge(github_results_path, budget_csv_path=None):
    """Convenience entry point: load both sources and return merged rows.
    With no budget CSV, budget is not tracked at all (see build_rows)."""
    github_data = load_github_results(github_results_path)
    if budget_csv_path is None:
        return build_rows(github_data, {}, include_budget=False)
    budget_data = load_budget_data(budget_csv_path)
    return build_rows(github_data, budget_data)


def derive_decisions(rows):
    """Deterministic list of decisions the pulled signals put in front of
    an owner. Same rule as the position statements: every item is built
    from named fields and named thresholds in this file, so each one shows
    its evidence and a reader can check it against the table. Nothing here
    is predicted or scored. Ordered critical, then watch, then clear.

    Each item: severity, title, evidence (list of strings), decision,
    caveat (or None), repos."""
    items = []

    def _by_days(rs):
        return sorted(rs, key=lambda r: r["days_since_commit"] or 0, reverse=True)

    for r in rows:
        if r["code_health"] == "BROKEN":
            branch = r["default_branch"] or "the default branch"
            items.append({
                "severity": "critical",
                "title": f"Failing build on {r['repo']}",
                "evidence": [
                    f"The latest commit on {branch} fails its checks.",
                    f"{_n(r['days_since_commit'], 'day')} since that commit; "
                    f"{_n(r['prs_merged_30d'], 'PR')} merged in the last 30 days.",
                ],
                "decision": "Name an owner for the failing build, and decide whether merging continues while it stays red.",
                "caveat": "One failing run can be a flaky test or an outage. Confirm it persists before escalating.",
                "repos": [r["repo"]],
            })

    stale = [r for r in rows if r["delivery_flag"] == "STALE"]
    archive = _by_days([r for r in stale if (r["days_since_commit"] or 0) > STALE_ARCHIVE_CANDIDATE_DAYS])
    quiet = _by_days([r for r in stale if r not in archive])
    if quiet:
        items.append({
            "severity": "watch",
            "title": f"{_n(len(quiet), 'project')} gone quiet",
            "evidence": [f"{r['repo']}: {r['days_since_commit']} days since the last commit on {r['default_branch'] or 'the default branch'}." for r in quiet],
            "decision": "For each, confirm it is finished, dormant by design, or missing an owner, and record which.",
            "caveat": "A quiet project can be a stable one. The signal says nothing has landed, not that anything is wrong.",
            "repos": [r["repo"] for r in quiet],
        })
    if archive:
        items.append({
            "severity": "watch",
            "title": f"{_n(len(archive), 'project')} with no commit in over a year",
            "evidence": [f"{r['repo']}: {r['days_since_commit']:,} days since the last commit." for r in archive],
            "decision": "Decide whether to archive or retire each, and stop carrying it as live work.",
            "caveat": None,
            "repos": [r["repo"] for r in archive],
        })

    stuck = [r for r in rows if r["open_issues"] is not None
             and r["open_issues"] >= BACKLOG_NO_THROUGHPUT_OPEN_ISSUES and r["prs_merged_30d"] == 0]
    if stuck:
        items.append({
            "severity": "watch",
            "title": f"{_n(len(stuck), 'project')} with open work and no merges",
            "evidence": [
                f"{r['repo']}: {r['open_issues']} open issues, {r['tickets_opened']} opened against "
                f"{r['tickets_closed']} closed in the window, 0 PRs merged in 30 days."
                for r in stuck
            ],
            "decision": "Decide whether to fund triage and maintenance capacity for these, or formally close out what will not be done.",
            "caveat": None,
            "repos": [r["repo"] for r in stuck],
        })

    stuck_names = {r["repo"] for r in stuck}
    growing = [r for r in rows if r["ticket_net"] is not None
               and r["ticket_net"] >= TICKET_BACKLOG_GROWTH_WATCH_THRESHOLD
               and r["repo"] not in stuck_names]
    if growing:
        items.append({
            "severity": "watch",
            "title": f"{_n(len(growing), 'project')} with a growing backlog",
            "evidence": [f"{r['repo']}: {r['tickets_opened']} opened against {r['tickets_closed']} closed." for r in growing],
            "decision": "Decide whether the team has the capacity this work needs, or whether scope should move.",
            "caveat": None,
            "repos": [r["repo"] for r in growing],
        })

    nodata = [r for r in rows if r["delivery_flag"] == "NO DATA (not pulled)"]
    if nodata:
        items.append({
            "severity": "unknown",
            "title": f"{_n(len(nodata), 'project')} with no data this cycle",
            "evidence": [f"{r['repo']}: not pulled." for r in nodata],
            "decision": "Find out why the pull failed before reading anything into the rest of the table.",
            "caveat": None,
            "repos": [r["repo"] for r in nodata],
        })

    clear = [r for r in rows if r["risk_tier"] == "clear"]
    if clear:
        items.append({
            "severity": "clear",
            "title": f"{_n(len(clear), 'project')} {'needs' if len(clear) == 1 else 'need'} no action",
            "evidence": [f"{r['repo']}: active, checks passing, {_n(r['prs_merged_30d'], 'PR')} merged in 30 days, {_n(r['open_issues'], 'open issue')}." for r in clear],
            "decision": "None this cycle.",
            "caveat": None,
            "repos": [r["repo"] for r in clear],
        })

    return items
