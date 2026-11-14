# RoboHub Keeper

RoboHub's supervisor and front door: it signs people in, installs the applications
and runs them as systemd user units from releases, and serves them under its own
origin at `/app/<name>/`. It listens on `127.0.0.1:19090`.

The full guide is [docs/index.md](docs/index.md).

This repository sits beside the orchestrator, `robohub`, whose registry and shared
modules it reads; `ROBOHUB_ROOT` says where that is when it is somewhere else.

## Building and running

```sh
rho build .
ROBOHUB_ROOT=../robohub ./build/keeper     # by hand, on 127.0.0.1:19090
./scripts/deploy-keeper.sh                 # as the robohub-keeper user service
```

`RHO_HTTP_ADDR` sets the address a keeper started by hand listens on;
`KEEPER_LISTEN` the one the deployed service does (`127.0.0.1` unless told).

## What it does

- Home: every installed application as a card, with an inspector to start, stop,
  restart, build, redeploy and roll it back, and its journal and environment
- Install from the Rho registry by name, from a git URL or from a folder, after
  showing what the application needs from the machine
- A catalogue of what it runs, `~/.rho/keeper/installed.yml`, and a release per
  redeploy under `~/.rho/keeper/apps/<name>/releases/`
- Sign-in for every application: people with roles (admin, operator, viewer) and
  grants per application, tickets signed with the keeper's key
- The applications behind its own origin, `/app/<name>/` (setting
  `keeper.proxy_apps`)
- Integrations it runs for the applications, starting with the MQTT broker
- Node enrollment and the registry of issued node identities
- The documentation site

## Environment

| Variable | What it says |
| --- | --- |
| `ROBOHUB_ROOT` | the orchestrator's checkout (default: beside this one) |
| `RHO_HTTP_ADDR` | where a keeper started by hand listens (`127.0.0.1:19090`) |
| `RHO_KEEPER_STATE_DIR` | another state folder instead of `~/.rho/keeper` |
| `ROBOHUB_APPS_HOME` | where applications installed from git are cloned (`~/.rho/apps`) |
| `RHO_DOCS_ROOT`, `RHO_DOCS_TREE` | a documentation tree the keeper builds a site of its own from |
| `RHO_SITE_TITLE` | what that site calls itself, when it should not use its default |
| `ROBOHUB_ARTIFACT_PUBKEY` | the Ed25519 key a staged artifact must be signed with |

## Tests

```sh
rho test .
```

The Rho unit suite checks the registry's name and list helpers; the smoke suite
builds the keeper, starts it on loopback and walks the applications page over HTTP:
the keeper row, installing and uninstalling an external application, pinning it to
the menu, refusing to remove the keeper, releases, rollbacks and a stale job.
