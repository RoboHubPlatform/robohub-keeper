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
