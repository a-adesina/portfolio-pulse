# Pull Verification Report

Run 2026-09-23 13:01 UTC. Independent check via `git clone --depth 1`, zero GitHub API calls. Works even when api.github.com's rate limit is fully exhausted.

Post-fix status: the primary pull now reads the same default-branch commit signal this verifier checks, via a different code path (REST API vs. git protocol). A tight match is the expected normal case. A divergence here now points to something new, API propagation lag, a caching quirk, or a genuine bug, worth investigating on its own terms rather than assumed benign.

| Repo | Recorded last_commit_date | Recorded days | git log last commit | git log days | Result |
|---|---|---|---|---|---|
| tiangolo/fastapi | 2026-09-19T08:00:00Z | 4 | 2026-09-01T20:59:53+00:00 | 21 | DIVERGES |
| pallets/flask | 2026-09-08T09:40:41Z | 15 | 2026-09-08T09:40:41-07:00 | 14 | match |
| psf/requests | 2026-08-02T09:00:00Z | 52 | 2026-09-21T13:22:33-07:00 | 1 | DIVERGES |
| github/gitignore | 2026-09-11T09:15:42Z | 11 | 2026-09-11T09:15:42-07:00 | 11 | match |
| octocat/Hello-World | 2012-03-06T15:06:50Z | 5313 | 2012-03-06T15:06:50-08:00 | 5313 | match |

**At least one repo diverged from the independent check.** See the divergence note above before treating this as a pull error, then investigate the specific repo if the gap isn't explained by it.