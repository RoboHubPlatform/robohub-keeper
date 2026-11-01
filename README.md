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

## RoboHub Mesh

`/mesh` is the Mesh dashboard: the gateway status and address, restart/stop,
last update, and the button that starts a new gateway plan. The wizard plan is
`/mesh/plan`.

The plan is a gateway and a tree of nodes. The plan is a card tree with a link
badge on every branch; accepting it locks the tree and opens the network, build
and verify steps. In the network step a branch is a connection: click its badge
to choose a transport both boards can serve and set both endpoints, or click a
node to see its incoming and outgoing connections. Boards and drivers are
discovered from the local registry at runtime, including the `capabilities` and
`deployment` blocks in their `module.yml`; the available transports come from
`robohub-transport` and each board's `capabilities.links`. `Console` is offered
only when the parent is a host.

The build step is the same tree with a status on every card. Clicking a node
offers **Build node** and **Program node**; clicking the gateway offers **Build
gateway** and **Program gateway**, and can change the root to another gateway
board or to this host. The node build carries the selected transport into the
firmware: UART uses a hardware UART, USB/Console use USB CDC, WiFi/Socket use
TCP. Programming shows the board's boot-mode instruction and waits for an
acknowledgement before writing. A console panel follows the live output, keeps
the latest line in view until you scroll away, and has a **Clear console**
action; it is reset before each action.

Projects are folders under `~/.rho/mesh/projects` (or `ROBOHUB_MESH_PROJECTS`).
The Mesh dashboard lists them with their gateway status and a create-project
form; project cards have Restart, Stop, Delete and **Project settings**.
Opening a project shows its plan wizard at `/mesh/plan`. See
[docs/mesh.md](docs/mesh.md) for the full guide.

The keeper uses `rho-log` through the `logemit` port. Build, flash, network and
project records go to standard error with a UTC timestamp, and `RHO_LOG_FILE`
also appends them to a file. The web console prefixes live lines with the local
date and time.

## Tests

```sh
rho test applications/keeper
```

The Rho unit suite checks the mesh's string helpers, and the smoke suite builds
the keeper, walks the mesh over HTTP, saves a two-node tree, verifies the locked
tree, projects and the event stream.
