# Incident Log — Portfolio Pulse

**Document type:** A single, append-only record of every real defect this
project's own verification work has actually found and fixed. Not a
changelog of features, not a list of hypothetical risks (those live in
`GAP_ANALYSIS.md`) — only things that were genuinely wrong, caught by
running something for real, not by reading the code and trusting it.

**Why this exists as its own file:** the same six incidents below were
previously scattered across `METHODOLOGY.md`, `MCP_VERIFICATION_LOG.md`,
and `GAP_ANALYSIS.md` §6, each told in the context of whatever document
happened to be nearby when the bug was found. Consolidating them here
makes two things checkable at a glance that were previously only true if
you read three documents and added it up yourself: *how many* real
defects this build has actually produced, and that every one of them got
a permanent regression test, not just a fix.

**Format:** newest first within each entry's own numbering is NOT used —
entries are numbered in the order they were found, oldest first, so the
numbering is a stable reference other documents can point to ("see
incident #6") without renumbering later.

---

## Incident #1 — `pushed_at` staleness miscalculation

- **Found:** during the original build, by running `verify_pull.py` (an
  independently-written second code path) against the primary pull and
  comparing results, not by code review.
- **What was wrong:** staleness was computed from the repo object's
  `pushed_at` field, which reflects a push to *any* branch. A bot branch,
  a docs branch, or a stray PR branch getting touched could make a
  genuinely stalled project look active.
- **Fix:** query the commits endpoint scoped to the repo's actual default
  branch (`get_default_branch_last_commit`), the same signal `git log` on
  that branch would show.
- **Regression test:** staleness is now computed exclusively from the
  default-branch commit lookup; `tests/test_github_pull.py`'s
  `CommitLookupTests` class covers the shape and content of that lookup.
- **Full account:** `METHODOLOGY.md`.

## Incident #2 — MCP error-message sanitization

- **Found:** during the original build, by connecting a real `mcp`
  `ClientSession` to `mcp_server.py` and calling every tool, including
  with a deliberately invalid input.
- **What was wrong:** `get_project_status` raised a `ValueError` with a
  specific, useful message (which repos ARE valid) on an unknown repo.
  MCP's default exception handling sanitizes error details before they
  reach the client, for legitimate security reasons, so the real message
  never arrived — the agent saw only a generic "Error executing tool"
  string, useless for recovery.
- **Fix:** an unknown repo is an expected, foreseeable input, not an
  exception-worthy bug, so it's returned as a normal structured value
  (`{"error": ..., "known_repos": [...]}`) instead of raised.
- **Regression test:** `tests/test_agent_eval.py`'s
  `test_unknown_repo_surfaces_structured_error_not_a_crash` re-runs this
  exact scenario through the full agent loop, not just a direct tool
  call, added when the eval harness was built (see incidents #5 and #6
  below, found by that same harness).
- **Full account:** `MCP_VERIFICATION_LOG.md`.

## Incident #3 — partial-failure false "active" status

- **Found:** during the Phase 7 gap-remediation pass, while adding input
  validation, by running the pull repeatedly under real (flaky) network
  conditions rather than trusting the validation logic because it read
  correctly.
- **What was wrong:** when the commit-lookup call failed partway through
  a pull (a rate limit hit at exactly that point, distinct from the
  initial repo call succeeding), `last_commit_date` came back `None`, and
  the old staleness check (`staleness_days is not None and
  staleness_days > THRESHOLD`) silently evaluated to `False` — reporting
  a project with no actual data as falsely "active." A rate-limit hiccup
  could make a genuinely dead project look healthy.
- **Fix:** a failed commit lookup now returns no result for that repo at
  all, the same honest "no data" path a 404 already took, rather than a
  result that looks fine but rests on nothing.
- **Regression test:**
  `test_partial_failure_on_commit_lookup_does_not_report_false_active` in
  `tests/test_github_pull.py`.
- **Full account:** `GAP_ANALYSIS.md` §6.

## Incident #4 — live test suite's own rate-limit race condition

- **Found:** during the same Phase 7 pass, running the live integration
  tests repeatedly rather than once.
- **What was wrong:** an earlier version checked GitHub's rate-limit
  quota once, upfront, and skipped the live tests if it was too low.
  Running it repeatedly proved that check unreliable — the quota changed
  in the seconds between the check and the actual pull, because this
  environment's shared IP is under enough concurrent external load for
  that race to be real, not theoretical.
- **Fix:** check the quota *after* the attempt and diagnose a `None`
  result against quota at that point, rather than predicting from a stale
  reading taken moments earlier.
- **Regression test:** the live integration tests themselves now follow
  this pattern; there is no separate unit test for a race condition in a
  live-network test, which would itself require faking network timing,
  correctly judged not worth the complexity here.
- **Full account:** `GAP_ANALYSIS.md` §6.

## Incident #5 — `agent_client.py` read a field name the installed SDK doesn't expose

- **Found:** October 2026, within seconds of actually running
  `tests/test_agent_eval.py` for the first time — the new eval harness's
  very first real exercise of the agent loop against a real
  `mcp_server.py` subprocess.
- **What was wrong:** the MCP-to-Claude tool-schema conversion read
  `t.inputSchema` (camelCase) off each tool definition. The installed
  `mcp` SDK (`mcp==2.3.0`, satisfying this project's own `requirements.txt`
  pin of `mcp>=2.0`) exposes this as `input_schema` (snake_case) — confirmed
  directly against `Tool.model_fields`, not assumed. `MCP_VERIFICATION_LOG.md`
  genuinely had confirmed `inputSchema` during the original build's
  verification run; the wire protocol's JSON field is camelCase, but the
  Python SDK's own attribute name for it isn't guaranteed to stay that way
  release to release, and apparently didn't.
- **Why this matters precisely:** this means the "written correctly
  against the documented SDK APIs" claim in `agent_client.py`'s own
  docstring and `SOW.md` §5 was true when written and had quietly gone
  stale by the time of this check — not a fabrication, a real instance of
  why "written correctly" and "verified to still work" are different
  claims, the exact distinction this project has insisted on everywhere
  else. This is precisely the kind of drift an unrun, unverified code
  path accumulates silently, and precisely why closing the eval-harness
  gap mattered even without a live model.
- **Fix:** read `t.input_schema`, with an explanatory comment at the call
  site naming the exact SDK version this was checked against and why it
  changed.
- **Regression test:** every test in `tests/test_agent_eval.py` exercises
  this line, since every test drives the real `list_tools()` →
  tool-schema-conversion path.

## Incident #6 — `list_projects()` results silently truncated to one project

- **Found:** October 2026, immediately after fixing incident #5, while
  getting the eval harness's first assertions to pass.
- **What was wrong:** `list_projects()` returns a Python list of five
  project rows. The installed `mcp` SDK serializes a list return value as
  one `TextContent` block *per list item*, not one block holding a JSON
  array of all five. The tool-result handling in `agent_client.py` read
  only `result.content[0].text`, silently discarding content blocks 1
  through 4 — meaning a live agent asking "what's the state of things?"
  (the exact example question in this file's own docstring) would have
  seen exactly one of five tracked projects, with no error, no warning,
  and no way to know data was missing.
- **Why this is the most consequential of the six:** this is the only one
  of the six incidents that would have produced a confidently wrong
  answer rather than a crash or an honest failure. Everything else in
  this project's design philosophy is built around "silence should never
  resolve to looking healthy" (incident #3's own words) — this bug was
  exactly that failure mode, just in the one layer (`agent_client.py`)
  that had never been run before this harness existed.
- **Fix:** join every content block's text (newline-separated) instead of
  reading only the first. Claude reads tool results as plain text, not
  parsed JSON, so several JSON objects in sequence is a correct, readable
  result, not a malformed one.
- **Regression test:**
  `test_single_tool_call_then_final_answer` in `tests/test_agent_eval.py`
  explicitly asserts all five fixture repos are present in what reaches
  the model, by name, not just that *a* result arrived.

---

## Addendum: found by the first hosted runs (not renumbered into the six)

Kept apart from the six above on purpose, and not renumbered, because
the "six" is quoted across other documents; the counts get reconciled in
one pass once a full day of hosted runs is in. Part A is a test-suite
defect. Parts B, C and D are defects in `pulse_scheduler.py`, the same
kind as the six.

### A. The live CI test (test-suite defect)

- **Found:** the first push to a real GitHub repository. The `Tests`
  workflow failed on all three Python versions (3.10, 3.11, 3.12) with
  the same single failure; the other 91 tests passed on each.
- **What was wrong:** `test_live_repo_with_no_ci_configured` asserted that
  `octocat/Hello-World` has no CI, so `ci_status` should be
  `no_ci_configured`. The runner got `success`. That claim was about a
  third-party repo this project does not control, and nothing pinned it:
  in this build's recorded runs the live tests that need a result were
  skipped (a rate limit, then this sandbox's network policy), so the
  assertion was not being exercised. The product code behaved correctly, since `get_ci_status` reports any
  check run or commit status GitHub returns for the latest commit.
- **Fix:** replaced it with `test_live_repo_returns_a_valid_ci_status`,
  which asserts the real response falls inside the documented status
  vocabulary. The specific "no CI configured" outcome stays covered by
  the mocked tests, where the inputs are controlled.
- **Why it's worth recording:** the live tier was designed to check "the
  mocked assumptions match reality." This is that tier doing its job. It
  also shows the cost of a test that skips whenever its precondition
  isn't met: the suite reported green while one of its three live
  assertions was wrong.
- **Also learned, same run:** the other two live tests
  (`test_live_dormant_repo_is_stale`,
  `test_live_nonexistent_repo_returns_none`) executed on the runner and
  passed. This was the first run recorded in this project in which all
  three live tests executed with none skipped.

### B. A first observation read as a change (scheduler defect, observed live)

- **Found:** two manual runs of the hosted `unattended-pull` job, four
  minutes apart. Run #3 (checked at 16:02:31Z) decided `baseline_due` and
  pulled 5/5 repos. Run #4 (16:06:28Z) decided
  `priority_change_detected`, listing **all five** tracked repos as
  changed, with the detail "only 0.1h since the last pull". Five repos
  cannot all change in four minutes.
- **What was wrong:** with no saved ETag, GitHub has nothing to compare
  against and must answer 200 whether or not anything changed.
  `check_repo_changed` returned True for that 200, so the first check of
  every repo always read as a change and triggered an extra pull right
  after the baseline pull.
- **Fix:** a first observation now records the ETag and returns False; a
  change can only be reported against a prior ETag. Regression tests:
  `test_first_observation_records_etag_and_is_not_a_change` and
  `test_second_check_after_first_observation_detects_a_real_change`.
- **What the same run proved:** run #4 read run #3's saved log
  (`pulls_in_last_24h: 1`, `last_pull_at: 2026-11-25T16:02:31Z`), so
  state persisting between separate hosted runs works as designed.
- **Cost of the bug:** one extra pull, within the cap of 3 per 24h. Two
  pulls are on record for 2026-11-25.

### C. The watched resource was too noisy (scheduler design flaw, reasoned, not observed)

- **Found:** by rereading the check after run #4, not by watching it fail.
- **What was wrong:** the change check watched the plain repo record
  (`GET /repos/{owner}/{repo}`), whose ETag flips on star counts, issue
  counts and descriptions as well as code. On busy repos that is many
  times a day, so priority pulls would have fired on nearly every tick up
  to the cap of 3 a day, against a requested cadence of 1 a day unless the
  author updates the code. The earlier "safe by construction" wording
  covered correctness (a false positive never produces a wrong answer) and
  missed that it defeated the cadence.
- **Fix:** watch `GET /repos/{owner}/{repo}/commits?per_page=1` instead
  (the default branch's commit list), and prefix cache keys with
  `commits:` so ETags saved under the old scheme are never compared
  against the new resource.
- **Not yet verified live:** that GitHub answers 304 on that endpoint
  when nothing has changed. The per-tick decision log records which repos
  were seen as changed, so the first quiet ticks will show it.

### D. The commit-list ETag changed with no new commit (scheduler defect, observed live)

- **Found:** the first two scheduled ticks of the hosted repo. Tick 1
  (checked 2026-11-25T23:57Z) decided `not_due`. That was the first
  observation of the `commits:` keys, so it carried no information about
  whether GitHub answers 304. Tick 2 (2026-11-26T07:26Z) decided
  `priority_change_detected` and listed **all five** repos as changed,
  including `octocat/Hello-World`, a repo the pull itself reports as
  5,377 days since its last commit. The extra pull was the third in the
  trailing 24h (16:02Z, 16:06Z, 07:26Z), so the cap of 3 is what stopped
  any further pulls; the intended cadence of one a day was not met.
- **Evidence:** the stored ETag for every `commits:` key differs between
  the persist commits after tick 1 and tick 2 (`etag_cache.json`). The
  `last_commit_date` recorded by the pulls at 2026-11-25T16:06Z and
  2026-11-26T07:26Z is identical for all five repos; only the
  days-since count moved by one.
- **What was wrong:** the check treated "ETag differs" as "something
  landed on the default branch". The ETag differed with no change visible
  in the recorded data.
- **Cause: not established.** Candidates, all unverified: the ETag varies
  with the credential (each Actions run uses a different `GITHUB_TOKEN`);
  the endpoint does not honour the conditional request; some other
  response detail changes. I could not probe the endpoint from the build
  sandbox (its proxy returns 403 for api.github.com), so none of these
  was tested.
- **Fix:** stop depending on the ETag. Each tick fetches the newest commit
  and compares its SHA with the SHA saved last tick (`sha:` cache keys;
  earlier keys ignored, so each repo has one first observation). This
  removes the unexplained variable rather than explaining it. Regression
  tests: `test_etag_churn_with_same_commit_is_not_a_change`,
  `test_change_is_reported_once_then_quiet`,
  `test_values_saved_under_earlier_schemes_are_ignored`, plus
  `FetchLatestShaTests` for the HTTP wrapper.
- **Not yet verified live:** that the SHA version reports "no change" on a
  quiet tick. Unit tests pin the logic; only a hosted tick shows it holds
  against GitHub.
- **What the same ticks proved:** state persisted across separate
  scheduled runs (tick 2 read tick 1's saved cache), the persist step
  committed on each tick, and the hard cap was in force with three pulls
  in the window.
- **Unreconciled:** the `checked_at` values (23:57Z, 07:26Z) fall before the
  `0 */8 * * *` slots at 00:00Z and 08:00Z by roughly 3 and 34 minutes.
  Not explained here.

---

## What this log is, and isn't

Six real defects across this build, zero of them hypothetical, all six
closed with a fix and a permanent regression test. This is not evidence
that the system is now defect-free — `GAP_ANALYSIS.md` names a long list
of things that have never been exercised at all (concurrency, real
scale, a hosted CI run, a live model actually calling these tools). It is
evidence of a discipline: every time a piece of this system was actually
run for the first time, under real conditions, something was found — and
the response each time was a fix plus a test that makes the same mistake
structurally harder to reintroduce, not a patch and a hope. Incidents #5
and #6 are the clearest illustration of why that discipline matters:
both lived in the one layer (`agent_client.py`) that had sat untested
the longest, and both were found the first hour anything actually
exercised it.
