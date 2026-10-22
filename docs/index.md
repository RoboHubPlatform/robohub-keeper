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
