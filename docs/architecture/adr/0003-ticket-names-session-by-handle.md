---
id: ADR-0003
title: A ticket names the keeper session by a derived handle
status: proposed
date: 2026-11-14
requirements: [KEEP-AUTH-0006, KEEP-AUTH-0008, SYS-0009]
supersedes: []
superseded_by: []
---

# A ticket names the keeper session by a derived handle

## Context

An application ends its own session when the keeper session it came from ends,
so its ticket has to say which keeper session that is. Until 0.9.8 the ticket
carried the session id itself — the value of the keeper's `keeper_session`
cookie. An application, or anything that read its ticket, could present that
value back to the keeper as the admin.

## Decision

A ticket carries a handle, `HMAC-SHA256(session id, "rh-session1")` as 64 hex
digits, and `GET /auth/session/<handle>` answers 200 while that session stands
and 404 otherwise. The session id is never accepted as a handle, and the cookie
value never leaves the keeper.

## Consequences

- Holding a ticket, or a list of handles, gives no way into the keeper.
- Checking a handle walks the session file and derives each session's handle;
  applications ask at most once a minute, so the cost is small.
- Tickets minted before the change named the raw id and stop matching; their
  applications' sessions end and sign in again.
