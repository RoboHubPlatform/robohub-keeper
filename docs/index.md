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

## Running

```sh
./applications/keeper/build/keeper
```
