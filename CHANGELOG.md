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
