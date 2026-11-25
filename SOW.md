# Statement of Work — Portfolio Pulse

**Engagement type:** Self-directed technical build, single owner
**Status:** Complete for stated scope; extension points identified and explicitly out of scope, not silently deferred

---

## 1. Objective

Build a working system that answers a specific, previously-unmet
requirement: direct, verifiable visibility into project delivery, code
health, ticket activity, and budget position, pulled from source systems
rather than collected through manual status reporting, with every
computed judgment traceable to a named, inspectable rule rather than
asserted.

This is not a generic portfolio dashboard. It exists to demonstrate a
specific operating capability, direct systems integration in place of
status collection through people, under the same rigor a live technical
interview would apply, verified before being called done, not asserted
and hoped.

## 2. Scope of work

Delivered in six phases, each building on a verified prior phase rather
than assumed to work:

| Phase | Deliverable | Status |
|---|---|---|
| 1 | Direct GitHub API pull: delivery signal, issue tracking | Complete |
| 2 | Budget join, risk flagging, markdown + HTML report renderers | Complete |
| 3 | Independent verification tooling (`verify_pull.py`), catching and fixing a real staleness-calculation bug | Complete |
| 4 | Code health (CI status), ticket/CR activity, deterministic per-project and portfolio interpretation layer | Complete |
| 5 | MCP server exposing verified data as tools; agent client demonstrating a reasoning loop on top | Complete (tool layer verified live; agent layer correctly written, unrun, see §5) |
| 6 | Automated test suite: unit, mocked negative-case, and live integration tests | Complete |
| 7 | Targeted gap remediation: retry/backoff logic, input validation, CI wiring, scoped narrowly from `GAP_ANALYSIS.md` rather than addressing every named gap at once | Complete for stated scope |
| 8 | Maturity-gap closure against a 7-tier AI-maturity framework: agent eval harness, structured logging, consolidated incident log, scoped narrowly from `GAP_ANALYSIS.md` §7 | Complete for stated scope |
| 9 | Four of Tier 5's five named components: alerting (`pulse_alert.py`), an unattended cron schedule plus a real-pipeline CI job, a live grounding-eval harness, an operational incident-log template. The fifth component, real users, explicitly not attempted, named instead as out of reach by building alone | Complete for the four components attempted |
| 10 | Priority-aware pull scheduler (`pulse_scheduler.py`), to the user's own corrected spec: a 24h baseline cadence, an earlier pull only when a cheap conditional check detects a real change on a tracked repo, never more than 3 pulls per rolling 24h regardless of trigger. Replaces Phase 9's unconditional daily pull in CI with a scheduler-gated job, and adds the state-persistence step the mechanism depends on to work across scheduled runs at all | Complete for stated scope; never observed running end to end in a hosted repo, same boundary as Phase 9's schedule trigger |

## 3. Deliverables

- `github_status_pull.py` — direct API pull, no manual input; now with narrowly-scoped retry logic and input validation
- `pulse_core.py` — single source of truth for joining, flagging, and interpreting data
- `generate_report.py`, `generate_dashboard.py` — two renderers over one dataset
- `verify_pull.py` — independent correctness check via a separate code path (git protocol vs. REST)
- `mcp_server.py`, `agent_client.py` — the MCP/agent layer
- `tests/test_pulse_core.py`, `tests/test_github_pull.py`, `tests/test_agent_eval.py`, `tests/test_pulse_alert.py`, `tests/test_grounding_eval.py`, `run_tests.py` — the test suite and its runner
- `.github/workflows/tests.yml` — CI wiring plus a `schedule:` trigger and a separate `unattended-pull` job running the real pipeline, not yet observed running in a hosted repo
- `pulse_log.py` — structured JSON-lines run/repo logging, appended by `github_status_pull.py`
- `pulse_alert.py` — monitoring/alerting on top of the structured log: detects a crashed run, a total pull failure, or a repeated-failure pattern, and fires a webhook (or states plainly what it would have sent, with no webhook configured)
- `grounding_eval.py` — a live grounding-eval harness, distinct from `tests/test_agent_eval.py`'s scaffolding eval: checks a live agent's claimed numbers and status words against the real tool output from that same run. Its extraction/comparison logic is tested; its model-facing half has not run against a live model, same stated limit as `agent_client.py`
- `OPERATIONAL_INCIDENTS.md` — a template for a genuinely separate operational incident log, empty by design until this project actually runs unattended
- `pulse_scheduler.py` — the priority-aware pull scheduler: enforces a 24h baseline pull cadence, allows an earlier pull only on a cheap conditional-request change signal, and caps pulls at 3 per rolling 24h regardless of trigger; logs every decision (pull or skip) via `pulse_log.py`
- `tests/test_pulse_scheduler.py` — deterministic tests over hand-built run histories and a stubbed change-check, covering the cap, the baseline, the priority trigger, and the "unknown network result never counts as a change" safety property
- `GAP_ANALYSIS.md` — honest self-assessment against production standards, severity-ranked and sequenced
- `INCIDENT_LOG.md` — the consolidated, numbered record of every real defect this project's own verification work has found, fix and regression test for each
- `MATURITY_ASSESSMENT.md` — this project mapped against an external 7-tier AI-maturity framework, tier by tier, each claim tied to a specific artifact
- `README.md`, `METHODOLOGY.md`, `MCP_VERIFICATION_LOG.md`, `TEST_REPORT.md` — documentation, written to be read by someone deciding whether to trust the system, not just describing what it does

## 4. Acceptance criteria, and what actually satisfied each one

Every criterion below is tied to a specific, checkable artifact, not a
claim taken on faith:

1. **The pipeline runs end to end against real and fixture data.** Verified: `sample_report_FIXTURE_TEST.md`, `sample_dashboard_FIXTURE_TEST.html`.
2. **Staleness reflects the branch that actually matters, not any push anywhere.** Verified: the `pushed_at` bug, caught by `verify_pull.py`, fixed, re-verified. Documented in `METHODOLOGY.md`.
3. **The MCP tool layer responds correctly to a real client.** Verified: a real `ClientSession` called all three tools and got correct data back. Documented in `MCP_VERIFICATION_LOG.md`, including a second real bug (error-message sanitization) caught in that same verification pass.
4. **Edge and negative cases are covered by test code, not just the happy path.** Verified: 92 tests, boundary conditions (budget thresholds, zero-division), missing-data combinations, priority ordering under simultaneous failure conditions, negative API responses (404, rate limiting, 5xx, connection errors) via deterministic mocking, malformed-shape input validation, the agent loop's scaffolding driven against a real MCP server with only the model call scripted, alerting conditions against hand-built log histories, the grounding-check's number/status extraction logic against hand-built answer/tool-output pairs, and the pull scheduler's cap/baseline/priority decision logic against hand-built run histories with the network call stubbed. See `TEST_REPORT.md`.
5. **Where a criterion could NOT be fully verified, that's stated, not hidden.** The agent layer's live reasoning behavior (§5) and 2 live integration tests were blocked by GitHub's rate limit at build time, not silently passed over, explicitly reported as skipped with the reason, distinct from a false pass. The CI workflow's YAML is validated but has not been observed running in a real hosted GitHub Actions environment, same category, stated plainly rather than assumed.
6. **Retrying only helps where retrying can plausibly help.** Verified by test: connection errors and 5xx responses retry with backoff; a 403 rate-limit response makes exactly one call, confirmed by `test_403_rate_limit_never_retries`, not assumed from reading the code.
7. **A third and fourth real defect were found and closed while satisfying criteria 4 and 6, not zero, the same pattern as criteria 2 and 3.** A partial API failure mid-pull previously produced a false "active" status for a project with no actual data, `GAP_ANALYSIS.md` §6 has the full account. A race condition in the live test suite's own rate-limit check was found and fixed the same way, by running it repeatedly under real conditions rather than trusting the design.
8. **A fifth and sixth real defect, both in the agent layer specifically, were found the first time anything actually exercised it.** Building the agent eval harness (Phase 8) caught a stale SDK field name and a list-shaped tool result silently truncated to its first item, before any live model was involved. `INCIDENT_LOG.md` incidents #5–#6 has the full account, including why the second one is the most consequential finding in this project's history: it would have produced a confidently wrong answer, not a crash.
9. **A gap in the CI workflow itself was found while extending it, by inspection rather than by running it, a different and lesser category of catch than criteria 2, 3, 7, and 8 above, stated as such rather than inflated to match them.** Adding the Phase 9 schedule trigger required reading `.github/workflows/tests.yml` closely, which surfaced that its dependency-install step only ever installed `requests`, never `mcp` or `anthropic` — meaning `tests/test_agent_eval.py` (added in Phase 8) would have silently failed the first time this workflow actually ran in a hosted repo. Fixed by installing `requirements.txt` directly. Not caught by running anything, caught by reading carefully; the distinction matters enough to this project's own discipline to state plainly rather than quietly round it up to a seventh "real bug caught by running."
10. **A second CI-workflow gap, same lesser category, found while wiring in the Phase 10 scheduler.** `pulse_scheduler.py`'s cap and baseline both depend on `pulse_run_log.jsonl` (and the priority check on `etag_cache.json`) surviving between scheduled runs — but a GitHub Actions job starts from a clean checkout every time, so without committing those files back, every tick would see an empty log, decide "baseline_due" every single time, and the entire cadence the user asked for would silently never apply. Caught by reasoning through what a fresh checkout actually gives the scheduler on tick two, not by observing it fail in a hosted repo — the same "found by inspection, not by running" category as criterion 9, named the same way rather than inflated. Fixed by adding `permissions: contents: write` and a "Persist scheduler state for the next tick" step that commits those files back with `[skip ci]`.
11. **The maturity-assessment document itself had drifted out of sync with the project it describes, found while updating it again for Phase 10.** `MATURITY_ASSESSMENT.md`'s Tier 5 table still read as if Phase 9 (alerting, the live grounding eval, the operational-incident template) had never happened — a real documentation-consistency gap, not a code defect, caught by re-reading the document before adding to it rather than appending on top of stale claims. Corrected in the same pass that added Phase 10's entries, same discipline as everywhere else in this project: a gap in the paper trail gets named and fixed, not quietly left for someone else to notice.

## 5. Explicitly out of scope

Stated here rather than discovered later:

- **Production-scale deployment.** Built and tested against five repos. Scaling to 40-50 concurrent projects requires a `GITHUB_TOKEN` (a configuration change, not a code change) and has not itself been load-tested.
- **Non-GitHub data sources.** Budget data is a representative CSV; a real deployment would pull from an actual finance system's API, same join logic, different source, not built here.
- **Severity-weighted tickets.** A backlog of five trivial issues and five critical ones currently read identically. Named as a real limitation in `METHODOLOGY.md`, not addressed.
- **Burn-rate budget modeling.** Budget variance is a point-in-time comparison, not spend-over-time against project duration. Named, not addressed.
- **Live-verified agent behavior.** `agent_client.py` is correctly written against verified SDK APIs but has not been run against a live model; no credential was available at build time. This is the one deliverable whose acceptance criterion is partially unmet, stated as such rather than assumed passing.
- **Pagination for high-volume ticket activity.** The ticket-activity pull reads one page (100 items). Adequate at this project's scale, named as a gap for a genuinely high-traffic repo.

## 6. Assumptions and dependencies

- GitHub's public REST API remains available and stable at its current schema.
- Unauthenticated use is rate-limited to 60 requests/hour, shared across whatever else is using the same network path; a `GITHUB_TOKEN` (5,000/hour) is assumed for anything beyond light, occasional use. **Revised at Phase 8:** this specific build environment's own outbound network policy blocks unauthenticated GitHub reads outright, confirmed by a real attempt, a stricter condition than rate-limit exhaustion and worth checking for independently of the rate limit itself.
- The MCP and agent layer assumes the official `mcp` and `anthropic` Python SDKs remain API-stable at the versions pinned in `requirements.txt`. **Revised at Phase 8:** "pinned" means a version range (`mcp>=2.0`), not an exact version; incident #5 in `INCIDENT_LOG.md` is a real instance of that range allowing a breaking attribute-name change (`inputSchema` → `input_schema`) between what was verified and what later installed. Pin exactly, or re-verify on every install, if this matters for a given use.
- Running `agent_client.py` requires an `ANTHROPIC_API_KEY`, not provided or assumed available in the build environment.

## 7. Roles and responsibilities

Single-owner engagement: specification, implementation, testing, and
verification were all performed by the same person. No handoffs, no
division of labor to document, worth stating plainly rather than padding
this section, the accountability for every deliverable above sits in one
place.

## 8. Timeline

Built as a single continuous engagement rather than a scheduled,
multi-week plan, so no calendar dates are represented here; inventing a
timeline this wasn't actually run against would misrepresent how the work
happened. The phase sequence in §2 reflects build order, each phase
began only once the prior one's acceptance criteria were actually met,
not once it was assumed to be done.
