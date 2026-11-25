# Maturity Assessment — Portfolio Pulse vs. a 7-Tier AI-Maturity Framework

**Document type:** An honest, artifact-tied mapping of this project
against an external 7-tier framework, same discipline as `SOW.md` and
`GAP_ANALYSIS.md`: every tier claim below points at a specific, checkable
file, not an assertion taken on faith. Where a tier is only partly met,
that's stated as precisely as everywhere else in this project — a tier
claimed in full that was only half-earned would be exactly the kind of
overclaim this whole build has been constructed to avoid.

**Revision note:** an independent cross-check against this same
framework caught two things a first draft of this document got wrong by
being too generous, and one thing it had already gotten right. Corrected
here rather than defended: the headline Tier 4 claim is now stated as
"3-4, not clean" instead of "4, with a boundary" (same underlying facts,
less room for the qualifier to get dropped under a follow-up question);
the Tier 5 "incident log" row is now stated as not met, since a
build-time defect log is a precursor to an incident log, not one; and a
new paragraph makes explicit that most of what this project demonstrates
runs on a fixture, not a live pull, a fact `README.md` already disclosed
but this document had not previously surfaced on its own. A "Path to a
clean Tier 4" section, with three concrete steps, is added below.

**Second revision note (Phase 10):** this document had drifted out of
sync with its own project — a real gap, caught while updating it again
for Phase 10, worth naming plainly rather than quietly patching. Phase 9
had already built `pulse_alert.py` (real alerting logic, tested),
`grounding_eval.py` (a live grounding-eval harness distinct from the
agent-scaffolding eval), and `OPERATIONAL_INCIDENTS.md` (a real, if
empty-by-design, template) — but the Tier 5 table below still read as if
none of that existed ("no alerting," "not met" with no template named).
Corrected now: each Tier 5 row reflects what Phase 9 actually built,
each one still precisely scoped to "the mechanism exists and is tested"
rather than rounded up to "this has happened in real operation," which
is a different and still-unmet claim. Phase 10 (the priority-aware pull
scheduler, `pulse_scheduler.py`) is added where it belongs: it makes the
"runs unattended" mechanism more capable, not more proven — it has the
same "never observed running in a hosted repo" boundary every prior
unattended-run claim in this project has had from the start.

**The framework, as given:**

| Tier | What it looks like | Test |
|---|---|---|
| 1 | Directing one model to produce deliverables | Output reviewed by you before use |
| 2 | Multi-model validation as a standing discipline | Disagreement between models treated as signal |
| 3 | Formal study of agent architecture | Can explain agent, tool, call, structured output |
| 4 | Self-verifying agentic systems you built | Independent check catches the system's own errors |
| 5 | In production for other people | Runs unattended, has users, evals, monitoring, an incident log |
| 6 | Operating model redesigned around agents | Measured before and after; governance; people trained |
| 7 | Systems that compound | Multi-agent hand-offs; failures become tests automatically |

---

## Tier 1 — Directing one model to produce deliverables

**Met.** Every file in this project was AI-directed and human-reviewed
before being treated as done (`SOW.md` §7: "specification, implementation,
testing, and verification were all performed by the same person").
Baseline, not a differentiator on its own — every tier above assumes
this one.

## Tier 2 — Multi-model validation as a standing discipline

**Not met inside this project specifically — met elsewhere in the
broader portfolio.** Portfolio Pulse's own correctness checks are
dual-code-path (`verify_pull.py`'s git-protocol check against
`github_status_pull.py`'s REST pull), not multi-*model*. That's a real
form of independent verification (it's what Tier 4 below is actually
about), but it isn't this tier's specific test: no two LLMs' outputs are
compared anywhere in this codebase, and no disagreement between models
is treated as a signal anywhere in it. The standing discipline this tier
actually describes lives in a separate, unrelated proof point (an EMBA
financial model where a second model, run deliberately against the
first's output, caught a pivot-scenario error the first model's output
had silently broken) — real, but not part of this system. Don't claim
this tier for Portfolio Pulse itself; claim it for the portfolio, with
that different example.

## Tier 3 — Formal study of agent architecture

**Met, and the strongest "explain it cold" evidence in the project.**
`mcp_server.py` defines three tools with explicit input/output shapes;
`agent_client.py` implements the standard tool-use loop (call model →
tool_use → call tool → tool_result → repeat) explicitly, not
abstracted behind a framework that would let the mechanics stay
unexplained; `MCP_VERIFICATION_LOG.md` documents a real MCP client
calling every tool and what came back. A separate, unrelated credential
(a CodeSignal MCP/agents course) backs the same claim from the "studied
it formally" side, not just the "built it" side. Can explain agent, tool,
call, and structured output specifically because this project required
writing all four by hand, not importing them.

## Tier 4 — Self-verifying agentic systems you built

**Headline claim: Tier 3 on the agent path, Tier 4 on the data path. Not
yet a clean Tier 4 — the tier has two halves, and only one is proven.**
Stated this way deliberately, not rounded up, because Tier 4's own test
("independent check catches the system's own errors") only fully holds
for the half that's actually been run.

**The data/tool half — proven, independently, repeatedly.** `verify_pull.py`
caught the `pushed_at` staleness bug (`tiangolo/fastapi` showed `pushed_at`
as 4 days ago; the default branch's true last commit was 21 days ago — the
exact figures, not rounded, see `METHODOLOGY.md`); a real MCP client
caught the error-sanitization bug; the Phase 7 remediation pass caught a
partial-failure false-active bug and a rate-limit test race condition.
Four real bugs, caught by running something for real against this half
of the system.

**The agent half — scaffolding tested, the agent itself still unrun.**
The new eval harness (`tests/test_agent_eval.py`) caught two more real
bugs (a stale SDK field name; a list-result silently truncated to one
item) within its first hour of existing — but it tests the loop's
*mechanics* with a scripted stand-in for the model, not a live model's
actual behavior. **No agent has ever acted in this system.**
`agent_client.py` has never run against a live model, for lack of a
provisioned `ANTHROPIC_API_KEY` — stated the same way in `SOW.md` §5,
`GAP_ANALYSIS.md`, and `MCP_VERIFICATION_LOG.md` since this was first
built. Nothing yet checks a live agent's stated answer against what the
tools actually returned, because there has never been a live answer to
check. That specific capability — extracting every number and status
claim from a live agent's answer and diffing it against the real tool
output, failing the run on a mismatch — is the independent check Tier
4's "agentic" half actually asks for, and it does not exist yet. See
"Path to a clean Tier 4" below for exactly what closes this.

**One more factor that keeps even the data-path claim from being a
clean, unqualified "live system":** most of what this project
demonstrates end to end (the sample report, the sample dashboard, the
verification run) is built from `fixture_for_testing.json`, a
schema-accurate fixture, not a full live pull — disclosed plainly in
`README.md`'s "What's real and what isn't" section, not something this
assessment is surfacing for the first time. Exactly one row, ever, has
been genuinely live (`tiangolo/fastapi`, in `pull_results_PRE_FIX_LIVE_partial.json`)
— and that row was pulled under the OLD, pre-fix `pushed_at` logic, before
the schema even changed, specifically to document the bug. Under the
CURRENT, fixed pipeline, zero rows have been pulled live end-to-end and
reported. The data/tool verification itself is real and repeatable (the
mechanism was proven against real GitHub responses at several points);
the specific claim "this is a live system showing live data" is not yet
defensible as stated, and the budget layer is synthetic throughout
(`SOW.md` §5; public repos have no real budget to pull). Neither of these
breaks the project. Both mean "live system" needs the qualifier attached
every time it's said, not dropped under a follow-up question.

## Tier 5 — In production for other people

**Not met as a whole; four of its five named components now exist in
honest, demo-scale form, stated component by component rather than
rounded up to the tier. "Exist in demo-scale form" means: built, and
covered by deterministic tests. It does not mean any of them has fired,
or been observed running, during real unattended operation — that
distinction is the entire point of keeping this table component-by-
component instead of a single checkbox.**

| Component | State |
|---|---|
| Runs unattended | Mechanism built, never observed running unattended over real time. `pulse_scheduler.py` (Phase 10) decides each tick whether to pull — a 24h baseline, an earlier pull only on a detected change, capped at 3 pulls per rolling 24h — and `.github/workflows/tests.yml`'s `unattended-pull` job calls it on a `schedule:` trigger, persisting `pulse_run_log.jsonl`/`etag_cache.json` back to the repo so the cap and baseline survive between ticks. The decision logic is unit-tested (`tests/test_pulse_scheduler.py`, deterministic, mocked network). None of it has actually fired from inside a real hosted GitHub Actions environment — same boundary this item has had since Phase 8, now resting on more mechanism, not more proof. |
| Has users | Not met, and not fabricated as met. Zero real users; `SOW.md` §5 names production-scale deployment as explicitly out of scope. |
| Evals | Two distinct eval layers now exist, both tested, neither yet run against a live model. `tests/test_agent_eval.py` evaluates the agent *scaffolding* mechanically (see Tier 4) — the loop doesn't crash or truncate data. `grounding_eval.py` (Phase 9) is the complementary live-grounding check: for a real agent answer, extract every number/status claim and diff it against the real tool output from that same run, fail on mismatch. Its extraction/comparison logic is tested (`tests/test_grounding_eval.py`); its model-facing half has never run, same stated limit as `agent_client.py` itself — no `ANTHROPIC_API_KEY` has been available at build time. |
| Monitoring | Logging and alerting both exist and are tested; neither has fired for a real condition in real operation. `pulse_log.py` produces structured, queryable run/repo events. `pulse_alert.py` (Phase 9) reads that log and fires a real webhook POST (or states plainly what it would have sent, with none configured) on three named conditions — a crashed run, a total pull failure, a repeated-failure pattern — tested against hand-built log histories (`tests/test_pulse_alert.py`). What's missing isn't the mechanism, it's a real alert actually firing during real unattended operation; nothing in this build environment has produced that condition for real yet. |
| Incident log | **Still not met, but a real, honest template now exists where before there was nothing.** `INCIDENT_LOG.md` remains the build-time defect log — found by this project's own verification work, not by a live user or production monitoring, so it stays a precursor rather than the thing itself. `OPERATIONAL_INCIDENTS.md` (Phase 9) is the genuinely separate file this tier actually asks for: deliberately empty, with its own "empty, by design, not by oversight" statement, waiting for the "runs unattended" item above to actually run long enough to produce a real entry. Building the template doesn't close the gap; it names exactly what has to happen next to close it. |

**Honest summary for this tier:** don't claim "production" or "has
users." Do claim, specifically, "four of this tier's five components —
an unattended-run scheduler, two distinct eval layers, alerting on top
of structured logs, and a real operational-incident template — are
built and tested against a project that has deliberately never faked
the fifth (real users), and none of the four has yet been observed
firing under real, unattended operation; that's the next thing to prove,
not more code to write."

## Path to a clean Tier 4

Three steps, roughly two days of work, none of them architecture
changes — all three are running something that's already correctly
written, for the first time, and watching what actually happens:

1. **Run the agent loop live, with a provisioned `ANTHROPIC_API_KEY`,
   including deliberate trap questions** (an unknown repo, a question
   with no clean tool answer, a question inviting the model to guess
   rather than call a tool). This is the one step that actually produces
   a live agent answer to evaluate — nothing below works without it.
2. **Build a grounding eval, distinct from `tests/test_agent_eval.py`.**
   For each question, automatically extract every number and status
   claim from the agent's live answer and diff it against what the tools
   actually returned for that run; a mismatch fails. This is the
   independent check Tier 4's agentic half specifically asks for, and
   it's a different, complementary test from the scaffolding eval
   already built — that one needs no live model and proves the loop
   doesn't crash or truncate data; this one needs a live model and
   proves the model didn't misstate what the loop handed it.
3. **Do one full live pull with a `GITHUB_TOKEN`** (or let the CI
   workflow run once this is hosted in a real repo), with zero fixture
   rows in the reported result — closing the gap named above, not
   narrowing it with a partial or mixed pull.

**What to say until all three are done, verbatim:** "I built a
self-verifying status pipeline and an MCP tool layer. The verification
caught six real bugs, four in the data path, two in the agent's
scaffolding. The agent on top is written and its scaffolding is tested,
but no agent has actually acted in this system yet, and here's exactly
how I'd prove it." That holds under a third follow-up, in a hostile
interviewer's style, because every clause in it is backed by a file. "I built a
self-verifying agentic system," unqualified, does not hold under that
same follow-up, and shouldn't be said until these three steps close it.

## Path to Tier 5

Four of the five things this tier actually requires are buildable by one
person without an organization behind them. The fifth genuinely isn't,
and no amount of building closes it — it requires time and someone
else's real behavior, not more code. Listed in the order they unblock
each other, with which category each falls into stated plainly, because
conflating "I built the mechanism for this" with "this has actually
happened" is exactly the error this whole document exists to avoid:

1. **Runs unattended — built, including the throttling policy, still
   needs real time to accumulate.** Done, past the YAML-trigger stage
   this item originally described: `.github/workflows/tests.yml`'s
   `unattended-pull` job runs `pulse_scheduler.py` (Phase 10) on a
   `schedule:` trigger, that script decides each tick whether to
   actually pull — a 24h baseline, an earlier pull only on a detected
   change, never more than 3 pulls per rolling 24h — and the job
   persists `pulse_run_log.jsonl`/`etag_cache.json` back to the repo so
   that cap and baseline survive between ticks, a real dependency named
   and handled, not assumed away. What actually proves the claim still
   isn't the YAML or the scheduler's own tests, it's a visible run
   history in the Actions tab showing it fired on its own, correctly,
   obeying its own cap and baseline, across failures and successes,
   over a real stretch of time (weeks, not one run) with no one
   intervening. That history can only be earned by letting it run, not
   written in advance — this item moved from "not started" to "built
   and tested, waiting on real time," not to "done."
2. **Evals — the live half built, not yet run. The scaffolding half
   already closed.** `grounding_eval.py` (Phase 9) is the live
   grounding eval named here: extract every claim from a live agent
   answer, diff against real tool output, fail on mismatch. Its
   extraction logic is tested (`tests/test_grounding_eval.py`); its
   model-facing half has never run, same gap named throughout this
   document for `agent_client.py` itself. Closing Tier 4's agentic half
   and Tier 5's "evals" box is still the same piece of work, not two —
   now written, not yet exercised live.
3. **Monitoring — built and tested, not yet fired for real.**
   `pulse_log.py` produces the structured log. `pulse_alert.py`
   (Phase 9) reads it, checks for a real condition (a run that never
   finished, a run with zero successes, a repeated-failure pattern
   across recent runs), and fires a real webhook POST — or, with none
   configured, states plainly what it would have sent. Tested against
   hand-built log histories with a mocked webhook
   (`tests/test_pulse_alert.py`). What's left isn't more code, it's a
   real `PULSE_ALERT_WEBHOOK_URL` from whoever owns this, and a real
   condition arising during real unattended operation to prove the
   notification actually arrives, not just that the script runs.
4. **Incident log, the operational kind — the template is built
   (Phase 9); it stays empty until step 1 actually runs.**
   `INCIDENT_LOG.md` stays what it is: the build-time defect history.
   `OPERATIONAL_INCIDENTS.md` exists now, deliberately empty, with its
   own explanation of why, ready to receive real entries once step 1
   above is actually running unattended for real — but it cannot
   honestly contain anything until something real goes wrong in real
   operation. The template was buildable in an afternoon and is done;
   an incident log cannot be backfilled with incidents that haven't
   happened, and nothing about Phase 10 changes that.
5. **Has users — not buildable at all, by design, and the one honest
   way to get there is named, not worked around.** A real person,
   other than whoever built this, relying on it for something real.
   The only two credible, non-fabricated paths: point `TRACKED_REPOS` at
   repos from a real engagement already underway (or any other repo
   someone already has oversight of) and actually use the
   dashboard operationally, even if the only user is the builder
   themselves at first; or hand it to one real colleague on a real
   project and have them actually look at it on a recurring basis, not
   once. Neither can be simulated, scripted, or accelerated by more
   agent work in this sandbox. This is the one component of Tier 5 this
   project cannot close by building more; it closes by someone actually
   using it, which takes exactly as long as that takes.

**Honest summary for Tier 5, now that four of five are actually
built:** the remaining work on those four isn't more code, it's time —
a real hosted repo, a real stretch of unattended runs, a real webhook
URL, a real condition that triggers it. The fifth, users, is a statement
about the world, not about the code, and stays open until someone
genuinely adopts it — stated here precisely so "I built the mechanisms
for Tier 5" is never allowed to quietly become "I'm at Tier 5" before
any of them has actually run for real.

## On Tier 6 — why "elevate to it" isn't the right framing

**This tier cannot be reached by building more on Portfolio Pulse, and
attempting to make it look reached would be the exact failure mode this
whole project has been built to avoid.** Read the test again: "measured
before and after; governance; people trained." Every clause names
something that only exists inside a real organization with a real team —
a before state and an after state to measure against each other, a
governance structure with more than one person in it, and people, plural,
who were trained on something. A solo demo project, by construction, has
none of these, and no amount of additional code changes that. Writing a
`GOVERNANCE.md` for an audience of one, or a "training" doc for the
builder's own benefit, would be a document, not evidence — and worse,
it would be exactly the kind of prop that looks like progress to a
skim-reader and collapses on the first real follow-up question, the
opposite of the discipline every other document in this project has held
to.

**What's actually true, and worth saying instead:** Portfolio Pulse is
the prototype of an operating model built around agents, not an instance
of one, because there is no operation here to redesign, only a
demonstration that the mechanism works. The honest, interview-usable
version of a Tier-6 claim is forward-looking and conditional, not
present-tense: "I've already proven the mechanism solo, including where
it breaks and how I catch that. If I'm in a role with a real PMO, a real
team, and real before-state metrics, here's specifically how I'd roll
this out, measure the change, and govern it" — followed by naming the
specific before-metric this role's own stated pain point would supply
(for a PMO: time-to-detect a stalled project, or hours spent chasing
status updates per week, whatever the interviewer named as their actual
problem). That is a real, credible, well-evidenced pitch. "I've already
redesigned an operating model around agents" is not, and no amount of
further building in this sandbox makes it one — only an actual mandate
does.

## Tier 6 — Operating model redesigned around agents

**Not met, and not a goal of this project.** This is a single-owner demo
build (`SOW.md` §7), not an organizational rollout. There is no
before/after measurement, no governance structure, and no one else
trained on anything here, because there is no one else. This tier
describes a different kind of claim entirely — the kind that would
describe actually running a function at scale with a team under an
agent-redesigned operating model, not a solo proof-of-work build. Not
applicable to Portfolio Pulse; don't reach for it here.

## Tier 7 — Systems that compound

**Not met on multi-agent hand-offs; partially, genuinely met on
"failures become tests," with "automatically" stated precisely rather
than overclaimed.**

- **Multi-agent hand-offs:** not present. One MCP server, one agent
  client, no hand-off between agents of any kind.
- **Failures become tests:** this is real, and it is the one part of
  this tier worth claiming explicitly. Every one of the six incidents in
  `INCIDENT_LOG.md` produced a permanent regression test, not just a
  fix — `test_partial_failure_on_commit_lookup_does_not_report_false_active`,
  `test_403_rate_limit_never_retries`, and the two new agent-eval tests
  are the test-side half of incidents #3, #4 (by pattern), #5, and #6. It
  is not *automatic* in the sense of a system that writes its own tests
  unsupervised — a human (directing AI) wrote each one, deliberately,
  every time. "Failures become tests, as a consistently applied
  discipline" is the honest version of this claim; "failures become
  tests automatically, with no one deciding to write one" is not what
  happened here and shouldn't be implied.

---

## One-paragraph summary, if asked to compress this to an answer

Tier 3 on the agent path, Tier 4 on the data path — not yet a clean Tier
4, since no agent has ever actually acted in this system. Tier 1 is
baseline-met. Tier 2 is real but lives in a different project, not this
one. Tier 5 is not claimed as a whole; of its five components, four are
now real, tested artifacts — a priority-aware unattended-pull scheduler
with its own cap/baseline logic, two distinct eval layers (scaffolding
and live-grounding), alerting on top of structured logs, and an
operational-incident template — and the fifth, real users, is correctly
left unbuilt, not simulated. None of the four has actually fired during
real unattended operation yet; that's the next thing this project needs
time, not more code, to prove. Tier 6 isn't applicable to a solo build.
Tier 7's multi-agent claim isn't met; its "failures become tests" claim
is real, as a discipline, not an automation. Two further qualifiers
apply throughout: most of what this project demonstrates runs on a
fixture, not a live pull (disclosed in `README.md`, not new here), and
the budget layer is synthetic. Say "3-4, clean on the data path, not yet
on the agent path" rather than "4," and "the Tier 5 mechanisms are built
and tested" rather than "Tier 5."
