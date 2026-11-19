---
id: ADR-0006
title: Applications are issued broker users under the topic roots they declare
status: accepted
date: 2026-11-20
requirements: [KEEP-PROV-0006, KEEP-PROV-0007, KEEP-PROV-0008, KEEP-0010, SYS-0028, SYS-0032, SYS-0033, SYS-0069]
supersedes: []
superseded_by: []
---

# Applications are issued broker users under the topic roots they declare

## Context

The keeper runs the MQTT broker (robohub-mqtt) and writes its users from three
places (KEEP-PROV-0005, `mqtt_write_files` in `src/keeper/integrations.rho`):

- the keeper itself, which reads everything to show it;
- every application that binds `robohub.bus`, with a random password in its
  workspace and the topics its manifest's `bus:` block names;
- every device an admin adds by hand on the MQTT page, limited to
  `readwrite <prefix>/#`, its password shown once.

robohub ADR-0017 decides that Mesh runs Zigbee2MQTT for a Zigbee coordinator
plugged into one of a mesh's boards — this machine or another host board such as
the UNO Q. Zigbee2MQTT is an MQTT client and needs a broker user. None of the
three fits:

- **As Mesh's own user** it would hold Mesh's whole access (every device family's
  topics), and on another board it would carry Mesh's credential off this
  machine.
- **As an admin-added device** it works, but every coordinator becomes a manual
  step in the keeper, with a password copied by hand into Mesh, and nothing ties
  the user to the mesh that uses it: a removed mesh leaves a live credential.
- **As a keeper integration** (a service the keeper runs) it would not be a broker
  user at all today — `mqtt_write_files` skips integrations — and it would be one
  per machine, not one per mesh.

## Decision

1. **An application declares the topic roots it may have users issued under**, in
   its manifest, beside the topics it uses itself:

   ```yaml
   bus:
     publish: [...]
     subscribe: [..., zigbee/#]
     issue: [zigbee]
   ```

2. **It asks the keeper for a user** with `POST /api/v1/bus/users`
   (`{"name": "...", "prefix": "zigbee/<mesh>/<coordinator>"}`), on a loopback
   connection, authenticated by its own broker password —
   `Authorization: Bus <app>:<password>` — the secret the keeper already gave it
   (`ROBOHUB_BUS_PASSWORD_FILE`). No new credential is introduced to prove who
   the application is, and the request never leaves the machine.
3. **The keeper confines the user**: the prefix must be a plain topic (no `+`, `#`,
   empty level, space or newline) whose first level is one the manifest lists
   under `bus.issue`; the user is named `<app>-<name>`, so two applications can
   never be issued the same user, and is allowed `readwrite <prefix>/#` only. Its
   password is random, kept owner-only under `services/mqtt/issued/`, and answered
   once, with where the broker is reached (KEEP-PROV-0007).
4. **Issued users are visible and go with their application**: listed on the
   MQTT Clients tab with the issuing application and prefix, removable by the
   application (`DELETE /api/v1/bus/users/<name>`), and removed with it.
5. Issuing, removing and refusing are keeper events (`bus.user-issued`,
   `bus.user-removed`), and the broker reloads its users on SIGHUP without
   dropping connections, as it does today.

## Consequences

- Mesh can bring up a coordinator without a manual step in the keeper, and a
  coordinator's credential reaches only its own `zigbee/<mesh>/<coordinator>/#`.
- The ACL gains a fourth source; `mqtt_write_files` reads `services/mqtt/issued.txt`
  (`<app>|<name>|<prefix>`) beside `devices.txt`, and drops lines whose
  application is no longer in the catalogue or no longer declares the root.
- An application compromised on this machine can create users only under the
  roots its manifest declares; the manifest is maintainer-owned (CODEOWNERS).
- A remote client still needs the broker opened to the network by an admin
  (SYS-0032); the keeper does not open it on an application's behalf. The
  traffic between boards is plain MQTT with a password, as it is for Tasmota
  devices today; TLS on the broker is a decision of its own.
- `Authorization: Bus` is a new scheme accepted only on loopback and only by
  these two routes; the keeper's session and token checks are unchanged elsewhere.

## Alternatives considered

- **A keeper OAuth scope (`bus:issue`) on Mesh's client token** — the keeper is
  the issuer (robohub ADR-0003) and this would fit its model, but Mesh's client
  credentials are for signing people in, not for acting as itself towards the
  keeper; it adds a client-credentials grant for one call. Rejected for now; the
  broker password is already the application's identity on the bus.
- **The admin adds each coordinator as a device** — no new code, but a manual,
  error-prone step per coordinator and a credential tied to nothing. Rejected.
- **Let integrations be broker users** (fixing the skip in `mqtt_write_files`) —
  needed if the keeper ever runs a broker client itself, but it gives one service
  per machine, which does not fit a coordinator per mesh. Not done here.
