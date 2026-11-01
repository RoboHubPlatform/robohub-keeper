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

## RoboHub Mesh

A complete guide, including projects, the connection editor, build and program,
and the gateway page, is [Mesh](mesh.md).

`/mesh` is the Mesh dashboard: the projects in the workspace, each with its
gateway, address, running status and last update, and a form to create a new
project. A project card has **Restart**, **Stop**, **Delete** and **Project
settings**; opening a project loads it and shows its plan wizard. The plan
itself is `/mesh/plan`.

The plan is a gateway and the tree of nodes that report through it. The plan
is drawn as a tree of cards: the gateway is the root, and every child is drawn
under its parent with the link it uses — `UART` or `WiFi` — on the branch. A
card opens the node it represents, where its name, description, role, board,
driver, parent and link are chosen.

Accepting the topology locks the tree and opens the network step. Network is
about the edges: every branch on the tree is a connection, and its transport
badge is a link to that connection. The connection page shows both ends and
offers only transports both boards can serve, intersected with the transports
the `robohub-transport` module declares and the `capabilities.links` each board
declares. `Console` is offered only when the parent is a host — native or a
board that declares `host` and `console` — because the console is the host's
byte stream. Choosing a transport swaps in the fields that transport needs —
serial devices and baud for UART/USB/Console/RS-485, SSID and hosts for WiFi,
interfaces and ports for Ethernet/sockets, bus and address for SPI/I2C. A node card opens that node's network page, which lists its
incoming connection and the connections to its children. The gateway's page
sets the gateway host and REST port and lists its outgoing connections.
Accepting the network unlocks build and program.

The later steps draw the same tree read-only, and every step can be revisited;
editing the topology resets the steps that depended on it.

The steps after the plan are data: `wizard/wizard.yml` names them, each step is
a file under `wizard/steps/`, and a step lists its fields and actions. Boards
and drivers are discovered from the local registry on every page load, including
the `capabilities` and `deployment` blocks in their `module.yml`, so adding a
board or driver needs no keeper rebuild.

### Build & program

The build step is the same tree with a status on every card: `not built`,
`built`, `programmed`, `running` or `failed`. Clicking a node opens that node's
build page, which offers **Build node** and **Program node**. Program uses the
last successful build; build first when no image exists. Clicking the gateway
opens its page, which offers **Build gateway** and **Program gateway** (build if
needed, then deploy or start). The same page can change the gateway to another
gateway board or to this host; changing it resets the network, build and verify
steps. The verify step unlocks when the gateway is running and every node is
programmed.

The node's build and program are the same commands the pico examples use:
`rho build -target <board> .` and `rho flash -target <board> -project <node
directory> <image>`. The build carries the connection's transport into the
node's configuration: UART uses the UART link (UART 1 on the Pico 2W), USB and
Console use USB CDC, WiFi and Socket use the TCP sink. The platform's flash
entry attaches a Shared board to WSL and uses passwordless sudo for PICOBOOT
when it is available; otherwise it falls back to the bootrom's drive.

Before a node is programmed, its page shows the board's boot-mode instruction
and requires an acknowledgement before **Program** runs. The console is cleared
on the server before a new action starts, so a stale `__DONE__` from the
previous run cannot replay old output or close the stream early.

Long actions write their output to a progress file; the page follows it over
Server-Sent Events. The console panel keeps the latest line in view until you
scroll away, and has a **Clear console** action. The request that starts the
action returns when the action finishes, so the server does not impose a write
deadline on it.

### Logging

The keeper's `project.yml` asks the backend for the `logemit` port and the app
imports `rho.log`. Records on standard error carry a UTC timestamp, the level
and the subject:

```text
[2026-11-01T12:48:27.695Z] [info] [keeper] starting build_node on build
[2026-11-01T12:49:28.534Z] [info] [mesh] node 1 built
```

`RHO_LOG_FILE` also appends those records to a file. The generated HTTP server
logs requests with its own date/time, and the web console prefixes every live
line with the local date and time. The server-side progress log is cleared
before an action starts, so a previous run cannot replay into the new console.

### Projects

A project is a folder in the projects workspace: its plan, network, build and
verify settings live in `project.txt`. The default workspace is
`~/.rho/mesh/projects`; `ROBOHUB_MESH_PROJECTS` names another one. The dashboard
shows that location, every project and its gateway status, and a form to create
a new project.

Opening a project loads it as the current project and shows the wizard at
`/mesh/plan`. The dashboard itself does not show the plan/network/build/verify
steps; they belong to the project being created or edited. A project card has
Restart, Stop, Delete and **Project settings**; settings rename the project and
add a short description. The cards show the last update as local date/time from
the wall-clock `received_at_ms` the gateway records beside the node's uptime.

`RHO_KEEPER_STATE_DIR` still holds the keeper's reports and the current-project
pointer, which is what the tests use.
