# Portfolio Pulse

A working prototype of a direct, no-human-in-the-loop portfolio reporting
system: delivery signal, code health, ticket activity, and budget position
all pulled from source, joined, and interpreted into a written position
for every project and for the portfolio as a whole. Built to answer,
concretely, "have you personally connected systems rather than collected
status through people," and to go one step further: not just data, but
the same kind of interpretation a reporting consumer actually needs,
active or stale, code that's working or catching errors, tickets raised
and resolved, spend against plan, with a stated position at every level.

## What it reports, per project and portfolio-wide

- **Active or stale** — commit activity on the actual default branch,
  not just "something got pushed somewhere" (see the fix note below)
- **Code health** — did the latest commit pass its checks, fail, or is
  there no CI configured to know either way
- **Tickets/CRs raised and resolved** — issues opened and closed in the
  tracking window, with the net backlog trend
- **Budget position** — spend against plan, with variance
- **A written position at every level** — not just flags, a deterministic,
  templated sentence-by-sentence read of what the combination of signals
  means for that project, plus one for the whole tracked portfolio

## Pipeline

```
github_status_pull.py  →  pulse_core.py              →  generate_report.py
(pulls: commits, CI        (loads, joins, flags,          (renders markdown)
 checks, issues, PRs)       interprets — single         →  generate_dashboard.py
                            source of truth)                (renders HTML)
                                                        →  verify_pull.py
                                                            (independent check)
```

`pulse_core.py` is the only place every signal gets joined, flagged, and
turned into a written position. Every renderer calls it rather than
re-deriving any of that itself, so the markdown report, the dashboard, and
the verifier's expectations can never quietly drift apart from each other.

## The fix: staleness now reads the right signal

The original version used the repo object's `pushed_at` field for
staleness. That field reflects a push to *any* branch of the repo, so a
bot branch, a docs branch, or a stray PR branch getting touched could make
a genuinely stalled project look active. This was caught by actually
running `verify_pull.py`'s independent check against real data, not
found by inspection, `tiangolo/fastapi` showed `pushed_at` as 4 days ago
while its default branch's true last commit was 21 days ago.

Fixed: `github_status_pull.py` now queries the commits endpoint scoped to
the repo's actual default branch, the same signal `git log` on that
branch would show. `verify_pull.py`'s role shifted accordingly, it now
checks the same corrected signal via a genuinely independent method (git
protocol vs. REST API) rather than catching the wrong-field bug it
originally found. See `METHODOLOGY.md` for the full account.

## What's real and what isn't, stated plainly

- **Delivery, CI, and ticket signal is live and real.**
  `github_status_pull.py` calls GitHub's API directly for all of it. No
  form, no self-report, no manual input.
- **`pull_results_PRE_FIX_LIVE_partial.json` is a historical artifact**,
  one row of genuinely live data (`tiangolo/fastapi`) pulled under the
  OLD, buggy `pushed_at` logic, before the fix. Kept deliberately rather
  than deleted, it's the actual evidence the bug was real, not a
  reconstruction.
- **`fixture_for_testing.json` is a schema-accurate test fixture** under
  the CURRENT, fixed schema, used to prove the merge, interpretation,
  report, dashboard, and verification logic all work end to end. Three of
  its five rows use real observed commit dates (confirmed via `git log`);
  two use fabricated dates specifically so the verifier has something
  real to catch, see `verification_report_FIXTURE_TEST.md` for the
  results. Not live data, and labeled as such everywhere it appears.
- **`pull_results.json` in the repository is a live pull.** Since 25 Nov
  2026 the `unattended-pull` job has pulled five public repositories
  (`tiangolo/fastapi`, `pallets/flask`, `psf/requests`, `github/gitignore`,
  `octocat/Hello-World`) from GitHub's API under the current pipeline and
  committed the result. Those are the numbers the delivery dashboard
  shows. They are public open-source projects used as a stand-in
  portfolio, not any organisation's own projects.
- **Budget data is representative**, per the docstring in `pulse_core.py`.
  Public open-source repos have no real internal budget to pull from. In
  a real deployment, this column would pull from wherever spend actually
  lives, a finance system's API or a budget-tracking sheet's API, the same
  way delivery data pulls from GitHub, rather than being hand-maintained.
  The delivery dashboard no longer shows spend at all (see below);
  `generate_report.py` and the MCP server still join the representative
  budget file.
- **Interpretations are deterministic, not a live AI call.** Every
  written position, per-project and portfolio-wide, is built from
  templated logic reading the same named, verified flags used everywhere
  else in this file. Same input always produces the same reading, and if
  a reading is wrong, the fix is in named logic in `pulse_core.py`, not
  in an opaque model call generating prose at report time.

## Running a full live pull

```bash
export GITHUB_TOKEN=ghp_xxxxxxxxxxxx   # personal access token, read-only scope is enough
python3 github_status_pull.py           # writes pull_results.json
python3 generate_report.py              # writes status_report.md
python3 generate_dashboard.py           # writes dashboard.html
```

Each repo now costs 4-6 API calls (repo info, default-branch commit, CI
check-runs, a legacy-status fallback, issue activity), not 3, so the
unauthenticated ceiling covers roughly 10 repos per hour, not more. An
authenticated token raises that to 5,000/hour, which is what makes this
viable at the scale the target role actually described, 40-50 concurrent
projects.

## Verifying a pull without a live demonstration

`verify_pull.py` answers a specific practical need: confirming the pull
is correct without gambling on a live re-run working in the room,
especially given the rate limit has genuinely failed multiple times
during this build already.

It cross-checks each repo's recorded last-commit signal against an
independent source, `git clone --depth 1` against github.com's git
protocol directly, not the api.github.com REST endpoint the main pull
uses. Different rate-limit pool entirely, so this check works even when
the main pull can't run, and it's a genuinely different code path reading
the same fact, not the same call run twice.

```bash
python3 verify_pull.py    # reads pull_results.json, writes verification_report.md
```

Run this once, ahead of time, save the report. A saved, dated
verification report is stronger evidence than a live demo anyway, a live
demo only proves it worked once, in a favorable moment; a saved report
shows exactly what correct and incorrect look like, side by side, and
in this case, it's the actual artifact that caught the `pushed_at` bug.

## The dashboard, and what "refreshes per pull" actually means

`dashboard.html` is a static file, not a live page polling a server. It
has zero JavaScript API calls and no backend. "Refreshes per pull" means
exactly what the pipeline diagram above shows: run a new pull, run
`generate_dashboard.py` again, the old file is fully overwritten with the
new data. That's deliberate, GitHub activity, CI results, ticket counts,
and budget figures don't change fast enough to justify live polling, and
a plain regenerated file can't go stale silently: it's either freshly
regenerated or the visible timestamp says it isn't.

The dashboard is structured the way a real status report is, so a reader
can stop at whichever depth they need: a portfolio-level position, then
**the decisions the data supports** (each shows its evidence and, where it
applies, a caveat; built by `pulse_core.derive_decisions` from named
fields and thresholds, not predicted), then a project table (code health,
last commit, open issues, tickets opened and closed, PRs merged), then a
**run record** (last pull, pulls against the cap of 3, next baseline pull
due, recent scheduler decisions with what triggered each), then a written
position per project, then a plain statement of what the page leaves out.

- **No spend.** There is no real budget feed behind the demonstration, so
  the dashboard shows none rather than a representative figure.
- **The run record reads the scheduler's own log**, the same
  `pulse_run_log.jsonl` the cap and baseline read, through
  `pulse_health.py`. A decision is annotated only where a person has
  written a note for its exact timestamp in `decision_annotations.json`;
  nothing is inferred. Decisions logged before the `trigger` field existed
  show "trigger not recorded".
- **Where it lives.** `dashboard.html` is generated by the
  `unattended-pull` job on each tick that pulls, and uploaded as a run
  artifact (Actions, open the run, Artifacts). It is not committed to the
  repository. A tick that decides not to pull builds no dashboard.
- **Not yet observed:** the CI-built version. No pull has run since this
  version was added; the version reviewed was rendered in the build
  sandbox from the hosted data.

`sample_dashboard_FIXTURE_TEST.html` is the older fixture-based render,
kept as the artifact that proved the original renderer.

## Why the rate-limit failure is worth keeping in the story, not hiding

This is a real, demonstrable instance of the exact tradeoff worth naming
in an interview: unauthenticated, broad access doesn't scale past a
handful of calls. Production use needs a token and a defined access
boundary, read-only scope, rate limits sized to actual concurrency,
rather than open querying against live systems. That's the architecture
and security consideration that stayed unvoiced in an earlier interview.
This build produced direct, first-hand evidence of exactly why it matters,
twice over now, once on the original pull, once again with the richer
pull's higher per-repo call count.

## The MCP / agent layer

`mcp_server.py` exposes the same verified `pulse_core` data as callable
tools, `list_projects`, `get_project_status`, `get_portfolio_summary`,
over the standard MCP stdio transport. `agent_client.py` is a real agent
loop, Claude reasons over natural-language questions by calling those
tools, using the official MCP client and Anthropic SDKs, not a simulated
version of either.

**The design boundary, the whole point of building it this way:** the
deterministic interpretation layer in `pulse_core.py` stays exactly as it
was, unchanged, the source of every fact. The agent adds flexible
natural-language querying and synthesis on top, it cannot invent a number
that didn't come from an actual tool call, that rule is enforced in
`agent_client.py`'s system prompt, not just hoped for.

```bash
python3 mcp_server.py                          # runs the MCP server (stdio)
export ANTHROPIC_API_KEY=sk-ant-...
python3 agent_client.py "What needs my attention this week?"
```

**What's verified and what isn't, the same discipline as everywhere else
in this build:** the MCP server was tested end to end with a real MCP
client, every tool called, real output confirmed, and one real bug caught
and fixed in the process, error messages were being silently sanitized
before reaching the caller. Full account in `MCP_VERIFICATION_LOG.md`.
The agent layer, the part that actually calls Claude, has not been run
end to end, no API key was available in this build environment. Its code
was checked against the real, installed SDK's actual type definitions
rather than assumed, but its live behavior is untested. That's a real,
stated limit, not a hedge.

## Testing, including edge and negative cases

`run_tests.py` runs the full suite and writes a timestamped
`TEST_REPORT.md`, the same "run it, save the real output" pattern as
`verify_pull.py`.

```bash
python3 run_tests.py
```

Three tiers, deliberately not all live:
- **Pure logic** (`tests/test_pulse_core.py`), boundary conditions
  (budget exactly at 90%, exactly 100%, a zero-planned-budget divide
  guard), missing-data combinations, and priority ordering when multiple
  critical conditions fire at once (a project that's both over budget AND
  has a failing build reads as "a failing build," proven, not assumed).
- **Mocked negative cases** (`tests/test_github_pull.py`), a 404, a
  rate-limit response, empty CI data, deliberately faked at the HTTP
  layer so these run deterministically regardless of GitHub's actual rate
  limit at the moment. Reproducing a real 404 on demand from a live
  service isn't practical; mocking it here is the correct engineering
  call, not a shortcut.
- **Live integration tests against real repos**, for the specific edge
  cases real repos can actually provide, a genuinely nonexistent repo, a
  repo with no CI configured, a genuinely dormant repo. These skip with an
  explicit, honest reason if the rate limit is exhausted when they run,
  rather than reporting a false pass or fail. At the time this was built,
  all three skipped for exactly that reason, see `TEST_REPORT.md` for the
  actual run.

34 tests total, 31 passed, 3 honestly skipped, 0 failed, at last run.

**Since then: retry logic, input validation, and CI wiring were added**
(scoped narrowly, see `GAP_ANALYSIS.md` §6 for exactly what and why),
which is also how a real, fourth-and-fifth finding turned up, a partial
API failure could previously make a genuinely dead project silently
report as active, and the live test suite itself had a quota-check race
condition. Both fixed, both now regression-tested. That was 45 tests at
the time. The suite is now 127: 125 pass and 2 live-network tests skip in
the build sandbox, 0 fail (`TEST_REPORT.md`).

**CI:** `.github/workflows/tests.yml` runs the suite on every push and
PR across Python 3.10-3.12, using the Actions-provided token so the live
integration tests get a real shot at running rather than always
skipping. It has now run in a real hosted GitHub Actions environment (the
public repository, from 25 Nov 2026). The first run was red on all three
Python versions because of a defect in one live test (`INCIDENT_LOG.md`
addendum A); after the fix the runs are green on 3.10, 3.11 and 3.12. It
also carries the `unattended-pull` job described below.

## The SOW

`SOW.md` scopes this build the way a real engagement would be scoped,
objectives, phased deliverables, acceptance criteria tied to specific
verifiable artifacts, and an explicit out-of-scope section rather than
letting gaps get discovered later. Worth reading before describing this
project's boundaries from memory.

## The gap analysis

`GAP_ANALYSIS.md` is the honest next step past the SOW: what this build
does not yet claim against production standards at real scale, security,
architecture, reliability, observability, and testing maturity,
severity-ranked (P0/P1/P2) and sequenced into a five-phase remediation
roadmap. Security comes first in that sequence without exception,
nothing else is worth building on top of a system that isn't yet safe to
point at real data. Worth reading before describing this project's
production-readiness from memory, same as the SOW for its scope.

## Maturity assessment, incident history, and what's past "bug fixes"

Three documents track this project against an external 7-tier AI-maturity
framework and record what actually went wrong, separated by WHEN it went
wrong:

- **`MATURITY_ASSESSMENT.md`** maps every tier to a specific artifact, no
  tier rounded up past what's actually proven. Headline: Tier 3 on the
  agent path, Tier 4 on the data path, not yet a clean Tier 4. Includes
  "Path to a clean Tier 4," "Path to Tier 5," and an explanation of why
  Tier 6 isn't reachable by a solo project at all.
- **`INCIDENT_LOG.md`** is the defect history: ten real bugs caught by
  actually running something (six at build time, numbered #1 to #6, and
  four in the first hosted days, lettered A, B, D and F), each with a fix and
  a permanent regression test. Five further gaps found by reading or
  reasoning are recorded separately and not counted.
- **`OPERATIONAL_INCIDENTS.md`** is kept separate from the build-time log:
  incidents that happen once this runs unattended. It has two entries, both
  found by the owner reading the scheduler's decision log, not by an alert.
  Conflating the two files would overclaim what either one is.

Also added toward Tier 5: `pulse_log.py` (structured run/repo logging),
`pulse_alert.py` (alerts on a crashed, failed, or repeatedly degraded
run), and `grounding_eval.py` (checks a live agent's answer against the
real tool output from that run — distinct from `tests/test_agent_eval.py`'s
scaffolding eval, which needs no live model and proves something
different). None of the three has fired against a real webhook or a real model
yet; that's stated in each file's own docstring, not just here.

`pulse_scheduler.py` is a priority-aware pull scheduler built to the
user's own corrected spec: a 24-hour baseline pull cadence, an earlier
pull only when a tracked repo's newest commit SHA differs from the one
saved on the previous tick, and a hard ceiling of 3 pulls per rolling 24
hours regardless of trigger. `.github/workflows/tests.yml`'s
`unattended-pull` job calls it instead of pulling unconditionally, and
persists its state (`pulse_run_log.jsonl`, `etag_cache.json`, which now
holds commit SHAs and kept its name) back to the repo after every tick.
Without that, every scheduled run would start from an empty log and decide
"pull" by default, silently defeating the cadence. Every decision records
what triggered the run (`schedule`, `workflow_dispatch`, `local`).

**What has been observed, as of 27 Nov 2026, and what has not:**

| Observed in the hosted repository | Not yet observed |
|---|---|
| Tests green on Python 3.10, 3.11, 3.12 | A scheduled tick performing the baseline pull |
| 5 of 5 tracked repos pulled live; state persisting between separate runs | A real commit causing an early pull (unit-tested only) |
| A manual run deciding `baseline_due` correctly after 27.4h | `pulse_alert.py` firing, or a webhook delivering |
| Three quiet ticks under the SHA check, no false changes | A live model running `agent_client.py` |
| A scheduled run executing and recording `"trigger": "schedule"` (27 Nov 17:48Z) | Weeks of unattended running |

Two things went wrong on the way, both visible in the log and kept on the
dashboard on purpose: an early pull because the first check of each repo
was read as a change (25 Nov), and an early pull because the commit-list
ETag changed with no new commit (26 Nov); the second is why the check now
compares commit SHAs. Scheduled ticks have also not landed on the cron
slots (00:00, 08:00, 16:00 UTC); the 17:48Z tick started about 1 hour 48
minutes after the 16:00Z slot. The reason is not established. The scheduler
has 32 tests, network stubbed.

## The project status dashboard

`generate_project_status.py` produces `project_status_dashboard.html`, a
different subject from `dashboard.html`, deliberately: that dashboard
reports on the repos Portfolio Pulse tracks, this one reports on
Portfolio Pulse itself, as an engagement, using the same reporting
discipline reflexively.

```bash
python3 generate_project_status.py
```

Three sections: a SOW scope-vs-outcome-vs-current-state table with a
resource/spend note and a decision per phase, a plain-language summary of
what each tested unit of code actually does and what its tests prove
(for a reader who wants to understand the system, not just see a pass
count), and a decision-support insights section, observations, blockers,
recommendations.

**On "spend," stated plainly:** this is a personal build with no assigned
monetary budget, so no dollar figure appears here, inventing one would
break the same no-fabricated-numbers rule the rest of this project holds
to. The real, recurring, measurable resource consumed was GitHub API
quota, exhausted at multiple points across this build, reported as the
honest spend analogue, with the actual resourcing decision that follows
from it, acquire a token.

**This page's content is authored, not generated by `pulse_core`**, the
same way `SOW.md` is authored. That's a deliberate, stated distinction in
the page itself: the deterministic-generation discipline applies to
claims about the many tracked repos pulled from a live source, not to
one-time project-governance narrative about a single, non-repeating
build.

## Extending this

- Swap `TRACKED_REPOS` for real project repos once a token is set.
- Swap the budget CSV for a real spend-tracking API call, same interface,
  no renderer cares where `pulse_core`'s dict comes from.
- Issue activity currently reads one page (100 items); a genuinely
  high-traffic repo would need pagination in production, noted as a real
  limitation in `METHODOLOGY.md`, not silently handled.
- An AI-generated narrative layer could sit on top of the deterministic
  interpretations, the way a person writes an executive summary from
  verified figures, but the underlying figures and flags should stay
  deterministic and auditable regardless of what writes the prose around
  them.

## Design parameters and methodology

Every threshold in this build, why it's set where it is, which are
demo-appropriate placeholders versus production-ready, exactly how
staleness, CI status, ticket activity, and budget variance are each
computed, how the interpretation layer is built, and what the resulting
metrics do and don't actually imply, is documented in `METHODOLOGY.md`.
Read that before describing this build to anyone who's likely to ask "how
did you calculate that" or "what could this get wrong," not just "what
does it show."
