# Methodology

The reference for "walk me through how this was built," not just what it
outputs. Every parameter below is a named constant in the code, not a
buried magic number, specifically so it can be pointed to and defended.

## Project selection (TRACKED_REPOS)

Five public repos, chosen deliberately for range rather than to look clean:

| Repo | Why it's in the set |
|---|---|
| tiangolo/fastapi | Very active — proves the pipeline reads a healthy, fast-moving project correctly |
| pallets/flask | Moderately active — a middle case, not either extreme |
| psf/requests | Mature, low-velocity — tests that "quiet" doesn't get misread as "broken" |
| github/gitignore | Config-only repo with a different activity shape (high issue count, low code churn) — tests the model against a project type that doesn't look like normal software delivery |
| octocat/Hello-World | Genuinely dormant — the one repo the staleness flag is *expected* to fire on |

The last one matters more than it looks: a demo that only shows healthy
green rows proves nothing about whether the staleness logic actually
works. Including a known-dormant repo and confirming it gets flagged is
what makes the flag itself credible.

In production, this list would come from an actual project registry, an
org's repo list via GitHub's organization API, or a PM tool's active-project
export, not a hardcoded array. The array exists here because this is a
demo of the mechanism, not a production deployment.

## Staleness (STALENESS_THRESHOLD_DAYS = 21)

**Calculation:** the default branch's actual last commit date, pulled via
the commits endpoint scoped to that branch specifically
(`/repos/{owner}/{repo}/commits?sha=<default_branch>`), flagged stale if
`now(UTC) - that date` exceeds the threshold.

**Why 21, not 14 or 30:** it's a midpoint. Short enough to catch a real
stall within a sprint-adjacent cadence before it's been quiet for over a
month. Long enough that a repo with a legitimately slower cadence, a
config repo, a maintenance-mode integration, doesn't get flagged every time
nobody happened to touch it that week.

**Where this is a placeholder, honestly:** one global threshold across every
project type is the simplification a demo can get away with and a real
deployment can't. A fast-moving feature build and a stable, maintenance-mode
integration don't share a sensible staleness definition. The parameter is
named and isolated specifically so it's the first thing to make
project-type-aware in a real version, not a constant to leave alone.

**Fixed, not just found: the original version used `repo.pushed_at`
instead.** That field reflects a push to *any* branch of the repo, not
specifically the default branch a staleness check actually cares about.
Running `verify_pull.py` against live data caught exactly this:
`tiangolo/fastapi` showed `pushed_at` as 4 days ago, but the default
branch's true last commit was 21 days ago, a push to some other branch
(a bot branch, a docs branch, a PR branch) had bumped the repo-level
timestamp without the mainline delivery actually moving. The dangerous
direction: it could call a genuinely stalled project "active" because
something, anything, got pushed somewhere in the repo. Fixed by querying
the default-branch-scoped commits endpoint instead, the same signal
`verify_pull.py` already checks against independently.

**A second, related bug found afterward, while adding input validation,
not while fixing the first one:** when the default-branch commit lookup
itself failed partway through a pull (a rate limit hit at exactly that
call, not the initial repo lookup), the old code let the resulting
`None` staleness value silently evaluate `is_stale` to `False`, again
reporting a project with zero real data as falsely "active." Fixed:
`pull_repo_status` now treats a failed commit lookup as a failed pull for
that repo entirely, the same honest "no data" path a 404 already took,
rather than a result that looks fine but rests on nothing. Full account
in `GAP_ANALYSIS.md` §6, with a permanent regression test guarding
against it recurring silently.

## Delivery velocity (PR_VELOCITY_WINDOW_DAYS = 30)

**Calculation:** pull closed PRs, keep only those with a non-null
`merged_at` within the window, count them.

**Two GitHub API quirks this has to account for, not just work around
silently:**

1. `/issues` returns pull requests as well as real issues, since GitHub's
   data model treats a PR as a kind of issue. Every object that's actually
   a PR carries a `pull_request` key; filtering on that key's presence is
   the only reliable way to get a clean open-issue count instead of an
   inflated one.
2. `/pulls?state=closed` returns PRs closed *without* merging, alongside
   ones that were merged. Only `merged_at` being non-null means real
   delivery happened; a closed-but-abandoned PR is explicitly excluded
   rather than silently counted as progress.

Both raw and filtered counts are kept in the output (see
`open_issues_total_field_includes_prs` in the pull results) so the
filtering step is verifiable, not just asserted.

**Why 30 days:** matches a standard monthly reporting cadence, and is short
enough that a project merging nothing in the window is a real signal worth
seeing, not noise from an arbitrary window size.

## Code health / CI status

**Calculation:** the latest commit on the default branch is checked two
ways, in order. First, the modern Checks API
(`/repos/{owner}/{repo}/commits/{sha}/check-runs`), what GitHub Actions
actually populates. If any check run's conclusion is `failure` or
`timed_out`, the result is `failure`. If none failed but some are still
`queued` or `in_progress`, the result is `pending`. If all completed
without failure, `success`. If there are no check runs at all, falls back
to the legacy combined-status API
(`/repos/{owner}/{repo}/commits/{sha}/status`), for repos still using an
older third-party CI integration. If neither returns anything, the result
is `no_ci_configured`, stated as its own honest state, not silently
folded into "success" or "unknown."

**Why check both APIs rather than one:** GitHub Actions-based repos
populate check-runs; older or third-party CI setups (a legacy Travis or
CircleCI integration) populate the legacy status API instead. Checking
only one would misread the other class of repo as having no CI at all
when it actually does, a real accuracy gap, not a hypothetical one.

**How this folds into `code_health`, the single combined read:**
`failure` in CI overrides everything else and reads as `BROKEN`, a
failing build is worth flagging even on a project with recent commits.
Otherwise, a stale project reads as `STALE` regardless of what its last
CI run said, a project can't be "healthy" if nobody's touched it in
weeks. Otherwise, `no_ci_configured` reads as `ACTIVE (unmonitored)`,
active commits with no automated way to know if they work, a distinct,
honest state, not treated as equivalent to a passing check. `pending`
and `success` read as `ACTIVE (checks running)` and `HEALTHY`
respectively.

**The real limit here, stated plainly:** this reads the state of the
*latest* commit only. A project with a long history of failures that
happens to pass its most recent check reads as healthy. A single
snapshot, not a trend, is a real simplification worth knowing about
before treating `HEALTHY` as a guarantee of anything beyond "the last
commit passed."

## Ticket / CR activity (TICKET_ACTIVITY_WINDOW_DAYS = 30, TICKET_BACKLOG_GROWTH_WATCH_THRESHOLD = 5)

**Calculation:** GitHub's issues endpoint is queried with `state=all` and
`since=<window start>`, then filtered client-side on the actual
`created_at` and `closed_at` fields, not trusted as returned. This
two-step approach is deliberate: GitHub's `since` parameter filters on
`updated_at`, not `created_at`, so a raw query would over-include items
that were merely commented on, not actually opened or closed, in the
window. The query fetches a superset; the precise count comes from
checking the real timestamps client-side.

**The same PR-filtering quirk as open issues, handled the same way:**
the issues endpoint returns pull requests too; anything carrying a
`pull_request` key is excluded before counting.

**A named, real limitation, not silently handled:** this reads a single
page, 100 items. Fine at this demo's scale, five repos with normal issue
volume. A genuinely high-traffic repo in a real deployment would need
pagination; that's not implemented here, and pretending otherwise would
be the same kind of unstated gap the original `pushed_at` bug was.

**Why 5 for the watch threshold:** net backlog growth (opened minus
closed) of 5 or more in one 30-day window is treated as worth a second
look. Like every other threshold here, this is a placeholder tuned for a
demo, not a number derived from any specific team's real ticket velocity,
the right number depends entirely on team size and normal churn for that
specific project.

## Budget variance (BUDGET_NEAR_LIMIT_PCT = 90)

**Calculation:** `variance = spent_to_date - planned_budget`. Positive
means over budget. `pct_utilized = spent / planned * 100`. Flagged "near
limit" at 90% utilized, "OVER" once variance is positive, "on track"
otherwise.

**Why 90%, not 100%:** the point of a near-limit flag is to surface the
signal before the line is actually crossed, while there's still time to
act. Flagging only at 100%+ tells you after the fact; 90% is a standard
early-warning default in budget-variance reporting.

**The real gap here, stated plainly:** this is a point-in-time comparison,
not a burn-rate calculation. It can't distinguish "40% spent at 40% of the
project timeline, exactly on pace" from "40% spent in week one of a
year-long project," which is a materially worse signal. A real version
needs spend-per-unit-time against elapsed project duration, not a static
snapshot. Noted here rather than fixed, because the honest position is
that this demo tests the join mechanism, not a finished budget model.

**What "budget" actually is in this demo:** representative figures in
`budget_data.csv`, because public repos have no real internal budget to
pull from. In a live deployment this column pulls from wherever spend
actually lives, a finance system's API, a budget-tracking sheet's API, the
same way delivery data pulls from GitHub: same join logic, different
source. Nothing about the merge or flagging logic changes when the source
changes; that's deliberate.

## Interpreting the output: what each signal implies, and where it can mislead

Pulling data directly instead of through people removes a layer of
friction and self-reporting bias. It does not remove the need for judgment
about what the data actually means. That distinction matters, because the
two get conflated easily, and conflating them is where a metrics system
does real damage rather than just looking incomplete.

**A "STALE" flag is a prompt to ask a question, not a verdict.** No push
in 21+ days is consistent with several very different real situations: a
genuinely stalled or blocked project, a feature-complete repo now correctly
sitting in low-touch maintenance mode, a team reassigned elsewhere, or work
that's actively happening somewhere the pull doesn't see, a private fork, a
design or planning phase, a dependency blocking a merge. The system's job
is to say where attention is warranted. A person still has to find out why
and decide what, if anything, to do about it. Treating the flag itself as
the answer is the same failure mode as trusting a stale structured field
over what a person actually said, just inverted, trusting an
automatically-generated field over what's actually happening on the
ground.

**"Active" is a volume signal, not a value signal, and that gap is real.**
PRs-merged-in-30-days counts events, not substance. Six merged PRs could be
six shipped features or six one-line dependency bumps and CI config tweaks;
this system can't currently tell the difference, since that requires
reading what changed, not just counting that something did. A project
showing strong velocity by this metric could still be behind on what
actually matters to the roadmap.

**If this becomes a known measurement, it will get gamed, and that's worth
naming before anyone else names it.** This is a predictable Goodhart's Law
risk, not a hypothetical one: if engineers know PR count is read as a
health signal, splitting genuine work into artificially small PRs to
inflate the count is a rational response to the incentive the system
creates. A metric that's useful while it's a quiet observation can stop
being useful the moment it becomes a target. Worth pairing any real
deployment with periodic sanity checks against PR size and content, not
just count.

**The budget flag's point-in-time limitation, restated as a decision risk
rather than just a calculation gap:** acting on "on track" too late, when
spend is actually front-loaded and about to spike, or treating "near
limit" as an automatic problem too early, when spend is legitimately
concentrated at the start of a project's lifecycle, are both real failure
modes of using this flag as a trigger rather than a prompt to check the
underlying spend pattern.

**What this kind of system should never be used for, stated as a hard
line, not a soft caveat:** attributing individual engineer performance
from commit or PR counts. That's a well-documented anti-pattern, since it
measures visibility and activity, not difficulty, quality, or contribution,
and it actively punishes people doing hard, slow-moving work while
rewarding high-frequency, low-stakes commits. Any real version of this
stays at the project level. Tracing it down to individuals turns a delivery
signal into a surveillance tool, and that changes how people behave around
it in ways that quietly corrupt the signal itself, which is the same
Goodhart's Law risk above, just aimed at people instead of process.

**The access-visibility question this raises isn't just technical.**
Direct, no-human-in-the-loop visibility into engineering activity carries a
trust dimension the architecture-and-security framing alone doesn't fully
cover. If the teams being observed sense the system is used to score them
rather than to surface where a leader's attention should go, that changes
their behavior around it, which degrades exactly the honest signal the
system exists to capture. A real deployment needs a stated purpose,
communicated to the people generating the data, not just an access-control
decision made above their heads.

## The dashboard as a second view, not a second system

`generate_dashboard.py` renders the exact same `pulse_core.build_rows()`
output the markdown report uses, nothing about the join, the staleness
calculation, or the budget flags is recalculated or redefined for the
visual view. The two renderers exist because a markdown table and a
color-coded, scannable dashboard serve different reading modes, a quick
terminal check versus something put in front of a stakeholder, not because
the underlying data or logic differs between them.

**Why static rather than a live-polling page:** the underlying data,
GitHub activity and budget figures, doesn't change on a timescale that
justifies a server, a polling loop, or live JavaScript API calls. A
plain, regenerated-per-pull HTML file has a real advantage a live page
doesn't: it cannot go stale silently. Either the visible generated
timestamp is current, or it visibly isn't. A live dashboard that quietly
stopped polling would look identical to one that's still working; this
can't.

**Why a single overall risk tier (`critical` / `watch` / `clear` /
`unknown`) exists alongside the individual delivery, code-health, ticket,
and budget flags:** it's a worst-of derivation, computed once in
`pulse_core.py`, used to drive the dashboard's color coding so a reviewer
can triage by glancing at the left border of each row before reading a
single cell. `critical` fires on a failing build OR spend over plan,
treated as equally urgent rather than ranked against each other. `watch`
fires on staleness, spend nearing its limit, or a fast-growing ticket
backlog. The underlying flags stay visible in their own columns and in
the written position too; the tier is a reading aid layered on top of the
real signal, not a replacement for it.

## The interpretation layer: how the written positions are built

Every project gets a written position, and so does the portfolio as a
whole, in `interpret_row()` and `interpret_portfolio()` in `pulse_core.py`.
Both are template functions, not a live AI call generating prose at
report time. That distinction is deliberate and worth being able to
explain precisely, not just assert.

**Why deterministic rather than AI-generated prose:** the whole point of
this build is that its signals are verifiable, named, and traceable back
to a specific field and a specific calculation. A live AI call writing
the "position" sentence at report-generation time would reintroduce
exactly the kind of unverified output this build exists to avoid, the
same category of error the vendor spend assessment caught and corrected
in an AI's classification output. A template reading already-computed
flags can't hallucinate a number that isn't there; an LLM asked to
"summarize the situation" could.

**How a row's position is actually assembled:** five clauses, each
conditional on already-computed flags, concatenated in a fixed order,
delivery status, code health, ticket trend, budget position, then a
final verdict clause driven by the risk tier. Nothing in any clause is
inferred beyond what's already in the row's own fields; the function is
closer to a mail-merge with real conditional logic than to a model
generating a summary.

**What this buys, concretely:** the same input always produces the same
sentence. If a written position is ever wrong, the fix is a specific
`if` branch in a specific function, inspectable and testable, not a
prompt to iterate on and hope generalizes. That's a stronger claim for a
reporting system a founder or executive is meant to trust than "the AI
wrote a summary and it read well."

**Where this could reasonably extend, and why that's a separate
concern:** an AI-generated narrative layer could sit on top of these
deterministic positions, the way a person writes an executive summary
from a set of verified figures, turning five structured sentences into a
more polished paragraph. That's a legitimate extension, but the
underlying figures and flags should stay deterministic regardless of
what writes the prose around them, the same separation of concerns as
"the numbers are audited, the cover memo is written."

## What this demo does not claim

- Not a claim of production-scale reliability. It was built and tested
  against five repos, not forty.
- Not a claim that 21 days, 30 days, 90%, or a backlog growth of 5 are the
  *correct* numbers for any real deployment, they are the defensible,
  documented starting parameters for one.
- Not a claim that budget tracking is solved. The point-in-time
  limitation above is real and unresolved.
- Not a claim that CI status proves code quality. It reads the latest
  commit's check result only, a snapshot, not a trend.
- Not a claim that ticket counts capture severity. A backlog of five
  minor issues and five critical ones look identical to this system;
  severity-weighting isn't implemented.
- Not a claim that the written positions are anything more than what
  they are: a deterministic reading of the same flags visible elsewhere
  in the report, not independent judgment.

What it does claim: the pull, filter, join, flag, and interpretation
logic all work, verified end to end, against a mix of live data and a
schema-accurate fixture where a live rate limit interrupted the full run,
and independently cross-checked by a second tool that caught and led to
fixing a real bug in the original staleness calculation. That is a
different, narrower, and more honest claim than "this works," and it's
the one this build can actually stand behind under questioning.
