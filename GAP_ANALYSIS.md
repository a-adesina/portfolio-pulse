# Gap Analysis & Remediation Roadmap — Portfolio Pulse

**Document type:** Honest self-assessment against production engineering standards at scale, not a checklist exercise
**Basis:** What would actually surface in a real architecture or security review at a company operating at real scale, not a generic "best practices" list
**Status:** No remediation started; this is the prioritized plan, not the work

---

## 1. Purpose

Portfolio Pulse was built and verified as a working demonstration, every
claim in `SOW.md` is tied to a specific, checkable artifact. This
document is the deliberate next step: naming what a working demonstration
does not yet claim, precisely, severity-ranked, and sequenced, rather
than leaving those gaps implicit or discovered under questioning.

The standard here is not "what would make this a bigger project." It's
"what would this need before a security or architecture review at a
company operating at real scale would sign off on it." Those are
different bars, and conflating them would make this document as
dishonest as overselling the build itself would have been.

## 2. Severity framework

Three tiers, so prioritization is principled rather than a gut-feel
ranking:

- **P0 — Blocking.** Would fail a security or architecture review
  outright. Must be resolved before this touches anything beyond a demo
  with fixture or personal-repo data.
- **P1 — Significant.** Would survive a review with a credible
  remediation plan attached, but would be flagged as a real, named risk,
  not waved through silently.
- **P2 — Real, lower urgency.** Correct engineering hygiene. Absence is
  a legitimate finding, not an immediate danger.

## 3. Gap register

### 3.1 Security (P0 — the highest-consequence category)

| Gap | Severity | Why it matters | Current state |
|---|---|---|---|
| No authentication on the MCP server | P0 | Anyone who can invoke it reads every tracked project's budget and delivery data | None; any MCP client can call any tool |
| Secrets in plain environment variables | P0 | No rotation, no access control, no audit trail on credential use | `os.environ.get()`, no secrets manager |
| No audit logging | P0 | No record of who queried what financial data, when | Nothing logged beyond stderr print statements |
| No input validation at the API boundary | ~~P1~~ **Addressed** | An unexpected response shape from GitHub could silently corrupt data rather than fail loudly where it would be caught | `get_default_branch_last_commit` now validates shape and degrades to `(None, None)` rather than raising; this specific check caught a real second bug, see §6 |
| No defense against prompt injection via pulled content | P1 | Issue titles or ticket text flowing into the agent's context is an untested injection surface, not yet exploited, not yet defended | No sanitization or instruction-hierarchy defense on pulled text |

### 3.2 Reliability

| Gap | Severity | Why it matters | Current state |
|---|---|---|---|
| No retry or backoff logic | ~~P1~~ **Addressed** | A transient network blip is treated identically to a genuine failure | `_get()` retries connection errors and 5xx responses with exponential backoff (3 attempts); 403 rate-limit and 404 deliberately excluded, retrying those wastes a call and cannot succeed |
| No resumability | P1 | An interruption at repo 30 of 50 means starting over, expensive and slow at real scale | No checkpointing anywhere in the pipeline |
| No redundancy | P2 | One process, one run, nothing to fail over to | Single-threaded, single-instance by design |

### 3.3 Architecture

| Gap | Severity | Why it matters | Current state |
|---|---|---|---|
| Polling, not event-driven | ~~P1~~ **Partially addressed** | The wrong model at real scale; re-fetching and re-deriving state on demand doesn't match how GitHub actually notifies interested parties | `pulse_scheduler.py` (Phase 10) makes the polling cheaper and priority-aware — a conditional (ETag) check, not a full pull, decides whether a real pull is warranted before the next 24h baseline — but it is still polling, not a webhook listener. Real event-driven ingestion needs admin access to register a webhook on the tracked repo, which none of the five `TRACKED_REPOS` grant (third-party repos); stated as a real architectural limit, not solved by a smarter poll |
| No persistence or time-series storage | P1 | Can only state current status, never trend, "getting better or worse" is a real reporting need this can't answer | Flat JSON/CSV, overwritten each run |
| Sequential, not concurrent | P2 | 40-50 repos take 40-50x one repo's time | One repo processed at a time |

### 3.4 Observability

| Gap | Severity | Why it matters | Current state |
|---|---|---|---|
| No structured logging | ~~P1~~ **Addressed** | Nothing is queryable or alertable; a `print()` statement is not an incident response tool | `pulse_log.py` appends a structured JSON-lines entry (`run_started`, `repo_pull_succeeded`/`repo_pull_failed` with reason, `rate_limited`, `run_finished`) per run and per repo to `pulse_run_log.jsonl`, in addition to, not instead of, the existing stderr prints. Narrowly scoped: still no metrics/alerting on top of these logs, and not every HTTP status branch in `_get()` emits a distinct event, only the ones that change what a repo's outcome means |
| No metrics or alerting | ~~P1~~ **Addressed, mechanism only** | A pull that starts failing repeatedly does so silently; nobody gets paged | `pulse_alert.py` reads the structured log and fires a real webhook (or states plainly what it would have sent) on three named conditions: a run that never finished, a run with zero successes, or a repeated pattern of failed runs. The detection logic is tested against hand-built log histories; the alert has never actually fired against a real webhook in real operation, because this project has never run unattended in a real repo yet, see `OPERATIONAL_INCIDENTS.md` |
| No distributed tracing | P2 | Debugging a wrong answer across pull → tool call → model reasoning has no trail to follow | None |

### 3.5 Testing & CI maturity

| Gap | Severity | Why it matters | Current state |
|---|---|---|---|
| Tests not wired to CI | ~~P1~~ **Addressed** | Tests only run when someone remembers to run them locally, not on every change | `.github/workflows/tests.yml` runs the suite on every push/PR across Python 3.10-3.12, using the Actions-provided token so live integration tests get a real chance to run, not just skip; not yet verified running in a real hosted repo, see §6 |
| No coverage measurement | P2 | 45 tests sounds substantial; the actual percentage of the codebase they exercise is unmeasured | No coverage tool configured |
| Renderers and MCP tool wrappers untested by test code | P1 | `generate_report.py`, `generate_dashboard.py`, and `mcp_server.py`'s tool logic were verified manually and visually, not by automated tests | Verified once, not regression-protected |
| No evaluation framework for the agent layer | ~~P1~~ **Partially addressed** | Nothing systematically checked the agent's scaffolding, let alone whether its live judgment stays grounded in tool results over time | `tests/test_agent_eval.py` drives the real `mcp_server.py` subprocess through `agent_client.py`'s real tool-use loop with a scripted model, and already caught two real bugs (see `INCIDENT_LOG.md` #5–#6). This tests the scaffolding the model runs on (tool-schema conversion, multi-round orchestration, structured errors, the call cap) — it does NOT test a live model's actual judgment, which still requires a credential and remains fully untested. Don't let "there's an eval suite now" become "the agent is evaluated" |
| Never tested at real scale | P2 | Five repos, not forty; no load testing performed | Fixture-scale only |

### 3.6 Lower-priority, real but not blocking (P2 throughout)

No containerization, no infrastructure-as-code, no semantic versioning,
no multi-tenancy (one fixed repo list, not many teams each with their
own scope), no accessibility work on the HTML output, no
internationalization. Named for completeness; none of these is the
reason this wouldn't pass a first review, the P0 and P1 items above are.

## 4. Remediation sequence

Sequenced by dependency and risk reduction per unit of effort, not by
category order above. Rough relative sizing only (S/M/L), stated as
judgment, not measured, inventing specific day or week counts with no
real velocity data behind them would be exactly the kind of fabricated
precision this project has avoided everywhere else.

**Phase 0 — Close the Tier 4 claim.** *Size: S, roughly two days.*
Added after an independent cross-check against `MATURITY_ASSESSMENT.md`
found the Tier 4 claim was being stated as cleaner than the evidence
supports. Sequenced before Phase 1 on purpose: this is not production
hardening, it's proving what's already claimed, cheaper than any phase
below, and higher-value for anyone citing this project in an interview
right now. Three steps, each independent, none requiring architecture
changes:
1. Run `agent_client.py` live with a provisioned `ANTHROPIC_API_KEY`,
   including deliberate trap questions.
2. Build a grounding eval, distinct from `tests/test_agent_eval.py`'s
   scaffolding eval: extract every number/status claim from the live
   agent's answer and diff it against the real tool output for that run;
   a mismatch fails. This is what Tier 4's "independent check catches
   the system's own errors" test actually asks for on the agent side.
3. Do one full live pull via `GITHUB_TOKEN` (or a real hosted CI run)
   with zero fixture rows in the reported result.

Full reasoning in `MATURITY_ASSESSMENT.md`'s "Path to a clean Tier 4."

**Phase 1 — Security foundation.** *Size: M.* Secrets manager, MCP
authentication and RBAC, input validation at the API boundary, audit
logging, prompt-injection defense on pulled content. Sequenced first
without exception: nothing below is worth building on top of a system
that isn't yet safe to point at anything beyond fixture or personal-repo
data.

**Phase 2 — Reliability foundation.** *Size: S-M.* Retry and backoff
logic (done, §3.2) and structured logging with basic alerting (done,
Phase 9, `pulse_log.py` + `pulse_alert.py`) are now closed. Checkpointing
for resumability remains open. Comes second because it makes the
*current* architecture trustworthy before any larger rework, and because
Phase 4's persistence layer will want checkpointing primitives that
belong here first.

**Phase 3 — Testing & CI maturity.** *Size: M.* Wire the existing suite
into CI (done, §3.5) and build the agent evaluation framework (done
twice over, Phase 8's scaffolding eval and Phase 9's grounding eval) are
now closed. Coverage measurement and extending test coverage to the
renderers and MCP tool wrappers remain open. Sequenced before the
architecture rework so that rework happens against a tested,
CI-protected baseline, not a moving, unverified target.

**Phase 4 — Architecture rework.** *Size: L, the largest phase.*
Event-driven ingestion via GitHub webhooks in place of polling, a real
persistence layer with time-series storage for trend-aware
interpretation, concurrent fetching. The most expensive change,
deliberately sequenced after security, reliability, and testing are
already in place, rebuilding architecture on top of an insecure,
unprotected base would be building on sand.

**Phase 5 — Scale & polish.** *Size: M.* Multi-model fallback for the
agent layer, cost and spend monitoring, containerization,
infrastructure-as-code, multi-tenancy, accessibility and
internationalization work. Real, but correctly last, none of it matters
if Phases 1-4 aren't done first.

## 5. What this document is, and isn't

This is a prioritized map of the distance between a verified working
demonstration and a system that would pass a real production review at
scale. It is not an estimate with a delivery date attached, and not a
claim that any of this is in progress. Naming the gap precisely, the
same discipline `METHODOLOGY.md` applied to the build itself, is the
point of the document, not a preamble to apologize for before getting to
the good parts.

## 6. Progress: three items from this register, actually closed

Recorded formally as Phase 7 in `SOW.md`. Three P1 items above (input validation, retry logic, CI wiring) moved
from named gap to addressed, narrowly scoped on purpose rather than
solving the whole Security, Reliability, and Testing categories at once,
consistent with §5, this document maps distance, it doesn't promise a
delivery date.

**This section's bug history now lives in `INCIDENT_LOG.md` as incidents
#1–#4,** consolidated into one place rather than left scattered across
this file, `METHODOLOGY.md`, and `MCP_VERIFICATION_LOG.md`. The summaries
immediately below are kept for this section's own context;
`INCIDENT_LOG.md` is the canonical, complete account, now including two
more bugs (incidents #5–#6) found while closing the gaps recorded in §7
below.

**A third real bug was found closing these, not zero, the same pattern
as the two caught earlier in this build.** Adding the "no misleading
partial result" check for input validation surfaced a genuine defect
during live testing: when the commit-lookup call failed partway through
a pull (a rate limit hit at exactly that point, not on the initial repo
call), the old logic let a `None` staleness value silently evaluate to
`is_stale = False`, reporting a project with no data as falsely
"active." A rate-limit hiccup could have made a genuinely dead project
look healthy. Fixed: a failed commit lookup now returns no result for
that repo at all, the same honest path a 404 already took, rather than a
result that looks fine but rests on nothing. A permanent regression test
(`test_partial_failure_on_commit_lookup_does_not_report_false_active`)
guards against it recurring silently.

**A fourth, smaller finding: the live test suite itself had a race
condition.** An earlier version checked GitHub's rate-limit quota once
upfront and skipped if it was too low. Running it repeatedly in this
build's sandbox proved that check unreliable, the quota changed in the
seconds between the check and the actual pull, this environment's shared
IP is under enough concurrent external load for that race to be real,
not theoretical. Fixed by checking after the attempt and diagnosing a
`None` result against quota at that point, rather than predicting from a
stale reading taken moments earlier.

**Honest limit on the CI item specifically:** `.github/workflows/tests.yml`
is written and its YAML validated, but this project isn't hosted in a
real GitHub repository from this build environment, so the workflow has
not been observed actually running in GitHub Actions. That's a real,
stated boundary, the same "written correctly, not yet run live" category
as `agent_client.py`'s agent layer elsewhere in this project, not
silently assumed to work because the YAML parses.

## 7. Progress: two more items closed, against a 7-tier AI-maturity framework

A second remediation pass, prompted by mapping this project against an
external 7-tier AI-maturity table (self-directed model use → multi-model
validation → formal agent architecture → self-verifying agentic systems
→ production-for-others → org-wide agent redesign → compounding
multi-agent systems; full mapping in `MATURITY_ASSESSMENT.md`). Two named
gaps from §3.5 and §3.4 above moved from open to addressed, scoped as
narrowly as Phase 7 was:

- **No evaluation framework for the agent layer** → `tests/test_agent_eval.py`,
  an eval harness that drives the real `mcp_server.py` subprocess through
  `agent_client.py`'s real tool-use loop with only the Anthropic model
  call scripted. Tests the scaffolding, not a live model's judgment,
  stated precisely in that file's own docstring and in §3.5 above.
- **No structured logging** → `pulse_log.py`, appending structured
  JSON-lines run/repo events alongside, not instead of, the existing
  stderr prints.

**A fifth and sixth real bug were found doing this, not zero, the same
pattern as Phase 7.** Within the first hour the new eval harness existed,
before touching a live model at all, it caught: a stale camelCase/snake_case
SDK field name (`t.inputSchema` vs. the installed SDK's actual
`t.input_schema`) in the agent's tool-schema conversion, and a far more
consequential bug, `list_projects()`'s five-item result silently
truncated to one item before reaching the model, because the loop read
only `result.content[0]`. The second of these is the first of this
project's six bugs that would have produced a confidently wrong answer
rather than a crash or an honest failure — full account, and why that
distinction matters, in `INCIDENT_LOG.md` incidents #5 and #6.

**Honest limit on this phase specifically:** closing the scaffolding-eval
gap does not touch the still-open, still-HELD claim that `agent_client.py`
has never been run against a live model. Those are different gaps. This
phase closed the first; the second is unchanged, and still requires a
credential this build environment doesn't have, not more test code.

## 8. Progress: four of Tier 5's five components, the fifth named as out of reach

Prompted directly by the question "what would it take to reach Tiers 5
and 6," answered in full in `MATURITY_ASSESSMENT.md`'s "Path to Tier 5"
and "On Tier 6" sections. Four components closed here, narrowly, the
same discipline as §6 and §7:

- **Monitoring/alerting** → `pulse_alert.py` (§3.4 table above).
- **Runs unattended** → a `schedule:` trigger plus a dedicated
  `unattended-pull` job added to `.github/workflows/tests.yml`, running
  the real pipeline, not just the test suite, on a cron schedule once
  hosted in a real repo.
- **Evals** (the agentic half specifically) → `grounding_eval.py`, which
  checks a live agent's claimed numbers and status words against the
  real tool output from that same run — a different, complementary
  check from Phase 8's scaffolding eval, not a duplicate of it.
- **Incident log** (the operational kind) → `OPERATIONAL_INCIDENTS.md`,
  deliberately created empty, since it cannot honestly hold incidents
  that haven't happened yet.

**The fifth component, real users, is not attempted, by design.** No
amount of further building produces a real person relying on this
system; `MATURITY_ASSESSMENT.md` names the only two honest paths
(self-use on a real engagement, or handing it to one real colleague) and
states plainly that both take as long as they take.

**A seventh finding, in a different category from the first six:**
extending the CI workflow surfaced that its dependency-install step
never installed `mcp` or `anthropic`, which `tests/test_agent_eval.py`
(Phase 8) needs — meaning the workflow would have silently failed the
first time it actually ran in a hosted repo. Fixed. Found by reading the
file carefully while making an unrelated change, NOT by running
anything, unlike every incident in `INCIDENT_LOG.md` — stated as a
different, lesser category of catch rather than folded into that list
to inflate it to seven.

**Honest limit on this phase specifically:** none of the four components
above has fired for real yet. The mechanisms are written and
test-covered; what's missing is this project actually running
unattended, in a real repo, against real credentials, which is exactly
what Phase 9 cannot manufacture and does not claim to.

## 9. Progress: a user-directed correction to the unattended-pull cadence

Phase 9 wired `github_status_pull.py` to run unconditionally on every
schedule firing. The user reviewed that design and corrected it
directly, in their own words: "Build option 1. modify pull to once
every 24 hours unless prompted for more. no more than 3 pulls in a 24
hour window." `pulse_scheduler.py` (Phase 10) implements exactly that,
not the earlier 8-hour-fallback framing this project had proposed before
the correction:

- A hard ceiling of 3 pulls per rolling 24h, checked first, winning over
  everything else below.
- A 24h baseline: if it's been at least 24h since the last pull (or
  there's never been one), pull now.
- A priority trigger: if the baseline isn't due, a cheap conditional
  (ETag) check against each tracked repo can still trigger an earlier
  pull if something actually changed — "prompted for more," in the
  user's words — but only while the cap allows it.

`.github/workflows/tests.yml`'s `unattended-pull` job now calls
`pulse_scheduler.py` instead of the pipeline directly, on a more
frequent cron (every 8h, so the priority check gets a real chance to
matter) — most ticks are expected to decide "not due" and skip, which is
the design working, not a sign of a problem. Every decision, pull or
skip, is logged via `pulse_log.py`'s existing structured log, so the
decision history itself is inspectable the same way every other run
event in this project is.

**A real dependency this mechanism has on how it's hosted, named rather
than assumed away:** the cap and baseline only work if `pulse_run_log.
jsonl` (and the priority check's `etag_cache.json`) survive between
scheduled runs. A GitHub Actions job starts from a clean checkout every
time, so the job now commits those files back to the repo after each
tick (`permissions: contents: write` plus a dedicated persist step).
Caught while wiring this up, before it ran wrong anywhere — an eighth
finding, same lesser "caught by inspection, not by running" category as
the seventh in §8, named the same way rather than inflated to match the
six in `INCIDENT_LOG.md`.

**Also closed in this pass, not strictly part of the scheduler itself:**
`MATURITY_ASSESSMENT.md` had drifted out of sync with Phase 9's actual
deliverables (its Tier 5 table still read "no alerting" and "not met"
with no template named, after `pulse_alert.py` and
`OPERATIONAL_INCIDENTS.md` already existed). Corrected in the same pass
as adding Phase 10, rather than left for a reader to notice the
mismatch first.

**Honest limit, same as every prior unattended-run claim in this
project:** the scheduler's decision logic is unit-tested
(`tests/test_pulse_scheduler.py`, 19 tests, deterministic, network
stubbed). It has not been observed deciding correctly, tick after tick,
from inside a real hosted GitHub Actions environment with real state
persisting between runs. That observation is the only thing that can
actually prove the cadence holds in practice; nothing in this sandbox
can manufacture it.
