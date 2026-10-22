# RoboHub Keeper

A local dashboard for the RoboHub ecosystem — its registry, what is installed,
and what the machine needs to run it.

## Building

```sh
rho build applications/keeper
```

## Running

```sh
./applications/keeper/build/keeper
```

The keeper listens on port 8080 by default. Set the port with:

```sh
./applications/keeper/build/keeper 9090
```

## What it does

- Shows the ecosystem registry with installation status
- Module detail pages with version, role, path, git URL, summary
- Install/uninstall modules via git clone
- System dependencies page listing tools the ecosystem needs
- Documentation pages for each module and the orchestrator
- Web-based admin panel with rho-keeper style

## Environment

- `RHO_DOCS_ROOT` — the project root (default: `.`)
- `RHO_DOCS_TREE` — the documentation tree (default: `docs`)
- `RHO_SITE_BUILD` — where the built site is (default: temp dir)
- `RHO_SITE_TITLE` — the site title (default: "Rho language and toolchain")
