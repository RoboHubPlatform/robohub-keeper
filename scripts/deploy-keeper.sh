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

# If the service already exists and still describes this keeper, just report
# and exit. A unit written before the keeper had a workspace of its own, or for a
# checkout that has moved, is written again.
if systemctl --user is-enabled "$SERVICE_NAME" >/dev/null 2>&1 &&
   grep -q "ROBOHUB_APP_WORKSPACE" "$SERVICE_FILE" 2>/dev/null &&
   grep -qx "ExecStart=$KEEPER/build/keeper" "$SERVICE_FILE" &&
   grep -qx "Environment=ROBOHUB_ROOT=$ROBOHUB" "$SERVICE_FILE" &&
   grep -qx "Environment=ROBOHUB_WORKSPACE=$(dirname "$ROBOHUB")" "$SERVICE_FILE" &&
   grep -q "^Environment=PATH=$(dirname "$RHO"):" "$SERVICE_FILE" &&
   grep -qx "Environment=RHO_HTTP_ADDR=$KEEPER_LISTEN:$KEEPER_PORT" "$SERVICE_FILE"; then
    echo "[$(date)] $SERVICE_NAME is already deployed."
    echo "  Status: $(systemctl --user is-active "$SERVICE_NAME" 2>/dev/null || echo 'inactive')"
    echo "  Use 'systemctl --user restart $SERVICE_NAME' to restart."
    exit 0
fi

echo "[$(date)] Building keeper …" | tee -a "$DEPLOY_LOG"
cd "$KEEPER"
"$RHO" build . >> "$DEPLOY_LOG" 2>&1 || {
    echo "BUILD FAILED"; exit 1
}

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
ExecStart=$KEEPER/build/keeper
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