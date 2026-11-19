#!/usr/bin/env python3
"""Smoke test for the keeper's form tokens.

Builds the keeper and starts it against a scratch HOME and state folder. Every
route that changes something is posted to as an admin without the form token
and with a wrong one, and each must refuse without doing anything: the same
origin check in front of the keeper stops another site, the token stops a
request the page did not draw. The routes are read from src/main.rho, so a POST
route added later without a place in this test fails it.

The Nodes page is walked in full: rotate and revoke refuse a request with no
token, a wrong token, or a reader's session, and do what they say for an admin
with the token, each leaving an event behind.

    python3 tests/forms_smoke.py
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
RHO = PROJECTS / "rho" / "bin" / "rho"
RHO_CMD = str(RHO) if RHO.exists() else (shutil.which("rho") or "rho")

# Session ids as the keeper makes them: 16 random bytes, as hex.
ADMIN = "a1000000000000000000000000000001"    # a ticket with every scope
READER = "e1000000000000000000000000000002"   # a session that is no person's: it reads

CREDENTIAL = "cd" * 32
WRONG = "0" * 64

# The routes that are not a page's form: each is authenticated by what it
# carries (an enrollment token, a node credential, a client secret, a password),
# not by a session cookie another page could make the browser send.
MACHINE = {
    "/api/enroll": "an enrollment token",
    "/api/nodes/verify": "a node credential",
    "/auth/service-token": "a client secret",
    "/auth/login": "a password or the access token; there is no session yet",
    "/app/{name}": "nothing: a redirect to the application's own port, which checks the post",
    "/app/{name}/{path...}": "nothing: a redirect to the application's own port, which checks the post",
}

# Every other POST route, with fields that would act if the token were not
# checked. {name} and the like are filled with names nothing has.
FORMS = {
    "/install": {"module": "nosuch"},
    "/uninstall": {"module": "nosuch"},
    "/nodes/revoke": {"device": "garden-01"},
    "/nodes/rotate": {"device": "garden-01"},
    "/settings": {"log_level": "debug"},
    "/integrations/install": {"name": "nosuch"},
    "/applications/install": {"name": "nosuch", "source": "/nonexistent"},
    "/applications/uninstall": {"name": "nosuch"},
    "/applications/start": {"name": "nosuch"},
    "/applications/stop": {"name": "nosuch"},
    "/applications/redeploy": {"name": "nosuch"},
    "/applications/update": {"name": "nosuch"},
    "/applications/build": {"name": "nosuch"},
    "/applications/restart": {"name": "nosuch"},
    "/applications/menu": {"name": "nosuch", "pinned": "1"},
    "/overview/app/{name}/{action}": {},
    "/api/v1/apps/{name}/{action}": {},
    "/plugins/toggle": {"name": "robohub-provider-email", "enabled": "1"},
    "/plugins/test": {"name": "robohub-provider-log"},
    "/plugins/install": {"name": "nosuch", "source": "/nonexistent"},
    "/plugins/uninstall": {"name": "nosuch"},
    "/people/add": {"name": "mallory", "role": "admin"},
    "/people/claim": {"name": "mallory"},
    "/people/{name}/{action}": {},
    "/account": {"current": "x", "password": "y", "confirm": "y"},
    "/auth/token": {},
    "/auth/rotate-key": {},
    "/providers/install": {"name": "nosuch", "source": "/nonexistent"},
    "/providers/uninstall": {"name": "nosuch"},
    "/app-modules/settings": {"name": "nosuch"},
    "/app-modules/install": {"name": "nosuch", "source": "/nonexistent"},
    "/app-modules/uninstall": {"name": "nosuch"},
    "/developer/requirements/{id}/edit": {"title": "x"},
    "/developer/requirements/{id}/status": {"status": "approved"},
    "/developer/new": {"title": "x"},
    "/developer/adr/new": {"title": "x"},
    "/developer/adr/{repo}/{id}/{action}": {"status": "accepted"},
    "/developer/commit": {"message": "x"},
}

# What a route with parameters is posted to.
CONCRETE = {
    "/overview/app/{name}/{action}": "/overview/app/keeper/rotate-secret",
    "/api/v1/apps/{name}/{action}": "/api/v1/apps/keeper/restart",
    "/people/{name}/{action}": "/people/smoke/remove",
    "/developer/requirements/{id}/edit": "/developer/requirements/KEEP-0001/edit",
    "/developer/requirements/{id}/status": "/developer/requirements/KEEP-0001/status",
    "/developer/adr/{repo}/{id}/{action}": "/developer/adr/robohub/ADR-0001/status",
}

# The words a refusal for the token says, in any of the keeper's forms of it.
REFUSALS = ("not drawn by this keeper", "the form token did not match")

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
        except (urllib.error.URLError, ConnectionError):
            time.sleep(0.2)
    raise SystemExit(f"keeper did not start at {base}")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


def call(base: str, method: str, path: str, session: str = "", fields=None, headers=None) -> tuple:
    data = None
    if fields is not None:
        data = urllib.parse.urlencode(fields).encode()
    request = urllib.request.Request(base + path, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/x-www-form-urlencoded")
    # A browser posting from the keeper's own page.
    request.add_header("Origin", base)
    if session:
        request.add_header("Cookie", f"keeper_session={session}")
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    try:
        with OPENER.open(request, timeout=20) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as answer:
        return answer.code, answer.read().decode("utf-8", "replace")


def token_on(page: str) -> str:
    match = re.search(r'name="csrf" value="([0-9a-f]+)"', page)
    return match.group(1) if match else ""


def post_routes() -> list:
    routes = []
    for line in (KEEPER / "src" / "main.rho").read_text(encoding="utf-8").splitlines():
        match = re.match(r'route\s+(POST|PUT|DELETE|PATCH)\s+"([^"]+)"', line)
        if match:
            routes.append(match.group(2))
    return routes


def refused(status: int, body: str) -> bool:
    return status in (200, 403) and any(words in body for words in REFUSALS)


def events(state: Path) -> str:
    path = state / "events.log"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def build_keeper() -> Path:
    binary = KEEPER / "build" / "keeper"
    result = subprocess.run([RHO_CMD, "build", "."], cwd=KEEPER, text=True, capture_output=True)
    if result.returncode != 0:
        raise SystemExit("keeper build failed:\n" + result.stdout + result.stderr)
    return binary


def main() -> int:
    binary = build_keeper()
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="keeper-forms-") as home_dir:
        home = Path(home_dir)
        state = home / "state"
        nodes = state / "nodes"
        nodes.mkdir(parents=True)
        record = nodes / "garden-01.txt"
        record.write_text(f"garden-01|cHVi|default|1|5|{CREDENTIAL}|1700000000\n", encoding="utf-8")
        record.chmod(0o600)
        # A hosted application in the catalogue, so its inspector has buttons.
        demo = home / "demo-app"
        demo.mkdir()
        (demo / "module.yml").write_text(
            "module:\n  name: demo\n  type: rho\n  version: 0.1.0\nmain: src/main.rho\n"
            "application:\n  kind: keeper-hosted\n  title: Demo App\n  route: /demo\n"
            "  port: \"9009\"\n  command: demo\n", encoding="utf-8")
        expiry = int(time.time()) + 3600
        sessions = f"{ADMIN}|{expiry}|smoke|*\n{READER}|{expiry}|watcher|keeper:read\n"
        for folder in (state, home / ".rho" / "keeper"):
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "auth-sessions.txt").write_text(sessions, encoding="utf-8")
        keys = home / ".rho" / "auth"
        keys.mkdir(parents=True)
        subprocess.run([RHO_CMD, "auth", "keygen", "--dir", str(keys), "--force"],
                       check=True, capture_output=True, text=True)
        public_key = (keys / "public.pem").read_text(encoding="utf-8")
        env = dict(os.environ)
        env.setdefault("RHO_HOME", os.path.join(os.path.expanduser("~"), ".rho"))
        env["ROBOHUB_WORKSPACE"] = str(home / "workspace")
        env["RHO_KEEPER_STATE_DIR"] = str(state)
        env["HOME"] = str(home)
        env["RHO_HTTP_ADDR"] = f"127.0.0.1:{port}"
        # Nothing here may start or stop a real unit.
        fake = home / "fake-bin"
        fake.mkdir()
        (fake / "systemctl").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        (fake / "systemctl").chmod(0o755)
        env["PATH"] = str(fake) + os.pathsep + env.get("PATH", "")
        process = subprocess.Popen([str(binary)], cwd=ROBOHUB, env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            wait_for(base)
            hashed = record.read_text(encoding="utf-8")

            # @verifies KEEP-AUTH-0014
            # Every POST route is either a page's form, which this test posts to,
            # or one authenticated by what it carries.
            routes = post_routes()
            unknown = [r for r in routes if r not in FORMS and r not in MACHINE]
            expect(not unknown, f"every POST route has a place in this test (missing: {unknown})")

            # @verifies KEEP-ENROLL-0008, KEEP-AUTH-0014
            status, page = call(base, "GET", "/nodes", ADMIN)
            token = token_on(page)
            expect(status == 200 and token != "", "the Nodes page draws its forms with the token")
            if not token:
                status, page = call(base, "GET", "/applications", ADMIN)
                token = token_on(page)
            if not token:
                raise SystemExit("no page carries a form token")
            expect(page.count('name="csrf"') >= 2 or "/nodes/rotate" not in page,
                   "both of a node's forms carry the token")

            for action in ("rotate", "revoke"):
                for label, fields in (("no token", {"device": "garden-01"}),
                                      ("a wrong token", {"device": "garden-01", "csrf": WRONG})):
                    status, body = call(base, "POST", f"/nodes/{action}", ADMIN, fields)
                    expect(status == 403 and refused(status, body),
                           f"{action} with {label} is refused ({status})")
                    expect(record.exists() and record.read_text(encoding="utf-8") == hashed,
                           f"{action} with {label} leaves the record as it was")
                status, body = call(base, "POST", f"/nodes/{action}", READER,
                                    {"device": "garden-01", "csrf": token})
                expect(status == 403, f"{action} by a reader with the token is refused ({status})")
                expect(record.exists() and record.read_text(encoding="utf-8") == hashed,
                       f"{action} by a reader leaves the record as it was")
            expect("node." not in events(state), "a refused node action leaves no event")

            status, body = call(base, "POST", "/nodes/rotate", ADMIN, {"device": "garden-01", "csrf": token})
            match = re.search(r"New credential for garden-01: ([0-9a-f]{64})", body)
            expect(status == 200 and match is not None, f"an admin with the token rotates a credential ({status})")
            rotated = record.read_text(encoding="utf-8") if record.exists() else ""
            expect(rotated != hashed and "|s1$" in rotated, "the rotated credential is kept as a new salted hash")
            if match:
                status, _ = call(base, "POST", "/api/nodes/verify", "",
                                 {"device_id": "garden-01", "credential": match.group(1)})
                expect(status == 200, "the new credential verifies")
            status, _ = call(base, "POST", "/api/nodes/verify", "",
                             {"device_id": "garden-01", "credential": CREDENTIAL})
            expect(status == 403, "the old credential no longer verifies")
            said = events(state)
            expect('"kind":"node.rotated"' in said and "garden-01" in said, "a rotation is an event")

            status, body = call(base, "POST", "/nodes/revoke", ADMIN, {"device": "garden-01", "csrf": token})
            expect(status == 200 and "Node garden-01 was revoked" in body and not record.exists(),
                   f"an admin with the token revokes a node ({status})")
            expect('"kind":"node.revoked"' in events(state), "a revocation is an event")
            if match:
                status, _ = call(base, "POST", "/api/nodes/verify", "",
                                 {"device_id": "garden-01", "credential": match.group(1)})
                expect(status == 403, "a revoked node's credential no longer verifies")

            # @verifies KEEP-AUTH-0014
            # Every other form refuses an admin's post without the token, or with
            # a wrong one, before it does anything.
            # Toggling an alert channel writes the keeper's bind.conf.
            plugin_state = home / ".rho" / "apps" / "keeper" / "bind.conf"
            before_plugins = plugin_state.read_text(encoding="utf-8") if plugin_state.exists() else ""
            for route in routes:
                if route in MACHINE:
                    continue
                path = CONCRETE.get(route, route)
                fields = dict(FORMS.get(route, {}))
                for label, extra in (("no token", {}), ("a wrong token", {"csrf": WRONG})):
                    status, body = call(base, "POST", path, ADMIN, {**fields, **extra})
                    if route.startswith("/api/v1/"):
                        ok = status == 403 and "form token" in body
                    else:
                        ok = refused(status, body)
                    expect(ok, f"POST {path} with {label} is refused ({status})")
            expect(public_key == (keys / "public.pem").read_text(encoding="utf-8"),
                   "a refused key rotation leaves the signing key as it was")
            now_plugins = plugin_state.read_text(encoding="utf-8") if plugin_state.exists() else ""
            expect(now_plugins == before_plugins, "a refused plugin toggle changes nothing")

            # An inspector button posts with HTMX outside any form: it carries the
            # token in hx-vals, and a post with it is not refused for the token.
            status, body = call(base, "POST", "/applications/install", ADMIN,
                                {"name": "demo", "source": str(demo), "csrf": token})
            expect("demo was installed" in body, f"an install with the token goes on ({status})")
            buttons = []
            for page_path in ("/overview/app/demo", "/overview/app/demo?tab=deps"):
                _, page = call(base, "GET", page_path, ADMIN)
                buttons += re.findall(r"<button[^>]*hx-post=\"[^\"]*\"[^>]*>", page)
            expect(buttons != [], f"the inspector has HTMX buttons ({len(buttons)})")
            expect(all(f"hx-vals='{{\"csrf\":\"{token}\"}}'" in b for b in buttons),
                   "every HTMX button outside a form carries the form token")
            status, body = call(base, "POST", "/overview/app/nosuch/start", ADMIN, {"csrf": token})
            expect(not refused(status, body), f"an inspector action with the token is not refused for it ({status})")

            # The programs' API: a session cookie needs the token, a ticket does not.
            status, body = call(base, "POST", "/api/v1/apps/nosuch/start", ADMIN, {"csrf": token})
            expect(status == 404, f"the API with a session and the token goes on ({status})")
            status, location = 0, ""
            query = urllib.parse.urlencode({"audience": "keeper", "return_to": base + "/auth/callback", "next": "/"})
            request = urllib.request.Request(base + "/auth/login?" + query)
            request.add_header("Cookie", f"keeper_session={ADMIN}")
            try:
                with OPENER.open(request, timeout=10) as response:
                    status = response.status
            except urllib.error.HTTPError as answer:
                status, location = answer.code, answer.headers.get("Location", "")
            ticket = urllib.parse.parse_qs(urllib.parse.urlparse(location).query).get("ticket", [""])[0]
            expect(ticket != "", "the keeper signs a ticket for itself")
            if ticket:
                status, body = call(base, "POST", "/api/v1/apps/nosuch/start", "", {},
                                    {"Authorization": "Bearer " + ticket})
                expect(status == 404, f"the API with a ticket and no cookie needs no token ({status})")
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed:")
        for failure in FAILURES:
            print("  -", failure)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
