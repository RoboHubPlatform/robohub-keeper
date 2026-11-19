---
id: ADR-0005
title: The Developer section changes files only through rho req, and commits locally without pushing
status: proposed
date: 2026-11-19
requirements: [KEEP-0012, KEEP-DEV-0001, KEEP-DEV-0004, KEEP-DEV-0005, SYS-0041]
supersedes: []
superseded_by: []
---

# The Developer section changes files only through rho req, and commits locally without pushing

## Context

The keeper is where the maintainer already works, so it is where requirements
and decisions are browsed and edited day to day. But the files have one
authority, `rho req`, which CI runs too; a second writer of the same YAML would
drift from it. And the maintainer's checkouts carry work in progress, which a
commit made from a web page must not sweep up or publish.

## Decision

The section reads everything from `rho req … --tsv` and changes every file with
the matching `rho req` command — `new`, `edit` with only the changed fields,
`set-status`, `adr new`, `adr set-status`, `adr supersede` — showing the tool's
refusal on the form. It commits only the files it changed under
`docs/requirements/` and `docs/architecture/`: on a feature branch with
`git commit -- <files>`, on the default branch onto `requirements/<date>`
through a temporary index, leaving the working copy and its index as they were.
It never pushes.

## Consequences

- The keeper and `rho req check` cannot disagree about what a file says.
- The section needs `rho req` installed, and says how to install it when it is
  not.
- Publishing and merging remain the maintainer's own steps outside the keeper.
- Approvals made in the keeper stand only if CI accepts the committing identity,
  which the section warns about.
