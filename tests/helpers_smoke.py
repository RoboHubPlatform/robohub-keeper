#!/usr/bin/env python3
"""Smoke test for supervision: the units the keeper writes and the helpers it runs (robohub ADR-0018).

Builds the keeper and starts it against a scratch HOME and state folder whose
catalogue holds two applications: `zapp`, which declares `helpers: [z2m-*,
gateway-*]` and `deploy.limits: {memory: 4G, tasks: 4096}`, and `wapp`, which
declares no helper and a memory limit that is not one. Their programs are files
in their release folders, one carrying the sd_notify marker. systemctl is a
stand-in that records every call and remembers which unit it started, so
nothing on this machine is started, stopped or reloaded — the isolation probe
included — and the live keeper's ~/.rho/keeper is never touched.

It checks the application units (restart policy, Type=notify on a marked program
and simple without, the limits, a refused limit and the note when this machine
cannot enforce them), the isolation probe (a unit written and started through
systemctl --user, removed, a kept `no` asked again once), and the helpers API:
the App credential (401), loopback and declared patterns (403), what a helper may
be given (400), the unit it gets, listing, start/stop/restart, removal, the
application's page, a restart of the application leaving its helpers alone,
uninstalling removing them, and the events.

    python3 tests/helpers_smoke.py
"""

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve()
KEEPER = HERE.parents[1]
PROJECTS = KEEPER.parent
ROBOHUB = Path(os.environ.get("ROBOHUB_ROOT", PROJECTS / "robohub")).resolve()
RHO = PROJECTS / "rho" / "bin" / "rho"
RHO_CMD = str(RHO) if RHO.exists() else (shutil.which("rho") or "rho")

# A session id as the keeper makes them: 16 random bytes, as hex.
ADMIN = "a1000000000000000000000000000001"
# The applications' client secrets, as `rho auth client add --secret-out` writes them.
SECRET = "e0" * 32
WSECRET = "f0" * 32
WRONG = "e1" * 32

MARKER = b"rho-sd-notify-v1"

FAILURES = []


def expect(condition: bool, what: str) -> None:
    if condition:
        print(f"[PASS] {what}")
    else:
        FAILURES.append(what)
        print(f"[FAIL] {what}")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for(base: str, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base + "/healthz", timeout=1) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.2)
    raise SystemExit(f"keeper did not start at {base}")


def call(base: str, method: str, path: str, body=None, headers=None, session: str = "", form=None, raw=None) -> tuple:
    data = None
    request_headers = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode()
        request_headers["Content-Type"] = "application/json"
    if raw is not None:
        data = raw.encode()
        request_headers["Content-Type"] = "application/json"
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        request_headers["Content-Type"] = "application/x-www-form-urlencoded"
        request_headers["Origin"] = base
    if session:
        request_headers["Cookie"] = f"keeper_session={session}"
    request = urllib.request.Request(base + path, data=data, method=method, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as answer:
        return answer.code, answer.read().decode("utf-8", "replace")


def app(name: str, secret: str) -> dict:
    return {"Authorization": f"App {name}:{secret}"}


def parsed(text: str) -> dict:
    try:
        return json.loads(text)
    except ValueError:
        return {}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


ZAPP_MANIFEST = """module:
  name: zapp
  type: rho
  version: 0.1.0
main: src/main.rho
application:
  kind: keeper-hosted
  title: Z App
  port: "9013"
  command: zapp
helpers: [z2m-*, gateway-*]
deploy:
  limits: {memory: 4G, tasks: 4096}
"""

WAPP_MANIFEST = """module:
  name: wapp
  type: rho
  version: 0.1.0
main: src/main.rho
application:
  kind: keeper-hosted
  title: W App
  port: "9014"
  command: wapp
deploy:
  limits:
    memory: 2GB
    cpu_weight: 500
"""

# systemctl, as far as this test needs it: every call is recorded; start and
# restart make a unit active, stop and disable --now inactive; is-active answers
# what it was left as. The isolation probe's unit is copied when it is started,
# and fails when the test asks it to.
SYSTEMCTL = """#!/bin/sh
echo "$*" >> "$SMOKE_SYSTEMD/calls"
[ "$1" = "--user" ] && shift
verb="$1"; shift
now=""
if [ "$1" = "--now" ]; then now=1; shift; fi
unit="$1"
case "$verb" in
  start|restart)
    if [ "$unit" = "rh-keeper-isolation-probe.service" ]; then
      cp "$HOME/.config/systemd/user/$unit" "$SMOKE_SYSTEMD/probe-unit" 2>/dev/null
      [ -e "$SMOKE_SYSTEMD/fail-probe" ] && exit 1
    fi
    echo active > "$SMOKE_SYSTEMD/state-$unit";;
  stop) echo inactive > "$SMOKE_SYSTEMD/state-$unit";;
  disable) [ -n "$now" ] && echo inactive > "$SMOKE_SYSTEMD/state-$unit";;
  is-active)
    state=$(cat "$SMOKE_SYSTEMD/state-$unit" 2>/dev/null || echo inactive)
    echo "$state"
    [ "$state" = active ] && exit 0
    exit 3;;
esac
exit 0
"""


def build_keeper() -> Path:
    result = subprocess.run([RHO_CMD, "build", "."], cwd=KEEPER, text=True, capture_output=True)
    if result.returncode != 0:
        raise SystemExit("keeper build failed:\n" + result.stdout + result.stderr)
    return KEEPER / "build" / "keeper"


def start(binary: Path, env: dict, addr: str) -> subprocess.Popen:
    run_env = dict(env)
    run_env["RHO_HTTP_ADDR"] = addr
    return subprocess.Popen([str(binary)], cwd=ROBOHUB, env=run_env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def stop(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


class Healthy(BaseHTTPRequestHandler):
    """What answers for zapp while a job waits for it: /healthz is 200."""

    def do_GET(self):
        self.send_response(200 if self.path == "/healthz" else 404)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        pass


def wait_jobs(state: Path, timeout: float = 60.0) -> list:
    deadline = time.time() + timeout
    while time.time() < deadline:
        statuses = [p.read_text(encoding="utf-8").split("\n")[0] for p in (state / "jobs").glob("*/status")]
        if statuses and "running" not in statuses:
            return statuses
        time.sleep(0.3)
    return ["timeout"]


def program(path: Path, marked: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = b"\x7fELF\x00\x00fake program\x00"
    if marked:
        content += b"\x00const " + MARKER + b"\x00"
    path.write_bytes(content + b"\x00end\n")
    path.chmod(0o755)


def main() -> int:
    binary = build_keeper()
    port = free_port()
    zapp_port = free_port()
    health = HTTPServer(("127.0.0.1", zapp_port), Healthy)
    threading.Thread(target=health.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="keeper-helpers-") as home_dir:
        home = Path(home_dir)
        live = Path(os.path.expanduser("~")) / ".rho" / "keeper"
        state = home / "state"
        state.mkdir()
        assert state.resolve() != live.resolve()
        catalogue = ""
        for name, manifest, port_of in (("zapp", ZAPP_MANIFEST, str(zapp_port)), ("wapp", WAPP_MANIFEST, "9014")):
            folder = home / name
            folder.mkdir()
            (folder / "module.yml").write_text(manifest, encoding="utf-8")
            catalogue += (f"  {name}:\n    origin: \"external\"\n    location: \"{folder}\"\n"
                          f"    version: \"0.1.0\"\n    port: \"{port_of}\"\n    unit: \"{name}\"\n")
        (state / "installed.yml").write_text("# The applications this keeper runs.\napps:\n" + catalogue, encoding="utf-8")
        for name, secret in (("zapp", SECRET), ("wapp", WSECRET)):
            auth = state / "workspaces" / name / "auth"
            auth.mkdir(parents=True)
            (auth / "client.secret").write_text(secret + "\n", encoding="utf-8")
            (auth / "client.secret").chmod(0o600)
            # What it is a client for, as the keeper records it, so writing its
            # unit does not register it again with a new secret.
            (auth / "client.wanted").write_text("keeper|keeper:read\n", encoding="utf-8")
        # zapp runs from releases: an older one built without the marker, and
        # the one in use, built with it.
        releases = state / "apps" / "zapp" / "releases"
        older = releases / "0.1.0-20261119000000"
        newer = releases / "0.1.0-20261120000000"
        program(older / "zapp", False)
        program(newer / "zapp", True)
        (state / "apps" / "zapp" / "current").symlink_to(newer)
        program(state / "apps" / "wapp" / "current" / "wapp", False)
        expiry = int(time.time()) + 3600
        for folder in (state, home / ".rho" / "keeper"):
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "auth-sessions.txt").write_text(f"{ADMIN}|{expiry}|smoke|*\n", encoding="utf-8")
        keys = home / ".rho" / "auth"
        keys.mkdir(parents=True)
        subprocess.run([RHO_CMD, "auth", "keygen", "--dir", str(keys), "--force"],
                       check=True, capture_output=True, text=True)
        # What the old systemd-run probe kept on a machine without a user D-Bus.
        (state / "isolation.txt").write_text("no\n", encoding="utf-8")
        controllers = home / "cgroup.controllers"
        controllers.write_text("cpuset cpu io pids\n", encoding="utf-8")
        systemd = home / "systemd"
        systemd.mkdir()
        env = dict(os.environ)
        env.setdefault("RHO_HOME", os.path.join(os.path.expanduser("~"), ".rho"))
        env["ROBOHUB_WORKSPACE"] = str(home / "workspace")
        env["RHO_KEEPER_STATE_DIR"] = str(state)
        env["RHO_KEEPER_CGROUP_CONTROLLERS"] = str(controllers)
        env["HOME"] = str(home)
        env["SMOKE_SYSTEMD"] = str(systemd)
        fake = home / "fake-bin"
        fake.mkdir()
        (fake / "systemctl").write_text(SYSTEMCTL, encoding="utf-8")
        (fake / "systemctl").chmod(0o755)
        for name in ("loginctl", "systemd-run"):
            (fake / name).write_text("#!/bin/sh\necho \"$0 $*\" >> \"$SMOKE_SYSTEMD/calls\"\nexit 0\n", encoding="utf-8")
            (fake / name).chmod(0o755)
        env["PATH"] = str(fake) + os.pathsep + env.get("PATH", "")
        units = home / ".config" / "systemd" / "user"
        calls = systemd / "calls"

        # A helper's program and folder, on this machine outside the keeper's.
        tools = home / "tools"
        tools.mkdir()
        helper_program = tools / "helper.sh"
        helper_program.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        helper_program.chmod(0o755)
        plain_file = tools / "notes.txt"
        plain_file.write_text("not a program\n", encoding="utf-8")
        helper_dir = home / "hdir"
        helper_dir.mkdir()
        key_file = state / "workspaces" / "zapp" / "gateway.key"
        key_file.write_text("k" * 32 + "\n", encoding="utf-8")
        other_program = state / "workspaces" / "wapp" / "tool"
        program(other_program, False)
        keys_program = keys / "tool"
        program(keys_program, False)

        process = start(binary, env, f"127.0.0.1:{port}")
        try:
            wait_for(base)
            status, page = call(base, "GET", "/applications", session=ADMIN)
            token = re.search(r'name="csrf" value="([0-9a-f]+)"', page)
            csrf = token.group(1) if token else ""
            expect(token is not None, "the Applications page draws a form token")

            def restart(name: str) -> int:
                status, _ = call(base, "POST", "/applications/restart", session=ADMIN, form={"name": name, "csrf": csrf})
                return status

            # @verifies KEEP-APPS-0021
            # The kept `no` from the old probe is asked again, through a unit
            # written for it and systemctl --user, and the answer kept as -v2.
            status = restart("zapp")
            said = read(calls)
            probe = read(systemd / "probe-unit")
            expect(status == 200, f"the application is restarted ({status})")
            expect("--user daemon-reload" in said and "--user start rh-keeper-isolation-probe.service" in said,
                   "the probe is a unit started through systemctl --user")
            expect("systemd-run" not in said, "systemd-run is not asked")
            expect("Type=oneshot" in probe and "NoNewPrivileges=yes" in probe and
                   "PrivateUsers=yes" in probe and f"TemporaryFileSystem={state}:ro" in probe and f"InaccessiblePaths=-{keys}/private.pem" in probe and
                   "ExecStart=/bin/true" in probe, "the probe unit asks for the view an application gets")
            expect(not (units / "rh-keeper-isolation-probe.service").exists(), "the probe unit is removed afterwards")
            expect(read(state / "isolation.txt").strip() == "yes-v3", "its answer is kept as yes-v3")

            # @verifies KEEP-APPS-0017, KEEP-APPS-0018, KEEP-APPS-0019
            unit = read(units / "zapp.service")
            expect("StartLimitIntervalSec=0" in unit.split("[Service]")[0], "the start limit is off, in [Unit]")
            expect("Restart=always\nRestartSec=5\nTimeoutStopSec=20\n" in unit, "restarted always, after 5 s, killed after 20 s")
            expect("Restart=on-failure" not in unit, "not only on failure")
            expect("Type=notify\nNotifyAccess=main\nWatchdogSec=30\n" in unit, "a program with the marker is watched")
            expect("MemoryMax=4G\nTasksMax=4096\nCPUWeight=100\n" in unit,
                   "the limits a one-line map declares, with the default weight")
            expect("PrivateUsers=yes" in unit and f"TemporaryFileSystem={state}:ro" in unit, "with isolation now that the probe said yes")

            # A probe that cannot run says no, and that no is kept: asked once.
            (state / "isolation.txt").write_text("no\n", encoding="utf-8")
            (systemd / "fail-probe").write_text("", encoding="utf-8")
            restart("wapp")
            expect(read(state / "isolation.txt").strip() == "no-v3", "a probe systemd refuses is kept as no-v3")
            expect("--user reset-failed rh-keeper-isolation-probe.service" in read(calls), "its failed unit is reset")
            probes = read(calls).count("start rh-keeper-isolation-probe.service")
            restart("wapp")
            expect(read(calls).count("start rh-keeper-isolation-probe.service") == probes, "a kept no-v3 is not asked again")
            (systemd / "fail-probe").unlink()

            wunit = read(units / "wapp.service")
            expect("Type=simple\n" in wunit and "WatchdogSec" not in wunit and "NotifyAccess" not in wunit,
                   "a program without the marker is a plain process with no watchdog")
            expect("MemoryMax=2G\nTasksMax=1024\nCPUWeight=500\n" in wunit,
                   "a refused memory limit keeps the default; the others are taken")
            expect("TemporaryFileSystem" not in wunit and "NoNewPrivileges=yes" in wunit, "no isolation after a no")
            status, page = call(base, "GET", "/apps/wapp", session=ADMIN)
            expect(status == 200 and "deploy.limits.memory = 2GB: memory is a size such as 512M or 2G" in page,
                   "the application's page says which limit was refused and why")
            expect("Not enforced on this machine" in page, "and that this machine without cgroup v2 does not enforce them")
            controllers.write_text("cpuset cpu io memory hugetlb pids\n", encoding="utf-8")
            status, page = call(base, "GET", "/apps/wapp", session=ADMIN)
            expect("Not enforced on this machine" not in page and "CPU weight" in page,
                   "on a machine with cgroup v2 and memory the limits are shown without the note")

            # The program in use loses its marker: the unit no longer watches it.
            program(state / "apps" / "zapp" / "current" / "zapp", False)
            (state / "isolation.txt").write_text("yes-v3\n", encoding="utf-8")
            restart("zapp")
            unit = read(units / "zapp.service")
            expect("Type=simple\n" in unit and "WatchdogSec" not in unit, "a program without the marker is no longer watched")

            # @verifies KEEP-APPS-0020
            good = {"name": "z2m-home-zb1", "program": str(helper_program), "args": ["--x", "a b", "100%", "$HOME", 'say "hi"'],
                    "dir": str(helper_dir), "env": {"ZIGBEE2MQTT_DATA": "/w/z2m", "Z2M_ONBOARD_NO_SERVER": "1"}}
            status, text = call(base, "POST", "/api/v1/helpers", good)
            expect(status == 401 and "error" in parsed(text), f"no credential is refused ({status})")
            status, _ = call(base, "POST", "/api/v1/helpers", good, app("zapp", WRONG))
            expect(status == 401, f"a wrong secret is refused ({status})")
            status, _ = call(base, "POST", "/api/v1/helpers", good, {"Authorization": f"Bus zapp:{SECRET}"})
            expect(status == 401, f"another scheme is refused ({status})")
            status, _ = call(base, "POST", "/api/v1/helpers", good, app("nosuch", SECRET))
            expect(status == 401, f"a name that is no application is refused ({status})")
            status, _ = call(base, "POST", "/api/v1/helpers", good, app("zapp", WSECRET))
            expect(status == 401, f"another application's secret is refused ({status})")
            status, _ = call(base, "POST", "/api/v1/helpers", good, session=ADMIN)
            expect(status == 401, f"an admin's session is no application credential ({status})")
            status, _ = call(base, "POST", "/api/v1/helpers", good, {**app("zapp", SECRET), "X-Forwarded-For": "203.0.113.9"})
            expect(status == 403, f"a request a proxy forwarded is not a loopback one ({status})")
            status, text = call(base, "POST", "/api/v1/helpers", {**good, "name": "shell"}, app("zapp", SECRET))
            expect(status == 403 and "helpers:" in text, f"a name no declared pattern matches is refused ({status})")
            status, _ = call(base, "POST", "/api/v1/helpers", {**good, "name": "z2m-a"}, app("wapp", WSECRET))
            expect(status == 403, f"an application that declares no helpers runs none ({status})")
            refused = {
                "a name with a dot": {"name": "z2m-a.b"},
                "no name": {"name": ""},
                "a relative program": {"program": "helper.sh"},
                "a program with a .. part": {"program": str(tools / ".." / "tools" / "helper.sh")},
                "a program that is not executable": {"program": str(plain_file)},
                "a program that is not there": {"program": str(tools / "missing")},
                "a program in another application's workspace": {"program": str(other_program)},
                "a program among the keeper's keys": {"program": str(keys_program)},
                "a folder that is not there": {"dir": str(home / "nowhere")},
                "a folder that is a file": {"dir": str(plain_file)},
                "arguments that are not strings": {"args": [1, 2]},
                "an argument with a line break": {"args": ["a\nExecStartPre=/bin/sh"]},
                "a password in the environment": {"env": {"MQTT_PASSWORD": "hunter2"}},
                "a token in the environment": {"env": {"API_TOKEN": "abc"}},
                "a key that is no file": {"env": {"RELAY_KEY": "00ff00ff00ff"}},
                "a key file that is not there": {"env": {"GATEWAY_KEY_FILE": str(home / "nokey")}},
                "a lowercase environment name": {"env": {"lower": "x"}},
                "an environment value with a line break": {"env": {"A": "x\nExecStart=/bin/sh"}},
                "an environment value that is not a string": {"env": {"A": 1}},
            }
            for what, change in refused.items():
                status, text = call(base, "POST", "/api/v1/helpers", {**good, **change}, app("zapp", SECRET))
                expect(status == 400 and "error" in parsed(text), f"{what} is refused ({status} {parsed(text).get('error', '')})")
            expect(not list(units.glob("rh-zapp-*")), "a refused request writes no unit")

            status, text = call(base, "POST", "/api/v1/helpers", good, app("zapp", SECRET))
            answer = parsed(text)
            hunit = units / "rh-zapp-z2m-home-zb1.service"
            log = state / "workspaces" / "zapp" / "helpers" / "z2m-home-zb1.log"
            expect(status == 200 and answer.get("unit") == "rh-zapp-z2m-home-zb1.service" and answer.get("state") == "active" and
                   answer.get("log") == str(log), f"a declared helper is written and started ({status} {text})")
            htext = read(hunit)
            expect("[Unit]\nDescription=RoboHub zapp helper z2m-home-zb1\nStartLimitIntervalSec=0\n" in htext, "its unit is described and never given up on")
            expect(f"[Service]\nType=simple\nWorkingDirectory={helper_dir}\n" in htext, "it starts in its folder")
            expect('Environment="ZIGBEE2MQTT_DATA=/w/z2m"\nEnvironment="Z2M_ONBOARD_NO_SERVER=1"\n' in htext, "with its environment")
            expect(f'ExecStart="{helper_program}" "--x" "a b" "100%%" "$$HOME" "say \\"hi\\""\n' in htext,
                   "its program and arguments, each one word, nothing expanded")
            expect("\nUMask=0077\n" in htext.split("[Install]")[0], "what it writes is readable by its user only")
            expect("NoNewPrivileges=yes\n" in htext and "Restart=always\nRestartSec=5\nTimeoutStopSec=20\n" in htext,
                   "no new privileges, and the restart policy of every unit")
            expect(f"TemporaryFileSystem={state}:ro" in htext and f"BindPaths={state}/workspaces/zapp" in htext,
                   "the isolation its application has")
            expect(f"StandardOutput=append:{log}\nStandardError=append:{log}\n" in htext and log.parent.is_dir(),
                   "its output appended to a log in the application's workspace")
            expect("WantedBy=default.target" in htext and "PartOf" not in htext and "BindsTo" not in htext,
                   "started at boot, not bound to its application")
            said = read(calls)
            expect("--user enable rh-zapp-z2m-home-zb1.service" in said and "--user restart rh-zapp-z2m-home-zb1.service" in said,
                   "it is enabled and (re)started")
            expect(read(state / "services" / "helpers.txt") == "zapp|z2m-home-zb1\n", "it is kept in services/helpers.txt")

            restarts = read(calls).count("restart rh-zapp-z2m-home-zb1.service")
            changed = {**good, "args": ["--y"], "env": {"GATEWAY_KEY_FILE": str(key_file)}}
            status, text = call(base, "POST", "/api/v1/helpers", changed, app("zapp", SECRET))
            htext = read(hunit)
            expect(status == 200 and '"--y"' in htext and '"--x"' not in htext and f'Environment="GATEWAY_KEY_FILE={key_file}"' in htext,
                   f"asking again writes the unit as it now says; a key is given as its file ({status})")
            expect(read(calls).count("restart rh-zapp-z2m-home-zb1.service") == restarts + 1, "and restarts it")
            expect(read(state / "services" / "helpers.txt") == "zapp|z2m-home-zb1\n", "and keeps it once")

            status, text = call(base, "POST", "/api/v1/helpers",
                                {**good, "name": "gateway-home", "program": "/usr/bin/env", "env": {},
                                 "args": [f"GATEWAY_KEY_FILE={key_file}", str(helper_program)]}, app("zapp", SECRET))
            expect(status == 200 and f'ExecStart="/usr/bin/env" "GATEWAY_KEY_FILE={key_file}"' in read(units / "rh-zapp-gateway-home.service"),
                   f"a second helper, through /usr/bin/env with its arguments as given ({status} {text})")
            status, text = call(base, "GET", "/api/v1/helpers", headers=app("zapp", SECRET))
            listed = parsed(text).get("helpers", [])
            expect(status == 200 and [h.get("name") for h in listed] == ["z2m-home-zb1", "gateway-home"] and
                   all(h.get("state") == "active" and h.get("unit", "").startswith("rh-zapp-") and h.get("log") for h in listed),
                   f"the application's helpers are listed with their state, unit and log ({text})")
            status, text = call(base, "GET", "/api/v1/helpers", headers=app("wapp", WSECRET))
            expect(status == 200 and parsed(text).get("helpers") == [], "another application sees none of them")
            status, _ = call(base, "GET", "/api/v1/helpers")
            expect(status == 401, f"listing needs the credential too ({status})")

            status, text = call(base, "POST", "/api/v1/helpers/z2m-home-zb1/stop", headers=app("zapp", SECRET))
            expect(status == 200 and parsed(text).get("state") == "inactive", f"a helper is stopped ({status} {text})")
            status, text = call(base, "POST", "/api/v1/helpers/z2m-home-zb1/start", headers=app("zapp", SECRET))
            expect(status == 200 and parsed(text).get("state") == "active", f"and started ({status} {text})")
            status, text = call(base, "POST", "/api/v1/helpers/z2m-home-zb1/restart", headers=app("zapp", SECRET))
            expect(status == 200 and parsed(text).get("state") == "active", f"and restarted ({status})")
            status, _ = call(base, "POST", "/api/v1/helpers/z2m-home-zb1/kill", headers=app("zapp", SECRET))
            expect(status == 400, f"an action that is not one is refused ({status})")
            status, _ = call(base, "POST", "/api/v1/helpers/z2m-other/stop", headers=app("zapp", SECRET))
            expect(status == 404, f"a helper the application does not have is not found ({status})")
            status, _ = call(base, "POST", "/api/v1/helpers/z2m-home-zb1/stop", headers=app("wapp", WSECRET))
            expect(status == 404, f"nor another application's ({status})")

            status, page = call(base, "GET", "/apps/zapp", session=ADMIN)
            expect(status == 200 and "Helpers" in page and "z2m-home-zb1" in page and "gateway-home" in page and
                   "rh-zapp-z2m-home-zb1.service" in page and ">active<" in page,
                   "the application's page lists its helpers with their state")
            expect("Memory" in page and "4G" in page, "and its limits")

            # @verifies KEEP-APPS-0018
            # A rollback to a release built without the marker: the unit was
            # written for a watched program, so the job says in a drop-in that
            # the release now in use is a plain process, before restarting it.
            program(newer / "zapp", True)
            restart("zapp")
            expect("Type=notify" in read(units / "zapp.service"), "the release in use is watched again")
            mark = len(read(calls))
            status, _ = call(base, "POST", "/overview/app/zapp/rollback", session=ADMIN, form={"csrf": csrf})
            statuses = wait_jobs(state)
            dropin = units / "zapp.service.d" / "keeper-type.conf"
            expect(status == 200 and statuses == ["done"] and os.readlink(state / "apps" / "zapp" / "current") == str(older),
                   f"the rollback job puts the older release in use ({status}, {statuses})")
            expect("Type=simple\nNotifyAccess=none\nWatchdogSec=0\n" in read(dropin),
                   "a drop-in makes the unmarked release a plain process with no watchdog")
            job_calls = read(calls)[mark:]
            expect(0 <= job_calls.find("--user daemon-reload") < job_calls.find("--user restart zapp"),
                   f"systemd is reloaded, then the application restarted ({job_calls.strip()!r})")
            restart("zapp")
            expect(not dropin.exists() and "Type=simple\n" in read(units / "zapp.service") and
                   "WatchdogSec" not in read(units / "zapp.service"),
                   "writing the unit again folds the drop-in into it")

            # A restart of the application leaves its helpers running.
            before = read(calls)
            restart("zapp")
            after = read(calls)[len(before):]
            expect("rh-zapp-" not in after, f"restarting the application does not touch its helpers ({after.strip()!r})")
            status, text = call(base, "GET", "/api/v1/helpers", headers=app("zapp", SECRET))
            expect(all(h.get("state") == "active" for h in parsed(text).get("helpers", [])), "they are still active")

            status, text = call(base, "DELETE", "/api/v1/helpers/gateway-home", headers=app("zapp", WRONG))
            expect(status == 401, f"removing needs the credential ({status})")
            status, text = call(base, "DELETE", "/api/v1/helpers/gateway-home", headers=app("zapp", SECRET))
            expect(status == 200 and parsed(text).get("removed") == "rh-zapp-gateway-home.service", f"a helper is removed ({status} {text})")
            expect("--user disable --now rh-zapp-gateway-home.service" in read(calls) and not (units / "rh-zapp-gateway-home.service").exists(),
                   "it is stopped and disabled, and its unit removed")
            expect(read(state / "services" / "helpers.txt") == "zapp|z2m-home-zb1\n", "and it is forgotten")
            status, _ = call(base, "DELETE", "/api/v1/helpers/gateway-home", headers=app("zapp", SECRET))
            expect(status == 404, f"removing it again finds nothing ({status})")

            # Uninstalling the application removes every helper it runs.
            status, _ = call(base, "POST", "/applications/uninstall", session=ADMIN, form={"name": "zapp", "csrf": csrf})
            expect(not hunit.exists() and "--user disable --now rh-zapp-z2m-home-zb1.service" in read(calls),
                   f"uninstalling the application removes its helpers ({status})")
            expect("zapp|" not in read(state / "services" / "helpers.txt"), "and forgets them")

            events = read(state / "events.log")
            expect('"kind":"helper.started"' in events and "rh-zapp-z2m-home-zb1.service was started for zapp." in events,
                   "starting a helper is an event")
            expect('"kind":"helper.stopped"' in events, "stopping one is an event")
            expect('"kind":"helper.removed"' in events and "rh-zapp-z2m-home-zb1.service was removed with zapp." in events,
                   "removing one, by the application and with it, is an event")
            expect('"kind":"helper.refused"' in events and "MQTT_PASSWORD names a secret" in events, "a refusal is an event")
            expect(SECRET not in events and "hunter2" not in events, "no event carries a secret")
        finally:
            stop(process)
            health.shutdown()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed:")
        for failure in FAILURES:
            print("  -", failure)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
