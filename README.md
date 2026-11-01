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
- An applications registry: list, install, uninstall, open, start and stop
  keeper-hosted applications, and add any of them to the keeper's left menu
- Web-based admin panel with rho-keeper style

## Environment

- `RHO_DOCS_ROOT` — the project root (default: `.`)
- `RHO_DOCS_TREE` — the documentation tree (default: `docs`)
- `RHO_SITE_BUILD` — where the built site is (default: temp dir)
- `RHO_SITE_TITLE` — the site title (default: "Rho language and toolchain")

## Applications

The keeper is also the registry of the applications on the machine. An
application is a module whose `module.yml` declares an `application` block:

```yaml
application:
  kind: keeper-hosted
  title: RoboHub Mesh
  route: /mesh
  port: "8478"
  command: mesh
```

`kind: keeper` is the dashboard itself, listed but not removable; a module
without the block is not an application. The `/applications` page discovers
applications from `applications/` on every request, installs one from a git URL
or registers a folder that already exists, and uninstalls it again. Each row
has **Open**, **Start**, **Stop**, **Add to menu** and **Uninstall**. The
left-menu selection and the paths of externally registered applications live in
`~/.rho/keeper/` (`menu.txt`, `applications.txt`), or in
`RHO_KEEPER_STATE_DIR`.

The Mesh application is one of these: build it with
`rho build applications/mesh` and launch it from the registry. Its own guide is
the Mesh module's documentation.

## Tests

```sh
rho test applications/keeper
```

The Rho unit suite checks the registry's name and list helpers, and the smoke
suite builds the keeper, starts it, and walks the applications page over HTTP:
discovery, the keeper row, install and uninstall of an external application,
pinning it to the menu, and refusing to remove the keeper.
