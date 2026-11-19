---
id: ADR-0001
title: A catalogue of applications, run as systemd user units the keeper writes
status: proposed
date: 2026-11-13
requirements: [KEEP-0004, KEEP-APPS-0001, KEEP-APPS-0004, SYS-0013]
supersedes: []
superseded_by: []
---

# A catalogue of applications, run as systemd user units the keeper writes

## Context

Until 0.8.0 the keeper found applications by scanning folders and asking
`rho module list` on every page, and each application was started by a deploy
script of its own. What the keeper ran depended on what happened to be on disk,
a page was slow, and a moved folder or a changed port left a unit that started
the wrong thing.

## Decision

What the keeper runs is a catalogue, `installed.yml` in its state folder: one
record per application with its origin, location, version, port and unit. It is
adopted from what is on the machine on the first start and changed afterwards
only by Install, Uninstall and an update. Each catalogued application runs as a
systemd user unit the keeper writes from the application's manifest and its
record — dependencies as `After=`/`Wants=`, `Restart=on-failure`, its
environment in an owner-only `app.env` — and writes again whenever the unit no
longer says what it would write. State comes from systemd and the application's
`/healthz`; the log is the unit's journal.

## Consequences

- Pages and the API read one file; nothing is scanned per request.
- systemd restarts a failed application and orders starts, so the keeper needs
  no supervisor loop of its own, and the applications keep running when the
  keeper is stopped.
- The keeper depends on a user systemd (`systemctl --user`, lingering), which a
  machine without systemd does not have.
- A unit edited by hand is overwritten at the next start.
