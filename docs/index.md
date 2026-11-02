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

## Modules

`/app-modules` lists the reusable modules in `modules/registry.yml`: each row
shows the module's title, category, version and the application that hosts it,
links to the module's routes there, and can remove it. **Install a module** adds
one from a git URL or a folder. A module has no port or process of its own; its
host application owns the router and the port. A module's records stay in a
workspace named for the hosting application, so installing the same module in
another application does not move or share its database.

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
