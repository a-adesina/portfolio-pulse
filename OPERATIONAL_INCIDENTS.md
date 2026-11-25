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

**Current status: empty, by design, not by oversight.** As of this
file's creation, Portfolio Pulse has not yet accumulated a real
unattended run history — the `schedule:` trigger in
`.github/workflows/tests.yml` exists, but needs this project hosted in a
real GitHub repository before it can actually fire and produce one. An
incident log cannot honestly contain incidents that haven't happened;
backfilling this with plausible-sounding entries would be exactly the
kind of fabrication this project's documentation has avoided everywhere
else. See `MATURITY_ASSESSMENT.md`'s "Path to Tier 5," step 4, for
exactly what has to happen before this file's first real entry can be
written.

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

*(none yet — see "Current status" above)*
