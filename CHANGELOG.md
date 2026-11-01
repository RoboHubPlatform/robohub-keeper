# Changelog

All notable changes to this module are recorded here, one section per release.

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
