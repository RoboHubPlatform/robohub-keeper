#!/usr/bin/env bash
# deploy-app.sh — run an application as a user service. It ships with the keeper,
# which runs it; it reads no manifest and knows no repository layout, because the
# keeper tells it everything:
#
#   deploy-app.sh <name> <app-dir> <port> <command> <origin> [orchestrator] [keeper-port]
#
# origin is `registry` for an application published to the module registry,
# whose package carries its program, and anything else for an application in a
# folder, which is built from its sources with the rho toolchain first.
#
# The first install writes ~/.config/systemd/user/<name>.service and enables it.
# Later runs rebuild and restart the same unit, so the keeper's start and stop
# controls act on one service.
set -euo pipefail

export PATH=$HOME/.local/bin:/usr/local/go/bin:$HOME/.rho/bin:$PATH

NAME="${1:?application name required}"
APP="${2:?application directory required}"
PORT="${3:-}"
COMMAND="${4:-$NAME}"
ORIGIN="${5:-folder}"
ORCHESTRATOR="${6:-}"
KEEPER_PORT="${7:-${RHO_KEEPER_PORT:-19090}}"
RHO="${RHO:-rho}"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT="$UNIT_DIR/$NAME.service"

if [[ ! -f "$APP/module.yml" ]]; then
    echo "$APP/module.yml is missing" >&2
    exit 1
fi
APP="$(cd "$APP" && pwd)"

if [[ "$ORIGIN" == "registry" ]]; then
    # A published application is run as it was published.
    PROGRAM="$APP/$COMMAND"
else
    echo "Building $NAME …"
    cd "$APP"
    # A generated project can outlive the toolchain that wrote it; start from the
    # sources so a new template or locale feature is really in the build.
    rm -rf "$APP/build/generated"
    "$RHO" build . || { echo "BUILD FAILED"; exit 1; }
    PROGRAM="$APP/build/$COMMAND"
fi

if [[ -z "$PORT" || ! -x "$PROGRAM" ]]; then
    echo "$NAME has no serveable application block; no service was installed."
    exit 0
fi

# The orchestrator the keeper belongs to, when it has one: a hosted application
# reads the same registry the keeper does.
ORCHESTRATOR_ENV=""
if [[ -n "$ORCHESTRATOR" && -d "$ORCHESTRATOR" ]]; then
    ORCHESTRATOR="$(cd "$ORCHESTRATOR" && pwd)"
    # The workspace is the folder that holds the repositories, the orchestrator
    # among them, so it is said by where the orchestrator is rather than taken
    # from the keeper's environment, which a unit written before may have wrong.
    ORCHESTRATOR_ENV="Environment=ROBOHUB_ROOT=$ORCHESTRATOR
Environment=ROBOHUB_WORKSPACE=$(dirname "$ORCHESTRATOR")
"
fi

# An application that calls other services was registered as a client by the
# keeper before this ran, which wrote the environment it reads into its
# workspace: its client id, where its secret is (never the secret), the issuer and
# the services it calls.
WORKSPACE="$HOME/.rho/keeper/workspaces/$NAME"
CLIENT_ENV=""
if [[ -f "$WORKSPACE/auth/client.env" ]]; then
    CLIENT_ENV="EnvironmentFile=$WORKSPACE/auth/client.env
"
fi

echo "Writing $UNIT …"
mkdir -p "$UNIT_DIR" "$WORKSPACE"
cat > "$UNIT" <<UNIT
[Unit]
Description=RoboHub $NAME
After=network.target

[Service]
Type=simple
WorkingDirectory=$APP
Environment=HOME=$HOME
Environment=PATH=$PATH
${ORCHESTRATOR_ENV}Environment=RHO_APP_WORKSPACE=$WORKSPACE
Environment=ROBOHUB_APP_WORKSPACE=$WORKSPACE
Environment=ROBOHUB_APP_MANIFEST=$APP/module.yml
Environment=RHO_KEEPER_PORT=$KEEPER_PORT
Environment=RHO_HTTP_ADDR=:$PORT
${CLIENT_ENV}ExecStart=$PROGRAM
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
UNIT

loginctl enable-linger "$(whoami)" 2>/dev/null || true
systemctl --user daemon-reload
systemctl --user enable "$NAME" >/dev/null
systemctl --user restart "$NAME"
echo "Done: $NAME is running on port $PORT."
