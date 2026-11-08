# The RoboHub keeper

A local dashboard for the RoboHub ecosystem.

## What it does

The keeper is a web-based admin panel that shows the ecosystem's registry,
which modules are installed, and what the machine needs to run them. It helps
with the installation process: a user clones only the orchestrator, and the
keeper retrieves the elements they need.

## Building

```sh
rho build applications/keeper
```

The documentation the keeper serves is built by the documentation site, which
collects every module's pages into one tree:

```sh
rho build applications/docsite
./applications/docsite/build/docsite
```

## Running

```sh
./applications/keeper/build/keeper
```

The keeper serves the built site, and reads the tree it was built from. A keeper
that is told where the tree is — `RHO_DOCS_ROOT` and `RHO_DOCS_TREE` — builds a
site of its own instead, and `RHO_SITE_TITLE` says what the site calls itself.

The keeper is also reachable through the orchestrator's own command:

```sh
robohub keeper
```

## Applications

The keeper lists the applications on the machine at `/applications`, and the
`Applications` entry in the left menu goes there. An application is a module
whose manifest declares an `application` block:

```yaml
application:
  kind: keeper-hosted
  title: RoboHub Mesh
  route: /mesh
  port: "8478"
  command: mesh
```

Two kinds are recognized. `keeper` is the dashboard itself: it is listed so the
page is complete, but it cannot be started, stopped or removed from itself.
`keeper-hosted` is an application with its own listener that the keeper can
start and stop. A module without the block — a documentation site, a component,
a library — is not an application and the registry does not show it.

An application is discovered from `applications/` on every request, so one
built beside the keeper appears without a rebuild. **Install** clones a git URL
into `applications/<name>`, or registers a folder that already exists on the
machine; a registered folder stays where it is and its path is kept in
`~/.rho/keeper/applications.txt`. **Uninstall** removes a cloned folder, or only
the registration of an external one.

Each row can be opened in a new page, started and stopped, and added to or
removed from the keeper's left menu. A pinned application is a sub-item under
**Applications**, beside the registry link it was added from. The menu selection
is kept in `~/.rho/keeper/menu.txt`; the entries are read whenever a page is
rendered. A started application is also told the keeper's port, so it can offer
a **Go to Keeper** link back. `RHO_KEEPER_STATE_DIR` names another state
directory, which is what the tests use.

`rho build applications/mesh` builds the Mesh application, and the keeper can
start it from its registry row. Its own guide is the Mesh module's
documentation.

## Registry

`/modules` is the RoboHub registry: the repositories this orchestrator publishes
and tracks, with their versions and whether they are installed.

## Menu

The left menu keeps one entry per top-level concern: Home, Registry,
Applications, Docs and System. **Applications** opens the applications list and
also carries the current application, the pinned applications, **App modules**
and **Plugins** as sub-items, because those are things an application carries
rather than separate top-level destinations.

## App modules

`/app-modules` lists the reusable modules in `modules/registry.yml`: each row
shows the module's title, category and version, and can remove it. **Install a
module** adds one from a git URL or a folder. A module has no port or process of
its own, and no single host: every application that includes it serves its
routes on its own router, on that application's port and workspace.

## Plugins

`/plugins` lists the plugin registry in `plugins/registry.yml`. A row shows the
plugin's kind, transport and whether the keeper has it enabled; a path whose
folder is gone is marked missing. The keeper can install a plugin from a git URL
or a folder, remove one, enable or disable it for itself, and send a test alert.

The keeper's own `module.yml` names its plugins and settings. The dashboard's
override in `~/.rho/keeper/plugins.txt` changes only this installation, leaving
the manifest the application was installed with intact. Alerts raised by the
application registry — an application that fails to start, stop or install —
go through the same dispatcher.

## Logging

The keeper's `project.yml` asks the backend for the `logemit` port and the app
imports `rho.log`. Records on standard error carry a UTC timestamp, the level
and the subject:

```text
[2026-11-01T12:48:27.695Z] [info] [keeper] started application mesh on port 8478
[2026-11-01T12:49:28.534Z] [info] [keeper] added mesh to the keeper menu
```

`RHO_LOG_FILE` also appends those records to a file. The generated HTTP server
logs requests with its own date/time.

## Authentication

Keeper is the RoboHub authorization server. `/auth/login` validates the master
token, opens a keeper session, and mints a short-lived ES256 ticket for the
requesting application. The admin UI is behind that session. Tickets are
verified by the application with Keeper's public key; a ticket carries the
application audience, redirect URI, one-use id and a 30-second lifetime.

## Artifact updates

A signed artifact placed in `~/.rho/keeper/incoming/` is used by **Update** when
it is the newest file for that application. Keeper verifies it, extracts it to
`~/.rho/keeper/artifacts/<name>/<version>/`, points `build/<command>` at the new
entrypoint, restarts the service, and checks its health endpoint. A failed
health check restores the previous target and restarts again.

Set `ROBOHUB_ARTIFACT_PUBKEY` to the base64 Ed25519 public key that must sign
artifacts. Checksum-only verification is available for a development machine by
setting `ROBOHUB_ARTIFACT_ALLOW_UNSIGNED=1`, but a production keeper should pin a
key.

## Remaining OTA work

Keeper deploys host services from verified staged artifacts. Remote host
rollout, firmware OTA delivery through Mesh, ESP32 A/B confirmation, and
target-declared rollback remain outstanding; a target without a rollback-capable
bootloader is not offered remote OTA.

## Node enrollment

Create a one-time token on the keeper host:

```sh
rho bootstrap token -device garden-01 -project default -area 1 -node 7
```

The token lands in `~/.rho/keeper/enrollment.tokens`. A node runs:

```sh
rho bootstrap init -config /etc/robohub/provisioning.json -token <token>
```

The node generates its instance UUID and Ed25519 key locally, posts the public
key and token to `POST /api/enroll`, and stores the issued credential as a
`0600` file. Keeper keeps the node record under `~/.rho/keeper/nodes/` and marks
the token used. A reused or expired token is refused.
