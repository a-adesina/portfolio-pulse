# Operational Incident Log — Portfolio Pulse

**Document type:** A log of things that went wrong during actual,
unattended *operation* of this system — not during its build. This is
deliberately a separate file from `INCIDENT_LOG.md`, which records the
six defects this project's own build-time verification work found and
fixed before anything ran unattended. Conflating the two would overclaim
what either one is: `INCIDENT_LOG.md` is "we tested this and found real
bugs before shipping it"; this file is "this ran for real, unsupervised,
and here's what happened when it did." Different claims, kept in
different files on purpose.

**Current status: two entries, from the first hosted days.** The file
was created empty, and stayed empty until the project was hosted in a
public GitHub repository (25 Nov 2026) and its scheduler had run on real
ticks. Both entries below were found by the owner reading the scheduler's
decision log, not by an alert, and no alert fired for either. That is
itself a finding: `pulse_alert.py` watches for crashed, failed and
repeatedly degraded runs, and a run that pulls when it should not have is
none of those. No new alert condition has been added for it. The dashboard's
run record now shows the decision history, which makes the pattern visible
to anyone looking, not alerted on.

Both entries have a fuller build-side account in `INCIDENT_LOG.md`
(addendum parts B and D), which is where the fix and its tests are
described. Nothing was backfilled: each entry below is tied to a
timestamped decision in `pulse_run_log.jsonl`.

**What belongs here, once real operation starts:** anything `pulse_alert.py`
actually fires on during a real unattended run (a total pull failure, a
degraded run, a repeated-failure pattern), plus anything else that goes
wrong in operation that the alerting logic didn't anticipate — those are
arguably the more valuable entries, since they'd be gaps in the
*monitoring* itself, not just the pipeline. Each entry should follow
`INCIDENT_LOG.md`'s format for consistency: what happened, how it was
found (which for this file will always be "a real alert fired" or "a
real user reported it," not "caught during build-time testing"), the
fix, and whether a new test or alert condition was added to catch a
repeat.

---

## Entries

### OP-1. An early pull decided on the first observation of each repo (2026-11-25 16:06Z)

- **What happened:** four minutes after the first baseline pull, the
  scheduler decided `priority_change_detected` with all five repos listed
  as changed, and pulled again (a second pull inside the first 24 hours).
- **How it was found:** the owner read `scheduler_last_decision.json` and
  the run log after the second run. No alert fired.
- **Cause:** the first check of a repo always returns a full response, and
  the check read that as a change. See `INCIDENT_LOG.md` part B.
- **Fix and test:** a first observation now records state and reports no
  change. Regression test added.
- **Alert or monitoring change:** none.

### OP-2. A second false early pull, on a scheduled tick (2026-11-26 07:26Z)

- **What happened:** the scheduler decided `priority_change_detected` with
  all five repos changed, including `octocat/Hello-World`, whose last
  commit is from 2012, and pulled. That was the third pull inside 24
  hours; the cap of 3 stopped anything further, but the intended cadence
  of one pull a day was not met.
- **How it was found:** the owner read the decision file and noticed the
  dormant repo in the changed list. No alert fired.
- **Cause:** the commit-list ETag changed on every repo with no new
  commit visible in the pulled data. The reason the ETag changed was not
  established. See `INCIDENT_LOG.md` part D.
- **Fix and test:** the check now compares the newest commit SHA instead
  of the ETag. Regression tests added. Three quiet ticks have followed
  with no false changes (2026-11-26 18:04Z, 2026-11-27 06:27Z and 17:48Z).
- **Alert or monitoring change:** none. A decision-history view was added
  to the dashboard.
