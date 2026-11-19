#!/usr/bin/env python3
"""Smoke test for broker users the keeper issues to applications (ADR-0006).

Builds the keeper and starts it against a scratch HOME and state folder whose
catalogue holds the MQTT integration (robohub-mqtt from the orchestrator's
plugins/) and one application that binds the bus and declares `issue: [zigbee]`.
Nothing is started: systemctl is a stand-in that does nothing, so the broker's
files are written but no broker runs. The users are hashed by the machine's
mosquitto_passwd; without one, a stand-in leaves them as they are and the test
says so.

It then asks for users the way Mesh does — `POST /api/v1/bus/users` with
`Authorization: Bus <app>:<password>` — and checks the answers, the files the
broker reads, the Clients tab, the events, removal by the application and
removal with the application.

    python3 tests/bus_users_smoke.py
"""

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve()
KEEPER = HERE.parents[1]
PROJECTS = KEEPER.parent
ROBOHUB = Path(os.environ.get("ROBOHUB_ROOT", PROJECTS / "robohub")).resolve()
MQTT_PLUGIN = ROBOHUB / "plugins" / "robohub-mqtt"
RHO = PROJECTS / "rho" / "bin" / "rho"
RHO_CMD = str(RHO) if RHO.exists() else (shutil.which("rho") or "rho")

# A session id as the keeper makes them: 16 random bytes, as hex.
ADMIN = "a1000000000000000000000000000001"
# The application's broker password, as bus_password makes them: 24 bytes, as hex.
PASSWORD = "b0" * 24
OTHER = "c0" * 24

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


def call(base: str, method: str, path: str, body=None, headers=None, session: str = "", form=None) -> tuple:
    data = None
    request_headers = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode()
        request_headers["Content-Type"] = "application/json"
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        request_headers["Content-Type"] = "application/x-www-form-urlencoded"
        request_headers["Origin"] = base
    if session:
        request_headers["Cookie"] = f"keeper_session={session}"
    request = urllib.request.Request(base + path, data=data, method=method, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as answer:
        return answer.code, answer.read().decode("utf-8", "replace")


def bus(app: str, password: str) -> dict:
    return {"Authorization": f"Bus {app}:{password}"}


def parsed(text: str) -> dict:
    try:
        return json.loads(text)
    except ValueError:
        return {}


def lan_address() -> str:
    """This machine's address on its network, or "" when it has none."""
    try:
        out = subprocess.run(["ip", "-4", "-o", "route", "get", "1.1.1.1"], capture_output=True, text=True).stdout
    except OSError:
        return ""
    match = re.search(r" src (\d+\.\d+\.\d+\.\d+)", out)
    return match.group(1) if match and not match.group(1).startswith("127.") else ""


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
bind:
  robohub.bus:
    providers: [robohub-provider-mqtt]
bus:
  publish: [zigbee/+/+/+/set]
  subscribe: [zigbee/#]
  issue: [zigbee]
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


def main() -> int:
    if not (MQTT_PLUGIN / "module.yml").exists():
        raise SystemExit(f"robohub-mqtt is not at {MQTT_PLUGIN}")
    binary = build_keeper()
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="keeper-bus-") as home_dir:
        home = Path(home_dir)
        state = home / "state"
        state.mkdir()
        zapp = home / "zapp"
        zapp.mkdir()
        (zapp / "module.yml").write_text(ZAPP_MANIFEST, encoding="utf-8")
        (state / "installed.yml").write_text(
            "# The applications this keeper runs.\napps:\n"
            "  mqtt:\n    origin: \"integration\"\n    location: \"" + str(MQTT_PLUGIN) + "\"\n"
            "    version: \"0.1.1\"\n    port: \"1884\"\n    unit: \"robohub-mqtt\"\n"
            "  zapp:\n    origin: \"external\"\n    location: \"" + str(zapp) + "\"\n"
            "    version: \"0.1.0\"\n    port: \"9013\"\n    unit: \"zapp\"\n", encoding="utf-8")
        secret = state / "workspaces" / "zapp" / "auth" / "bus.secret"
        secret.parent.mkdir(parents=True)
        secret.write_text(PASSWORD + "\n", encoding="utf-8")
        secret.chmod(0o600)
        expiry = int(time.time()) + 3600
        for folder in (state, home / ".rho" / "keeper"):
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "auth-sessions.txt").write_text(f"{ADMIN}|{expiry}|smoke|*\n", encoding="utf-8")
        keys = home / ".rho" / "auth"
        keys.mkdir(parents=True)
        subprocess.run([RHO_CMD, "auth", "keygen", "--dir", str(keys), "--force"],
                       check=True, capture_output=True, text=True)
        env = dict(os.environ)
        env.setdefault("RHO_HOME", os.path.join(os.path.expanduser("~"), ".rho"))
        env["ROBOHUB_WORKSPACE"] = str(home / "workspace")
        env["RHO_KEEPER_STATE_DIR"] = str(state)
        env["HOME"] = str(home)
        # Nothing here may start or stop a real unit.
        fake = home / "fake-bin"
        fake.mkdir()
        (fake / "systemctl").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        (fake / "systemctl").chmod(0o755)
        hashed = shutil.which("mosquitto_passwd") is not None
        if not hashed:
            print("[NOTE] mosquitto_passwd is not installed: a stand-in leaves the users unhashed")
            (fake / "mosquitto_passwd").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            (fake / "mosquitto_passwd").chmod(0o755)
        env["PATH"] = str(fake) + os.pathsep + env.get("PATH", "")
        mqtt = state / "services" / "mqtt"

        process = start(binary, env, f"127.0.0.1:{port}")
        try:
            wait_for(base)
            ask = {"name": "zb1", "prefix": "zigbee/home/zb1"}

            # @verifies KEEP-PROV-0006, KEEP-PROV-0007
            status, text = call(base, "POST", "/api/v1/bus/users", ask, bus("zapp", PASSWORD))
            first = parsed(text)
            expect(status == 200, f"an application with its broker password is issued a user ({status} {text})")
            expect(first.get("user") == "zapp-zb1", "the user is <app>-<name>")
            expect(re.fullmatch(r"[0-9a-f]{48}", first.get("password", "")) is not None, "its password is random")
            expect(first.get("prefix") == "zigbee/home/zb1", "the answer carries the prefix")
            expect(first.get("port") == "1884" and first.get("loopback") == "127.0.0.1",
                   "the answer says the broker's port and loopback address")
            expect(first.get("network") == "", "no network address while the broker listens on the loopback only")

            status, text = call(base, "POST", "/api/v1/bus/users", ask, bus("zapp", PASSWORD))
            again = parsed(text)
            expect(status == 200 and again.get("user") == "zapp-zb1" and again.get("password") == first.get("password"),
                   "asking again answers the same user and password")

            # @verifies KEEP-PROV-0006
            issued = (mqtt / "issued.txt").read_text(encoding="utf-8") if (mqtt / "issued.txt").exists() else ""
            expect(issued == "zapp|zb1|zigbee/home/zb1\n", f"issued.txt holds the user once ({issued!r})")
            user_secret = mqtt / "issued" / "zapp-zb1.secret"
            expect(user_secret.exists() and (user_secret.stat().st_mode & 0o077) == 0,
                   "its password is kept owner-only")
            acl = (mqtt / "acl").read_text(encoding="utf-8") if (mqtt / "acl").exists() else ""
            expect("user zapp-zb1\ntopic readwrite zigbee/home/zb1/#\n" in acl,
                   "the ACL gives the user readwrite under its prefix")
            passwd = (mqtt / "passwd").read_text(encoding="utf-8") if (mqtt / "passwd").exists() else ""
            if hashed:
                expect(re.search(r"^zapp-zb1:\$", passwd, re.M) is not None and first.get("password", "x") not in passwd,
                       "the broker's password file has the user, hashed")
            else:
                expect(re.search(r"^zapp-zb1:", passwd, re.M) is not None,
                       "the broker's password file has the user (not hashed: no mosquitto_passwd)")

            # The same name with another prefix replaces the prefix and keeps the password.
            status, text = call(base, "POST", "/api/v1/bus/users", {"name": "zb1", "prefix": "zigbee/attic/zb1"},
                                bus("zapp", PASSWORD))
            moved = parsed(text)
            acl = (mqtt / "acl").read_text(encoding="utf-8")
            expect(status == 200 and moved.get("password") == first.get("password") and
                   "topic readwrite zigbee/attic/zb1/#" in acl and "zigbee/home/zb1" not in acl,
                   "another prefix for the same name replaces it, with the same password")

            # @verifies KEEP-PROV-0006
            status, text = call(base, "POST", "/api/v1/bus/users", ask, bus("zapp", OTHER))
            expect(status == 401 and "error" in parsed(text), f"a wrong password is refused ({status})")
            status, _ = call(base, "POST", "/api/v1/bus/users", ask)
            expect(status == 401, f"no credential is refused ({status})")
            status, _ = call(base, "POST", "/api/v1/bus/users", ask, bus("mqtt", PASSWORD))
            expect(status == 401, f"a name that is no application binding the bus is refused ({status})")
            status, _ = call(base, "POST", "/api/v1/bus/users", ask, session=ADMIN)
            expect(status == 401, f"an admin's session is no broker credential ({status})")
            for prefix in ("zigbee/#", "zigbee/+/zb1", "zigbee//zb1", "/zigbee/zb1", "zigbee/zb1/", "zigbee/zb 1",
                           "zigbee/zb1\nuser keeper"):
                status, _ = call(base, "POST", "/api/v1/bus/users", {"name": "zb2", "prefix": prefix},
                                 bus("zapp", PASSWORD))
                expect(status == 400, f"the prefix {prefix!r} is refused ({status})")
            for name in ("zb.2", "", "../x", "zb 2"):
                status, _ = call(base, "POST", "/api/v1/bus/users", {"name": name, "prefix": "zigbee/x"},
                                 bus("zapp", PASSWORD))
                expect(status == 400, f"the name {name!r} is refused ({status})")
            status, text = call(base, "POST", "/api/v1/bus/users", {"name": "zb2", "prefix": "tasmota/plug"},
                                bus("zapp", PASSWORD))
            expect(status == 403 and "bus.issue" in text, f"a root the manifest does not declare is refused ({status})")
            status, _ = call(base, "POST", "/api/v1/bus/users", {"name": "zb2", "prefix": "zigbeex/a"},
                             bus("zapp", PASSWORD))
            expect(status == 403, f"a root is a whole level ({status})")
            status, _ = call(base, "POST", "/api/v1/bus/users", ask,
                             {**bus("zapp", PASSWORD), "X-Forwarded-For": "203.0.113.9"})
            expect(status == 403, f"a request a proxy forwarded is not a loopback one ({status})")
            issued = (mqtt / "issued.txt").read_text(encoding="utf-8")
            expect(issued == "zapp|zb1|zigbee/attic/zb1\n", "a refused request issues nothing")

            # A line whose application is gone makes no broker user.
            with open(mqtt / "issued.txt", "a", encoding="utf-8") as lines:
                lines.write("ghost|zb9|zigbee/ghost\n")
            ghost = mqtt / "issued" / "ghost-zb9.secret"
            ghost.write_text("d0" * 24 + "\n", encoding="utf-8")
            ghost.chmod(0o600)
            status, _ = call(base, "POST", "/api/v1/bus/users", {"name": "zb2", "prefix": "zigbee/home/zb2"},
                             bus("zapp", PASSWORD))
            acl = (mqtt / "acl").read_text(encoding="utf-8")
            passwd = (mqtt / "passwd").read_text(encoding="utf-8")
            expect(status == 200 and "user zapp-zb2\n" in acl, "a second user is issued")
            expect("ghost-zb9" not in acl and "ghost-zb9" not in passwd,
                   "a line whose application is not in the catalogue makes no broker user")

            # @verifies KEEP-PROV-0007
            (mqtt / "listen").write_text("lan\n", encoding="utf-8")
            status, text = call(base, "POST", "/api/v1/bus/users", ask, bus("zapp", PASSWORD))
            network = parsed(text).get("network", None)
            expected = lan_address()
            expect(status == 200 and network == expected,
                   f"while the broker is open to the network the answer names this machine's address ({network!r}, {expected!r})")
            (mqtt / "listen").unlink()

            # @verifies KEEP-PROV-0008
            status, page = call(base, "GET", "/overview/app/mqtt?tab=clients", session=ADMIN)
            expect(status == 200 and "zapp-zb1" in page and "zapp-zb2" in page, "the Clients tab lists the issued users")
            expect("issued by zapp · zigbee/home/zb1/#" in page, "with the application that issued each and its prefix")
            expect("ghost-zb9" in page and "not in use" in page, "a line that makes no user is shown as not in use")

            status, text = call(base, "DELETE", "/api/v1/bus/users/zb2", headers=bus("zapp", OTHER))
            expect(status == 401, f"removing needs the application's password too ({status})")
            status, text = call(base, "DELETE", "/api/v1/bus/users/zb2", headers=bus("zapp", PASSWORD))
            expect(status == 200 and parsed(text).get("removed") == "zapp-zb2", f"the application removes a user ({status} {text})")
            acl = (mqtt / "acl").read_text(encoding="utf-8")
            expect("zapp-zb2" not in acl and not (mqtt / "issued" / "zapp-zb2.secret").exists(),
                   "a removed user leaves the broker and its password goes")
            status, _ = call(base, "DELETE", "/api/v1/bus/users/zb2", headers=bus("zapp", PASSWORD))
            expect(status == 404, f"removing it again finds nothing ({status})")

            # Not on a loopback connection: the same keeper on this machine's own
            # network address, asked from that address, refuses.
            address = lan_address()
            if address:
                lan_port = free_port()
                lan = start(binary, env, f"{address}:{lan_port}")
                try:
                    wait_for(f"http://{address}:{lan_port}")
                    status, _ = call(f"http://{address}:{lan_port}", "POST", "/api/v1/bus/users", ask, bus("zapp", PASSWORD))
                    expect(status == 403, f"a request that is not on a loopback connection is refused ({status})")
                finally:
                    stop(lan)
            else:
                print("[NOTE] no network address on this machine: the non-loopback refusal is covered by X-Forwarded-For only")

            # Removing the application removes every user it was issued.
            status, page = call(base, "GET", "/applications", session=ADMIN)
            token = re.search(r'name="csrf" value="([0-9a-f]+)"', page)
            expect(token is not None, "the Applications page draws a form token")
            status, _ = call(base, "POST", "/applications/uninstall", session=ADMIN,
                             form={"name": "zapp", "csrf": token.group(1) if token else ""})
            issued = (mqtt / "issued.txt").read_text(encoding="utf-8")
            acl = (mqtt / "acl").read_text(encoding="utf-8")
            expect("zapp|" not in issued and "zapp-zb1" not in acl and not (mqtt / "issued" / "zapp-zb1.secret").exists(),
                   f"uninstalling the application removes its issued users ({status})")

            said = (state / "events.log").read_text(encoding="utf-8") if (state / "events.log").exists() else ""
            expect('"kind":"bus.user-issued"' in said and "zapp-zb1 may use zigbee/home/zb1/#." in said,
                   "issuing is an event")
            expect('"kind":"bus.user-removed"' in said and "zapp-zb1 was removed with zapp." in said,
                   "removing, by the application and with it, is an event")
            expect('"kind":"bus.user-refused"' in said, "a refusal is an event")
            expect(first.get("password", "x") not in said, "no event carries a password")
        finally:
            stop(process)
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed:")
        for failure in FAILURES:
            print("  -", failure)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
