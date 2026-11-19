---
id: ADR-0004
title: Programs the keeper runs take their arguments one per line, and secrets only in owner-only files
status: proposed
date: 2026-11-13
requirements: [KEEP-0013, KEEP-AUTH-0011, KEEP-AUTH-0013, SYS-0033]
supersedes: []
superseded_by: []
---

# Programs the keeper runs take their arguments one per line, and secrets only in owner-only files

## Context

Much of what the keeper does is done by other programs: `rho auth` mints tickets
and hashes passwords, `rho build`, `git`, `systemctl`, `rho doctor`. Their
arguments come in part from requests — a name, a URL, a password. A command line
built as a string lets a value become an option or a second argument, and a
secret on a command line is readable by every user of the machine.

## Decision

Every program the keeper runs is given its arguments one per line
(`rho_exec_args`), so each value is exactly one argument; a value with a line
break, or one starting with `-` where it would be read as an option, is refused
before the program runs. A secret — a password, a client secret, a ticket being
read back — passes only through a file in an owner-only folder under the keeper's
state, created for the moment and removed at once; no secret is written to a
report file. The state folder itself is owner-only.

## Consequences

- A request cannot add an option or an argument to a command the keeper runs.
- Each secret hand-over costs a file write and a removal.
- A value that legitimately starts with `-` cannot be passed in a position where
  it would be read as an option.
