# Changelog

All notable changes to this module are recorded here, one section per release.

## [0.2.0] - 2026-11-01

Mesh projects and dashboard: the keeper plans a gateway and its nodes as a
tree, records each project in a workspace folder, and shows every project with
its gateway status, address, last update, restart/stop/delete and project
settings. The plan, network, build/program and verify steps are shown only
inside a project.

Network is connection-oriented: a branch opens the link, both ends are
configured, and the transport is chosen from what the two boards and
`robohub-transport` declare. Build carries the transport into the firmware;
programming shows the boot-mode instruction and waits for the acknowledgement.
Long actions stream their output over Server-Sent Events with timestamps and a
clearable console. Board and driver discovery is entirely runtime.

## [0.3.0] - 2026-11-01

The Applications registry. A module whose manifest declares an `application`
block is an application the keeper lists at `/applications` and in the left
menu: `keeper` is the dashboard itself, and `keeper-hosted` is an application
with its own listener that the keeper can start and stop.

The page discovers applications from `applications/` on every request, installs
one from a git URL, or registers a folder that already exists on the machine,
and uninstalls it again without touching an external folder. Every installed
application can be opened, added to or removed from the keeper's left menu, and
launched from that entry. The guest application's listener is built from the
browser's host and the port the manifest declares, so the link works from
another machine as well.

Mesh is a `keeper-hosted` application of its own now: its dashboard, plan
wizard and deployment state moved to `applications/mesh`, and the keeper no
longer carries the `/mesh` routes.

## [0.4.0] - 2026-11-02

The keeper has a plugin registry at `/plugins`. It lists the plugins in
`plugins/registry.yml`, confirms each path on disk, installs one from a git URL
or a folder, removes one, enables or disables it for the keeper, and sends a
test alert through it. A path whose folder is gone is shown as missing.

Application failures from the applications registry now raise alerts through
the configured dispatcher. The keeper's own plugin settings come from its
`module.yml`; a dashboard toggle is written to `~/.rho/keeper/plugins.txt` so the
installed manifest is not edited.

## [0.5.0] - 2026-11-02

A Modules registry at `/app-modules` for the reusable modules under
`modules/`. It lists the installed set from `modules/registry.yml`, confirms each
path on disk, installs one from a git URL or folder, and removes one. A module
has no port or process of its own and no single host: every application that
includes it serves its routes on its own router and port.

## [0.5.1] - 2026-11-02

The left menu nests the current RoboHub application, the pinned applications,
Modules and Plugins under **Applications**; Modules and Plugins are no longer
separate top-level entries.

The Modules page lists modules without an Open link: a module can be included by
more than one application, so there is no single host to follow. Module versions
are the module's own; a host declares a dependency constraint in its
`app_modules` entry.

## [0.5.2] - 2026-11-04

Keeper is the SSO authorization server: master login, session store, ticket minting, protected admin UI and the redesigned login page. Auth is a selectable plugin, and providers are listed beside plugins.

## [0.5.4] - 2026-11-05

A keeper session now stores an absolute expiry, which is what the generated auth
middleware reads; a master login and the pages it protects agree again. Starting
an application records the application's own pid instead of a wrapper's, so Stop
works and a later Start is not told a dead instance is still running. Aquarium's
menu shows the Keeper link when the keeper is the one that started it.


The keeper has an Access token page: a signed-in administrator can replace the
master token, generate a random one, and copy the new token once after saving.

## [0.5.5] - 2026-11-06

Deploy system: bootstrap script, per-app deploy script, deploy.port/depends
metadata in module.yml, Update/Restart buttons in web UI, dependency enforcement.
Fixed keeper session expiry (absolute epoch). Fixed app_start pid recording.

## [0.5.6] - 2026-11-08

Reactive application rows, plugin/provider/app-module actions, and the module
tree use HTMX fragments. English/Romanian UI, parent settings with alert
overrides, systemd-backed application services, signed host artifact rollout
with health-check rollback, and one-time node enrollment with a registry,
credential verification, rotation and revocation.

## [0.5.7] - 2026-11-09

Every application has a Logging form (level, text/JSON, rotating file, size,
retention, stderr) and the keeper's Applications page links each app to its
log. The keeper itself reads the same policy and writes to the shared logging
path. Starting a bundled application that has no unit now deploys it as a user
service first, so energy and future bundled apps are managed by systemd like
mesh and aquarium.

## [0.5.8] - 2026-11-12

The keeper finds the applications the orchestrator's registry names with
`role: application`, by the path each entry gives, after the published ones and
before the folders beside it. That is how Mesh, which has its own repository
now, is listed and started.

## [0.5.9] - 2026-11-12

The plugins page shows each plugin's real kind and transport, accepts a plugin
that declares `module.plugin_kind` on install, and says "No such plugin" when
there is none. Removing a provider removes the folder the registry names for
it. Installing a module checks `module.type: module`, and module titles come
from `module.title`. `deploy-keeper.sh` gives the keeper a workspace of its own
(`~/.rho/keeper`), carrying over settings it had in the shared store, and
rewrites a unit written before that.

## [0.6.0] - 2026-11-12

The keeper raises its alerts through the alert interface: it binds the log,
e-mail and Telegram providers in its `module.yml`, and the alert plugins it used
to name are gone. The Settings page's Alerts tab writes each channel's settings
through the binding, including whether e-mail and Telegram are on, and the
Plugins page lists the bound channels apart from the installed plugins: a
channel is switched on or off and sent a test through the interface, and a
plugin is enabled, installed or removed as before. The Providers page shows
which interface a provider implements, from its `implements` list. The plugin
and provider registry files are the keeper's own code rather than the alert
contract's.

## [0.6.1] - 2026-11-12

The keeper publishes the public key its sessions and tickets are verified with,
at `/auth/public-key`, to anyone and without a session: it is a public key. An
application the keeper starts fetches it from there, and one started elsewhere is
pointed at it with RHO_AUTH_URL, so no key is copied by hand. The smoke test
checks that the published key is the keeper's.

## [0.6.2] - 2026-11-12

Signing in to an application on a port of its own returns to `/auth/callback`
at its root, and keeper signs in to itself on the port it was started on. An
application row has **Build** and **Redeploy** (build, write the service unit for
where the application is now, restart); a unit left behind by a moved
application is written again on Start and Restart. A failed build is reported
as one.

## [0.7.0] - 2026-11-13

The keeper has a repository of its own, `robohub-keeper`, beside the
orchestrator it reads through `ROBOHUB_ROOT`; `scripts/deploy-keeper.sh` deploys it
from here, and listens on `127.0.0.1` unless `KEEPER_LISTEN` says otherwise.

Safe by default:

- A form posted from another origin, which includes every application on another
  port of this host, is refused before a handler sees it.
- Registry install and uninstall are POSTs, and uninstall removes only a checkout
  the keeper cloned itself. Uninstalling an application the keeper did not fetch
  stops it, removes its service and stops listing it, leaving its folder alone.
- Every program the keeper runs takes its arguments one per line; values with a
  line break or a leading `-` are refused. A node's enrollment can no longer name
  a file outside the node folder.
- The state folder is owner-only; random values come from the runtime and no
  secret is written to a report file.
- The token is compared without stopping at the first difference, five wrong
  tokens close the sign-in for five minutes, and changing the token asks for the
  current one and signs out every other session.
- Application rows loaded later get their Open links; a dependency that starts is
  no longer reported as one that did not, and two applications that depend on each
  other no longer start each other for ever.

## [0.8.0] - 2026-11-13

A catalogue and a supervisor. What the keeper runs is `installed.yml`, adopted
from what was on the machine the first time and changed only by Install and
Uninstall, so pages no longer scan folders and run `rho module list` on every
request. Each application gets a port of its own (the next free one from 8500
when its manifest's is taken) and a systemd unit the keeper writes from its
manifest — `After=`/`Wants=` for its dependencies, its environment in an
owner-only `app.env` — instead of the deploy script. State comes from systemd and
`/healthz`: running, starting, failed, stopped, not built. Logs come from the
journal.

Builds, redeploys and starts that need a build run as background jobs with a log,
shown in a strip at the bottom of every page. Applications cloned from git go to
`~/.rho/apps`, not into the orchestrator's checkout.

`/api/v1/apps` and `/api/v1/jobs` answer programs in JSON, with the same actions
the pages have, and the environment a started application is told is written down
— including `RHO_APP_SECRET`, the seed its forms' CSRF tokens use.

The keeper takes the RoboHub look from the new shared `robohub.ui` module: the
top bar every application will draw (brand, app switcher, the person's menu with
theme and language), a rail of places, and a strip of jobs at the bottom. Home is
the machine at a glance — every application as a card with one pill, and an
inspector beside them with its folder, port and unit, its journal, its
environment, and start, stop, restart, build and redeploy. A light theme comes
from the same tokens, chosen per person and shared by every application on the
host. The old explanatory home page, the unused stylesheets and the deploy script
are gone.

What an application needs, at three levels: the machine (its manifest's
`system_deps`, read with `rho doctor --path`), Rho (the modules it names) and
RoboHub (the applications it depends on and the services it calls). A required
program that is missing stops it from starting, its card says so, and its
Dependencies tab installs it as a job through `rho keeper install`. Installing
shows all of this first ("Check what it needs"), and the Dependencies page is the
whole machine. The keeper, Mesh and the aquarium declare their `system_deps`.

Each application has a page of its own in the keeper (`/apps/<name>`), which the
menu leads to; opening the application itself is a button there, so a menu entry
no longer leaves the keeper without warning. A job that ends says so on every open
page through the shared notifications module, and the install form is drawn by
the shared forms module with its CSRF token.

People. Signing in is by name and password, kept by rho-auth (`rho auth user`,
PBKDF2), with a role — admin, operator, viewer — and grants per application. The
first run makes the first admin, proved by the access token on the machine; after
that the token is only for recovery from the command line. A ticket for an
application carries the person's own name and only their grants for it, so a
person with no grant for Mesh is not signed in to Mesh; it also carries the keeper
session, and `/auth/session/<id>` tells an application whether that still stands,
so signing out — or being signed out from Users & access — ends every
application's session within a minute. The keeper's own actions follow the role:
installing, people, plugins and settings are an admin's; starting, stopping and
redeploying an operator's. Users & access lists the people with their grants and
sessions; Account changes one's own password. The sign-in page has the RoboHub
look and names the application it signs in to.

Users & access is a matrix — a row per person, a column per application — with
the person in an inspector: their role, and for each application no access, read,
everything or particular grants. An admin signed in with the access token is shown
in it, and makes the account they are from there; their session becomes it.

Every installed application is a client of the keeper, not only those that call
other services: it may read the keeper's API (`keeper:read`), its client goes when
it is uninstalled, and its Environment tab gives it a new secret. The signing key
can be rotated from the recovery page; applications fetch the new public key when
a ticket names it.

Applications listen on this machine only (`127.0.0.1:<port>`) unless their
manifest says `deploy.listen: lan` — which is also the address a Windows browser
is forwarded to under WSL, where an application on every interface could not be
reached. The orchestrator is asked rather than read: `/api/v1/registry`,
`/api/v1/me`, `/api/v1/services` and `/api/v1/config/{app}` answer an application
with its own service token.

The first run asks for the access token and nothing else: the token in
`~/.rho/auth/master.token` is the admin's, and it signs the admin in afterwards too.
Accounts with passwords are for other people. Wrong attempts are counted per name
and every sign-in is recorded, shown in the person's inspector. The forms module
draws the plugin, provider and module install forms with their tokens; those pages
and the registry are cards, and the registry is part of the Applications page. An
application published to the Rho registry is installed by name (`name@version`),
and updated when a newer version is out. Pages are in Romanian through the shared
i18n module's catalog of whole labels.

`/api/v1/events` streams what happens — installs, starts, stops, updates, jobs,
sign-ins and sign-outs, key rotation — so an application listens rather than asks.

Integrations: a plugin of `kind: integration` brings a service the keeper runs for
the applications — its program, configuration, port and system dependencies — and
the first is robohub-mqtt, a Mosquitto broker on port 1884. Every application that
binds the bus is a broker user with the topics its manifest names, devices are
broker users an admin adds, and the broker's inspector shows its clients and its
live topics. The keeper reaches the broker through the RoboHub platform's mqtt port.
The broker's users are hashed in a private file of their own and moved into place
only when that worked (two writes take turns, empty lines are left out), so the
broker keeps the users it had if anything goes wrong; and the broker does not log
the connection the keeper's health check opens.

## [0.9.0] - 2026-11-13

An application built from a folder runs from a release, never from the folder:
a redeploy (and the first start) builds, copies the program, its manifest,
static/ and what deploy.files names into ~/.rho/keeper/apps/<name>/releases/
<version>-<time>, moves `current` to it in one rename, and restarts the unit,
which runs `current`. A rebuild in the folder changes nothing until the next
redeploy. The three newest releases are kept, and Roll back (on the
application's page, or POST /api/v1/apps/<name>/rollback) puts the previous one
back in use. The application's page says which release is in use. The keeper
deploys itself the same way: scripts/deploy-keeper.sh builds, makes a release
and restarts on it every time it runs (--status only reports).

## [0.9.1] - 2026-11-13

The clock sign-in, sessions and enrolment use is read from the process (`rho_now_s`) instead of from `date` written to a fixed file, which two requests at once could truncate under each other and make a session expire at once. Built on rho-sql 0.2.1.

## [0.9.2] - 2026-11-13

Correctness fixes from the 2026-11 review.

- A redeploy whose release systemd cannot restart, or which does not answer, puts the release that was in use back and restarts it; the job ends failed saying which release is back, and the new one is marked `.failed`. Before, the broken release stayed in use and systemd restarted it in a loop.
- A rollback goes to the release made before the one in use, by the time in its name; a second rollback goes further back instead of returning to where the first started. Pruning never removes the release in use or the one before it.
- A job that says it is running but holds no lock after half a minute (killed, a restart, a lost race for the lock) is marked failed, so the application is not busy for ever.
- The smoke test binds to 127.0.0.1, and covers a release that answers, one that does not, two rollbacks and a stale job.

## [0.9.3] - 2026-11-13

Built on provider-email 0.2.1, provider-webhook 0.2.1, provider-log 0.2.1 and notifications 0.1.6.

## [0.9.4] - 2026-11-13

- Uninstalling an application removes its releases and its secrets (app.env, app.secret), so the same name installed again starts afresh; its data is kept.
- An application's name may not contain a dot, which the catalogue would read back as a record of its own.

## [0.9.5] - 2026-11-13

An application's `app.env` quotes HOME and PATH, as systemd's environment file reads a value whole: unquoted, WSL's PATH stopped at `/mnt/c/Program` and the Windows directories after it — powershell.exe among them — were lost, so Mesh could not reach a board through Windows to flash it.

## [0.9.6] - 2026-11-13

A mesh gateway's page can be signed in to. The gateway takes keeper's tickets for the audience `gateway` but is started by Mesh rather than hosted by the keeper, so its sign-in was refused as "not one this keeper signs in to". The keeper now signs in to the audience `gateway` when the ticket goes back to `/auth/callback` on this machine or on the host the keeper was reached on, on whatever port the mesh gave it, and nowhere else.

## [0.9.7] - 2026-11-14

Trimming, URL decoding and form fields come from the toolchain (rho 0.7.0) rather than the keeper's own copies; a `%` not followed by two hex digits in a form is kept as written instead of becoming a zero byte. Needs rho 0.7.0.

## [0.9.8] - 2026-11-14

From a security review.

- A sign-in ticket names the keeper session by a handle derived from it, never by the session id the keeper's cookie carries: an application, or anything that reads its ticket, could otherwise present it back to the keeper as the admin. `/auth/session/{handle}` answers by the handle.
- The docs page no longer reflects its address as markup, and refuses a path with `..`.
- The app switcher's list is readable from a page of this host only, not from any site (`Access-Control-Allow-Origin` was `*`).
- `next`, `return_to` and `audience` are URL-encoded on their way through sign-in.
- Hosted applications run with `NoNewPrivileges`, and — where the machine's systemd can make a private view for a user service, which the keeper tries once — with the keeper's folder empty in their view but for their own workspace and releases, and the keys that mint tokens hidden.
- A manifest's `deploy.calls` cannot name `*`.
- Enrollment: area and node must be numbers, and a token not made for a device cannot take over one already enrolled.

## [0.9.9] - 2026-11-14

- The keeper declares one port, 19090, and a keeper started by hand listens there on loopback.
- Uninstalling a module is refused while an installed application uses it, and deletes its folder only when the keeper fetched it.
- `deploy-keeper.sh` reads the manifest with awk and no longer needs PyYAML.

## [0.9.10] - 2026-11-14

Its function for a hosted app's workspace is `keeper_app_workspace`, apart from the toolchain's `app_workspace()`; HTML is escaped by `escape_html` (rho 0.8.0).

## [0.9.11] - 2026-11-14

Every page, fragment, notice and confirmation of the keeper — the sign-in page included — is written with i18n keys (609 in each of English and Romanian, the same set), where hard-coded English was translated afterwards by matching whole phrases, which missed about four in ten, any message with a value in it and every confirmation. The phrase catalog and its pass are gone. Messages the keeper keeps (job reasons, the sign-in history, logs) stay English and are translated when shown; API answers stay English.

## [0.9.12] - 2026-11-14

The applications the keeper hosts are served under its own origin, at `/app/<name>/` (rho 0.8.1's `app_proxy`), and the keeper's links and the app switcher send a person there rather than to their ports. Cookies are scoped by host, not by port, so on its own port an application received the keeper's admin session with every request; through the keeper it never does, and its own cookies are scoped to its path. An application signs in through the keeper's origin too. `keeper.proxy_apps: off` in the keeper's settings goes back to ports. Needs rho 0.8.1.
