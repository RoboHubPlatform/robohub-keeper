---
id: ADR-0002
title: Run applications from releases, switched in one rename and backed out on a failed health check
status: proposed
date: 2026-11-13
requirements: [KEEP-0005, KEEP-APPS-0009, KEEP-APPS-0010, KEEP-APPS-0011, SYS-0014]
supersedes: []
superseded_by: []
---

# Run applications from releases, switched in one rename and backed out on a failed health check

## Context

An application built from a folder ran the folder's own build. A rebuild — or a
build that failed half-way — changed what was running, and there was nothing to
go back to.

## Decision

A redeploy builds the folder, copies the program, `module.yml`, `static/` and
what `deploy.files` names into a new release
`apps/<name>/releases/<version>-<time>`, and points `current` at it with one
rename; the unit runs `current`. The release that was in use is remembered. When
the new release cannot be restarted or does not answer `/healthz` within 40
seconds, it is marked `.failed`, the previous one is put back and restarted, and
the job ends failed saying so. Roll back puts the release made before the one in
use back, by the time in its name. The three newest releases are kept, never the
one in use or the one before it. The keeper deploys itself the same way, from
its deploy script.

## Consequences

- Editing or rebuilding a checkout changes nothing that runs until a redeploy.
- A bad build leaves the application on the release that worked.
- Every redeploy copies the program; three releases per application are kept on
  disk.
- A published package (`origin: registry`) is not released this way: it runs
  where it was installed, and going back is selecting the older version.
