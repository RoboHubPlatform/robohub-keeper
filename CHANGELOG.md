# Changelog

All notable changes to this module are recorded here, one section per release.

## [0.5.4] - 2026-11-05

A keeper session now stores an absolute expiry, which is what the generated auth
middleware reads; a master login and the pages it protects agree again. Starting
an application records the application's own pid instead of a wrapper's, so Stop
works and a later Start is not told a dead instance is still running. Aquarium's
menu shows the Keeper link when the keeper is the one that started it.


The keeper has an Access token page: a signed-in administrator can replace the
master token, generate a random one, and copy the new token once after saving.

## [0.5.2] - 2026-11-04

Keeper is the SSO authorization server: master login, session store, ticket minting, protected admin UI and the redesigned login page. Auth is a selectable plugin, and providers are listed beside plugins.

## [0.5.1] - 2026-11-02

The left menu nests the current RoboHub application, the pinned applications,
Modules and Plugins under **Applications**; Modules and Plugins are no longer
separate top-level entries.

The Modules page lists modules without an Open link: a module can be included by
more than one application, so there is no single host to follow. Module versions
are the module's own; a host declares a dependency constraint in its
`app_modules` entry.

## [0.5.0] - 2026-11-02

A Modules registry at `/app-modules` for the reusable modules under
`modules/`. It lists the installed set from `modules/registry.yml`, confirms each
path on disk, installs one from a git URL or folder, and removes one. A module
has no port or process of its own and no single host: every application that
includes it serves its routes on its own router and port.

## [0.4.0] - 2026-11-02

The keeper has a plugin registry at `/plugins`. It lists the plugins in
`plugins/registry.yml`, confirms each path on disk, installs one from a git URL
or a folder, removes one, enables or disables it for the keeper, and sends a
test alert through it. A path whose folder is gone is shown as missing.

Application failures from the applications registry now raise alerts through
the configured dispatcher. The keeper's own plugin settings come from its
`module.yml`; a dashboard toggle is written to `~/.rho/keeper/plugins.txt` so the
installed manifest is not edited.

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
