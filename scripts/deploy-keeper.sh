#!/usr/bin/env bash
# deploy-keeper.sh  —  build robohub-keeper and install it as a user service
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
KEEPER="$(dirname "$HERE")"
# The orchestrator the keeper looks after is wherever ROBOHUB_ROOT says; a
# machine that says nothing has it beside this checkout, as a workspace does.
ROBOHUB="${ROBOHUB_ROOT:-$(dirname "$KEEPER")/robohub}"
if [ ! -d "$ROBOHUB/registry/modules" ]; then
    echo "deploy-keeper: no RoboHub orchestrator at $ROBOHUB; set ROBOHUB_ROOT" >&2
    exit 1
fi
ROBOHUB="$(cd "$ROBOHUB" && pwd)"
KEEPER_PORT=$(python3 -c "import yaml,sys; print(yaml.safe_load(open('$KEEPER/module.yml'))['deploy']['port'])")
# The keeper listens on this machine only unless told otherwise: it signs people
# in over plain HTTP, so reaching it from the LAN belongs behind a TLS proxy.
# KEEPER_LISTEN=0.0.0.0 opens it to every interface anyway.
KEEPER_LISTEN="${KEEPER_LISTEN:-127.0.0.1}"
SERVICE_NAME="robohub-keeper"
SERVICE_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
SERVICE_FILE="$SERVICE_DIR/$SERVICE_NAME.service"
DEPLOY_LOG="$HOME/.rho/keeper/deploy.log"
RHO="${RHO:-$HOME/.rho/bin/rho}"
# The keeper runs `rho` to build applications and to mint sign-in tickets, and
# `go` through it, so its service sees the toolchain where it is installed: a
# user unit otherwise has systemd's PATH, which has neither.
export PATH="$(dirname "$RHO"):$HOME/.local/bin:/usr/local/go/bin:$PATH"

mkdir -p "$(dirname "$DEPLOY_LOG")"

# --status reports and changes nothing. Otherwise every run builds the keeper,
# makes a release of the build and restarts the service on it: the service runs
# the release in use (~/.rho/keeper/apps/keeper/current), never this checkout's
# build, so a rebuild here changes nothing until the next deploy.
if [ "${1:-}" = "--status" ]; then
    echo "  Status: $(systemctl --user is-active "$SERVICE_NAME" 2>/dev/null || echo 'inactive')"
    echo "  Release: $(basename "$(readlink "$HOME/.rho/keeper/apps/keeper/current" 2>/dev/null)" 2>/dev/null || echo none)"
    exit 0
fi

echo "[$(date)] Building keeper …" | tee -a "$DEPLOY_LOG"
cd "$KEEPER"
"$RHO" build . >> "$DEPLOY_LOG" 2>&1 || {
    echo "BUILD FAILED"; exit 1
}

# A release of the build: the program and its manifest, in a folder of its
# own; `current` moves to it in one rename, and the three newest are kept.
APPHOME="$HOME/.rho/keeper/apps/keeper"
VERSION=$(python3 -c "import yaml; print(yaml.safe_load(open('$KEEPER/module.yml'))['module']['version'])")
REL="$APPHOME/releases/$VERSION-$(date +%Y%m%d%H%M%S)"
mkdir -p "$REL"
cp -a "$KEEPER/build/keeper" "$KEEPER/module.yml" "$REL/"
[ -d "$KEEPER/static" ] && cp -a "$KEEPER/static" "$REL/"
ln -sfn "$REL" "$APPHOME/current.next" && mv -T "$APPHOME/current.next" "$APPHOME/current"
ls -1dt "$APPHOME"/releases/*/ 2>/dev/null | tail -n +4 | while read -r old; do rm -rf -- "$old"; done
echo "[$(date)] Release $(basename "$REL") is in use." | tee -a "$DEPLOY_LOG"

# The keeper's own workspace, as every application it starts has one: its
# settings live there rather than in the store shared by anything started
# without one. Settings written to that shared store before are carried over once.
WORKSPACE="$HOME/.rho/keeper"
mkdir -p "$WORKSPACE/data"
# Sessions, reports and the keeper's private folder are in here: owner-only.
chmod 700 "$WORKSPACE"
if [ ! -f "$WORKSPACE/data/settings.conf" ] && [ -f "$HOME/.rho/robohub/data/settings.conf" ]; then
    cp "$HOME/.rho/robohub/data/settings.conf" "$WORKSPACE/data/settings.conf"
fi

echo "[$(date)] Writing systemd unit …" | tee -a "$DEPLOY_LOG"
mkdir -p "$SERVICE_DIR"
cat > "$SERVICE_FILE" <<UNIT
[Unit]
Description=RoboHub Keeper – web dashboard and application manager
After=network-online.target

[Service]
ExecStart=$APPHOME/current/keeper
Restart=on-failure
RestartSec=3
WorkingDirectory=$ROBOHUB
Environment=HOME=$HOME
Environment=PATH=$PATH
Environment=ROBOHUB_ROOT=$ROBOHUB
Environment=ROBOHUB_WORKSPACE=$(dirname "$ROBOHUB")
Environment=RHO_HTTP_ADDR=$KEEPER_LISTEN:$KEEPER_PORT
Environment=ROBOHUB_APP_WORKSPACE=$WORKSPACE
Environment=RHO_APP_WORKSPACE=$WORKSPACE

[Install]
WantedBy=default.target
UNIT

loginctl enable-linger "$(whoami)" 2>/dev/null || true
systemctl --user daemon-reload
# restart, not start: a keeper already running from the unit written before
# picks the new one up.
systemctl --user enable "$SERVICE_NAME" >> "$DEPLOY_LOG" 2>&1 &&
systemctl --user restart "$SERVICE_NAME" >> "$DEPLOY_LOG" 2>&1 || {
    echo "SERVICE START FAILED (user service may need user lingering)"; exit 1
}

echo "[$(date)] Keeper is running on http://$KEEPER_LISTEN:$KEEPER_PORT" | tee -a "$DEPLOY_LOG"