# The RoboHub keeper

A local dashboard for the RoboHub ecosystem.

## What it does

The keeper is a web-based admin panel that shows the ecosystem's registry,
which modules are installed, and what the machine needs to run them. It helps
with the installation process: a user clones the orchestrator and the keeper,
and the keeper retrieves the elements they need.

It has a repository of its own, `robohub-keeper`, and reads the orchestrator it
looks after from `ROBOHUB_ROOT` (or `ROBOHUB_WORKSPACE`, the folder that holds
both checkouts).

## Building

```sh
rho build .
```

The documentation the keeper serves is built by the documentation site, which
collects every module's pages into one tree:

```sh
rho build ../robohub/applications/docsite
../robohub/applications/docsite/build/docsite
```

## Running

```sh
ROBOHUB_ROOT=../robohub ./build/keeper
```

As a user service, which is how it normally runs:

```sh
./scripts/deploy-keeper.sh
```

The service listens on `127.0.0.1` only: the keeper signs people in over plain
HTTP, so reaching it from another machine belongs behind a TLS proxy.
`KEEPER_LISTEN=0.0.0.0 ./scripts/deploy-keeper.sh` opens it to every interface
anyway.

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

What the keeper runs is its catalogue, `~/.rho/keeper/installed.yml`: one record
per application with where it came from (`registry`, `workspace`, `bundled`,
`external` or `fetched`), where it is, its version, the port it was given and the
unit that runs it. Pages and the API read the catalogue instead of scanning
folders. On its first start the keeper adopts what it finds — the selected
packages in the module registry, what the orchestrator's registry names, the
orchestrator's `applications/` and the folders registered by path — and after
that a new application is added through **Install**: one **found on this
machine**, a git URL, which is cloned into `~/.rho/apps/<name>`
(`ROBOHUB_APPS_HOME`), or a folder, which stays where it is. An application whose
manifest port another application already has is given the next free one from
8500.

An application published to the Rho registry is installed by name —
`aquarium` or `aquarium@0.5.0` under **From the Rho registry** — with
`rho module install`, and runs as it was published. When the registry has a newer
version its card says **update** and its inspector offers **Update to …**, which
installs it, points the catalogue at it, writes the unit again and restarts; the old
version stays installed.

**Uninstall** removes the application's unit and its record. Its folder is
deleted only when the keeper cloned it; a checkout or a package stays where it is
and is offered again under **found on this machine**.

### How an application runs

Each application is a systemd user unit the keeper writes from its manifest and
its record — `After=`/`Wants=` for what `deploy.depends` names,
`Restart=on-failure`, and `EnvironmentFile=` the application's `app.env`. The
unit is written again whenever it no longer says what the keeper would write, so
a moved folder or a new port is picked up by the next start or restart. The state
a row shows comes from systemd and the application's `/healthz`: **running**,
**starting**, **failed**, **stopped**, **not built**, **no service yet**. **Log**
is the unit's journal.

What a started application is told, in `app.env` (owner-only):

| Variable | What it is |
| --- | --- |
| `RHO_APP_NAME` | its name in the catalogue |
| `RHO_APP_WORKSPACE` | the folder its state lives in (`ROBOHUB_APP_WORKSPACE` too) |
| `RHO_HTTP_ADDR` | where to listen: `127.0.0.1:<port>`, or `:<port>` when the manifest says `deploy.listen: lan` |
| `RHO_APP_SECRET` | a random value of its own: the seed of its forms' CSRF tokens |
| `RHO_AUTH_URL` | the issuer that signs people in |
| `ROBOHUB_KEEPER_URL` | the keeper, for its API |
| `RHO_CLIENT_ID`, `RHO_CLIENT_SECRET_FILE`, `RHO_SERVICE_<NAME>_URL` | for an application that calls other services (`deploy.calls`) |

`ROBOHUB_ROOT`, `ROBOHUB_WORKSPACE`, `ROBOHUB_APP_MANIFEST` and `RHO_KEEPER_PORT`
are still written for applications that read the orchestrator's files; they go
once every application asks the keeper's API instead.

### What an application needs

The **Dependencies** tab of an application, and the page **Install** shows before
anything is installed, read three levels: the machine — the programs its
manifest's `system_deps` names, as `rho doctor --path <folder>` finds them — the
Rho modules it names outside RoboHub's own, and the applications it depends on and
the services it calls. A required program that is missing stops the application
from starting; **Install** on its row runs `rho keeper install` as a job, which
fetches into `~/.rho/toolchains` when it can and uses the package manager when it
must (a package that needs root says how to install it by hand when the job
cannot). **Dependencies** in the rail is the whole machine: every application and
every enabled toolchain module.

### An application's page

`/apps/<name>` is an application's page in the keeper: its state, where it runs,
what it needs, its journal, its environment and its actions. The menu entries of
the applications added to the menu lead there, and **Open application** is the way
into the application itself.

### Integrations

An integration is a plugin of `kind: integration` that brings a service the keeper
runs for the applications. **Applications → Integrations** lists the ones under
the orchestrator's `plugins/`; **Run it** records it in the catalogue, writes its
configuration under `~/.rho/keeper/services/<name>/` and starts it as a user unit
running the service's own program. Its health is a TCP check on its port; what it
needs from the machine is its plugin's `system_deps`, on its Dependencies tab like
an application's.

**MQTT** (`robohub-mqtt`) runs Mosquitto on port 1884, on this machine only until an
admin opens it to the network for devices (Clients → *Open it to the network*). Every
application whose manifest binds the bus is a broker user, with a random password
in its workspace and the topics its `bus:` block names:

```yaml
bind:
  robohub.bus:
    providers: [robohub-provider-mqtt]
bus:
  publish: [+/rpc]
  subscribe: [+/status/#, +/online]
```

and is started with `ROBOHUB_BUS_URL`, `ROBOHUB_BUS_USER` and
`ROBOHUB_BUS_PASSWORD_FILE`. A device is a broker user an admin adds on the Clients
tab, allowed its own topic prefix; its password is shown once. **Topics** shows what
the broker carries, live. Passwords are hashed by `mosquitto_passwd` from an
owner-only file and never put on a command line, and a change of users or rules is
read by the running broker without dropping its connections.

### Jobs

Building, redeploying and a start that needs a build are jobs: a script under
`~/.rho/keeper/jobs/<id>/` run in the background, one at a time per application,
with its log and its outcome. The strip at the bottom of every page shows what is
running and how the last job ended; `/jobs/<id>` is its log.

### The API

```text
GET  /api/v1/apps                    every application: state, port, version, url
GET  /api/v1/apps/{name}             one of them
POST /api/v1/apps/{name}/{action}    start | stop | restart | redeploy | build
GET  /api/v1/jobs                    recent jobs
GET  /api/v1/jobs/{id}               one job, with its log
GET  /api/v1/registry                the orchestrator's modules: role, path here, git
                                     (?format=tsv for a program without JSON)
GET  /api/v1/me                      who is asking: a person, or an application
GET  /api/v1/services                the services an application calls, and where
GET  /api/v1/config/{app}            an application's record and environment
GET  /api/v1/switcher                the applications, for every app switcher (public)
GET  /api/v1/events                  Server-Sent Events: app.installed, app.started,
                                     app.stopped, app.updated, job.done, job.failed,
                                     person.signed-in, person.signed-out, keys.rotated
```

An application asks with its own service token: it is a client of the keeper,
with `keeper:read`, and `rho_http_request(..., "keeper", "keeper:read", ...)` gets
the token for it. Mesh reads the registry this way, so it does not read the
orchestrator's checkout.

The routes are behind the keeper's sign-in like its pages.

Each row can be opened in a new page, started and stopped, and added to or
removed from the keeper's left menu. A pinned application is a sub-item under
**Applications**, beside the registry link it was added from. The menu selection
is kept in `~/.rho/keeper/menu.txt`; the entries are read whenever a page is
rendered. A started application is also told the keeper's port, so it can offer
a **Go to Keeper** link back. `RHO_KEEPER_STATE_DIR` names another state
directory, which is what the tests use.

Mesh has its own repository, robohub-mesh, beside the orchestrator: `rho build
../robohub-mesh` builds it, and the keeper finds it through the orchestrator's
registry (`registry/modules/robohub-mesh.yml`, `role: application`) and can start
it from its row. Its own guide is the Mesh module's
documentation.

## Registry

`/modules` is the RoboHub registry: the repositories this orchestrator publishes
and tracks, with their versions and whether they are installed. **Install**
clones one where its registry entry says; **Uninstall** is offered only for a
checkout the keeper cloned itself (`~/.rho/keeper/fetched.txt`), because a
checkout made by hand may hold work that is not anywhere else.

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

## Security

- A form posted from another origin is refused (`same_origin` in `project.yml`).
  Every application the keeper hosts is another port of the same host, which a
  `SameSite` cookie does not tell apart; the browser's `Sec-Fetch-Site` or
  `Origin` does. Programs that post to the keeper send neither and are not
  affected.
- Every program the keeper runs gets its arguments one per line, so a name or a
  URL is exactly one argument; a value with a line break or a leading `-` is
  refused before it gets there.
- `~/.rho/keeper` is owner-only. Session ids, tokens and credentials come from
  the runtime's random source and never pass through a report file; a ticket is
  read from a private folder and removed at once.
- Five wrong tokens close the sign-in for five minutes. Changing the token asks
  for the current one and signs out every other session.

## People

The people who sign in are in `~/.rho/keeper/users.yml`, owner-only, kept by the
rho-auth component (`rho auth user add|verify|passwd|set|remove|list`), which
hashes passwords with PBKDF2; the keeper hands a password to it in a private file
removed at once, never on a command line. Each person has a role and grants:

| Role | May |
| --- | --- |
| admin | everything: applications, installing, people, plugins, settings |
| operator | start, stop, restart, build and redeploy the applications |
| viewer | read |

Grants are what a person reaches in each application, as scopes — `mesh:*`,
`mesh:greenhouse`, `aquarium:read`. A ticket for an application carries the
person's name and only their grants for it (an admin's carry `*`); a person with
none is told they have no access rather than signed in.

**The first run and the admin.** The keeper makes an access token on its first
start, owner-only, in `~/.rho/auth/master.token`, and a signing key pair if there is
none. The token is the admin's: with nobody in the store, the sign-in page asks for
it and nothing else, and it signs the admin in afterwards too ("The admin's access
token instead"). Accounts with a name and a password are for other people, made
under Users & access; the admin can make one for themselves there as well. A
forgotten password is reset by the admin, or from the command line:

```sh
rho auth user passwd --store ~/.rho/keeper/users.yml --name ana --password-file <file>
```

**Sessions end together.** A ticket carries the keeper session it came from. An
application keeps it with its own session and asks `/auth/session/<id>` at most
once a minute; signing out of the keeper, or **Sign out everywhere** under Users &
access, ends the application's session at its next request after that. A keeper
that cannot be reached signs nobody out.

## Authentication

Keeper is the RoboHub authorization server. `/auth/login` validates the master
token, opens a keeper session, and mints a short-lived ES256 ticket for the
requesting application. The admin UI is behind that session. Tickets are
verified by the application with Keeper's public key; a ticket carries the
application audience, redirect URI, one-use id and a 30-second lifetime.

Signing in to an application returns to its callback: `/auth/callback` at the
root of the port it serves on (Mesh on `:8478`), or `<route>/auth/callback` when it
is mounted behind a proxy. Keeper signs in to itself on the port it was started on
(`RHO_HTTP_ADDR`), which need not be the one its manifest names.

## Building, redeploying and restarting

Each application row has three controls that act on what runs:

- **Build** runs `rho build` on the application's folder and touches nothing
  that is running; **Restart** then runs the new build.
- **Redeploy** builds, writes the application's systemd user unit for where it
  is now, and restarts it. A build that fails leaves the running program alone.
- **Restart** restarts the service. A unit that no longer describes the
  application — its folder, manifest, program or port changed, as when a
  repository is moved — is deployed again first, so a moved application is not
  left restarting a program that is no longer there. **Start** does the same.

## Artifact updates

A signed artifact placed in `~/.rho/keeper/incoming/` is used by **Redeploy** when
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

## Enrolled node registry

`/nodes` lists identities Keeper has issued. Each record can be rotated or
revoked. A gateway or firmware calls:

```text
POST /api/nodes/verify
device_id=<device>&credential=<credential>
```

and receives the registered project/area/node, or `403` for an unknown or
revoked node. This endpoint is public because the credential authenticates it.

Revocation removes the record, so the next verification fails. Rotation issues a
new credential and the node must fetch or accept it; the firmware path that
updates the local credential is still hardware-side work.

The remaining firmware-level provisioning work is documented in the
`rho-bootstrap` component: NVS identity, flash encryption, enrollment transport,
factory reset, credential refresh, and secure-element limitations.
