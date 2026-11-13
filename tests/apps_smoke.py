#!/usr/bin/env python3
"""Smoke test for the keeper's applications registry.

Builds the keeper, starts it against a temporary state directory, and walks the
applications page the way a browser does: discovery from the tree, install of
an application that already lives on the machine, adding it to the left menu,
removing it again, and the refusal to uninstall the keeper itself.

The test uses the orchestrator's applications and does not need a board or a
network beyond the loopback listener. A missing application or registry is a
failed test, because the page's promise is that its lists come from the tree.

Run from anywhere:

    python3 tests/apps_smoke.py
"""

import http.server
import json
import threading
import re
import shutil
import os
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
# The orchestrator the keeper reads: ROBOHUB_ROOT, or beside this checkout.
PROJECTS = KEEPER.parent
ROBOHUB = Path(os.environ.get("ROBOHUB_ROOT", PROJECTS / "robohub")).resolve()
RHO = PROJECTS / "rho" / "bin" / "rho"


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


SESSION = "smoke-session"


def get(base: str, path: str) -> str:
    request = urllib.request.Request(base + path)
    request.add_header("Cookie", f"keeper_session={SESSION}")
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.read().decode("utf-8", "replace")


def post(base: str, path: str, fields: dict) -> str:
    body = urllib.parse.urlencode(fields).encode()
    request = urllib.request.Request(base + path, data=body, method="POST")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    request.add_header("Cookie", f"keeper_session={SESSION}")
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8", "replace")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def sign_in(base: str, audience: str, return_to: str, session: bool) -> tuple:
    """The keeper's answer to an application sending a person to sign in: the
    status, where it redirects, and the page."""
    query = urllib.parse.urlencode({"audience": audience, "return_to": return_to, "next": "/"})
    request = urllib.request.Request(base + "/auth/login?" + query)
    if session:
        request.add_header("Cookie", f"keeper_session={SESSION}")
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(request, timeout=10) as response:
            return response.status, "", response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as answer:
        return answer.code, answer.headers.get("Location", ""), answer.read().decode("utf-8", "replace")


def csrf_token(base: str) -> str:
    """The token the forms module drew the install form with."""
    match = re.search(r'name="csrf" value="([^"]*)"', get(base, "/applications"))
    if not match:
        raise AssertionError("the install form carries no CSRF token")
    return match.group(1)


HELLO_MANIFEST = """module:
  name: hello
  type: rho
  version: 0.1.0
  kind: keeper-hosted
  title: Hello
  command: hello
  port: "9011"
main: src/main.rho
build:
  language: go
  targets:
    - go-server
deploy:
  port: 9011
  files: [notes.txt]
"""

HELLO_MAIN = """module hello

import std.web.http

route GET "/healthz" => hello

fn hello(req: Request) Response {
    return html(status_ok(), "hi")
}
"""


def make_hello(root: Path) -> Path:
    """An application small enough to build in a second."""
    app = root / "hello-app"
    (app / "src").mkdir(parents=True)
    (app / "static").mkdir()
    (app / "module.yml").write_text(HELLO_MANIFEST, encoding="utf-8")
    (app / "src" / "main.rho").write_text(HELLO_MAIN, encoding="utf-8")
    (app / "static" / "a.txt").write_text("a", encoding="utf-8")
    (app / "notes.txt").write_text("n", encoding="utf-8")
    return app


class _Healthy(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == "/healthz" else 404)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        pass


class Stand_in:
    """Answers /healthz on an application's port, for a test whose systemd cannot
    start the application itself: with it, a release answers; without, it does not."""

    def __init__(self, port: int):
        self.server = http.server.HTTPServer(("127.0.0.1", port), _Healthy)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


def post_json(base: str, path: str) -> str:
    request = urllib.request.Request(base + path, data=b"", method="POST")
    request.add_header("Origin", base)
    request.add_header("Cookie", f"keeper_session={SESSION}")
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8", "replace")


def wait_job(base: str, name: str, timeout: float = 60.0) -> dict:
    """Waits for an application's job to end and answers the job."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        app = json.loads(get(base, "/api/v1/apps/" + name))
        if not app["job"]:
            jobs = [j for j in json.loads(get(base, "/api/v1/jobs"))["jobs"] if j["app"] == name]
            if jobs:
                return jobs[0]
        time.sleep(0.5)
    raise AssertionError(f"the job of {name} did not end")


def assert_contains(haystack: str, needles: list, label: str) -> None:
    for needle in needles:
        if needle not in haystack:
            raise AssertionError(f"{label} does not contain {needle!r}")


def build_keeper() -> Path:
    binary = KEEPER / "build" / "keeper"
    rho = str(RHO) if RHO.exists() else "rho"
    result = subprocess.run(
        [rho, "build", "."],
        cwd=KEEPER,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise SystemExit("keeper build failed:\n" + result.stdout + result.stderr)
    if not binary.exists():
        raise SystemExit(f"keeper build wrote no binary at {binary}")
    return binary


def external_app(root: Path) -> Path:
    """A hosted application that lives outside applications/."""
    app = root / "demo-app"
    app.mkdir()
    (app / "module.yml").write_text(
        """module:
  name: demo
  type: rho
  version: 0.1.0
  description: A demo hosted application.
main: src/main.rho
application:
  kind: keeper-hosted
  title: Demo App
  route: /demo
  port: "9009"
  command: demo
""",
        encoding="utf-8",
    )
    return app


def main() -> int:
    binary = build_keeper()
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="keeper-apps-") as state:
        demo = external_app(Path(state))
        env = dict(os.environ)
        # The application finds the toolchain (the documentation generator, the
        # components) by its home; the test gives the application a HOME of its own,
        # so the toolchain's home is named before that happens.
        env.setdefault("RHO_HOME", os.path.join(os.path.expanduser("~"), ".rho"))
        # The workspace is the folder that holds the repositories, Mesh's among
        # them, which the orchestrator's registry names by a path beside it.
        env["ROBOHUB_WORKSPACE"] = str(PROJECTS)
        env["RHO_KEEPER_STATE_DIR"] = os.path.join(state, "state")
        env["HOME"] = state
        env["RHO_HTTP_ADDR"] = f"127.0.0.1:{port}"
        # systemd cannot run this test's applications; a stand-in says yes to
        # restarting and starting them, and passes every other question on.
        fake = Path(state) / "fake-bin"
        fake.mkdir()
        real = shutil.which("systemctl") or "/bin/false"
        (fake / "systemctl").write_text("#!/bin/sh\n"
            "case \" $* \" in *\" restart \"*|*\" start \"*|*\" daemon-reload \"*) exit 0;; esac\n"
            f"exec {real} \"$@\"\n", encoding="utf-8")
        (fake / "systemctl").chmod(0o755)
        env["PATH"] = str(fake) + os.pathsep + env.get("PATH", "")
        # The applications page is behind the keeper's own session. Give the
        # smoke run one valid local session instead of disabling auth.
        state_dir = Path(env["RHO_KEEPER_STATE_DIR"])
        state_dir.mkdir(parents=True, exist_ok=True)
        session_line = f"{SESSION}|{int(time.time()) + 3600}|smoke|*\n"
        (state_dir / "auth-sessions.txt").write_text(session_line, encoding="utf-8")
        # The generated middleware is configured with the home-relative
        # session_file, which a state-dir override does not move.
        home_sessions = Path(env["HOME"]) / ".rho" / "keeper"
        home_sessions.mkdir(parents=True, exist_ok=True)
        (home_sessions / "auth-sessions.txt").write_text(session_line, encoding="utf-8")
        # The keeper's signing key, which it publishes for the applications
        # that trust it.
        keys = Path(env["HOME"]) / ".rho" / "auth"
        keys.mkdir(parents=True, exist_ok=True)
        subprocess.run([str(RHO) if RHO.exists() else "rho", "auth", "keygen", "--dir", str(keys), "--force"],
                       check=True, capture_output=True, text=True)
        process = subprocess.Popen(
            [str(binary)],
            cwd=ROBOHUB,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            wait_for(base)

            # The public key is published to anyone, with no session.
            with urllib.request.urlopen(base + "/auth/public-key", timeout=10) as response:
                published = response.read().decode()
            if "BEGIN PUBLIC KEY" not in published or published != (keys / "public.pem").read_text():
                raise AssertionError("the keeper does not publish its public key")

            # Signing in to an application on a port of its own returns to its
            # callback at the root of that port: Mesh at :8478 is answered at
            # /auth/callback, its route /mesh being only its first page.
            status, _, body = sign_in(base, "mesh", "http://127.0.0.1:8478/auth/callback", False)
            if status != 200 or "not one this keeper signs in to" in body:
                raise AssertionError(f"Mesh's sign-in is refused ({status}): {body[:200]}")
            status, _, body = sign_in(base, "mesh", "http://127.0.0.1:8478/mesh/auth/callback", False)
            if status != 200:
                raise AssertionError(f"Mesh's sign-in behind its route is refused ({status})")
            # Another port, or a callback that is not one, is refused.
            for wrong in ("http://127.0.0.1:9999/auth/callback", "http://127.0.0.1:8478/elsewhere"):
                status, _, _ = sign_in(base, "mesh", wrong, False)
                if status != 400:
                    raise AssertionError(f"a sign-in returning to {wrong} was not refused ({status})")
            # The keeper signs in to itself on the port it was started on, which
            # is not the port its manifest names.
            status, location, body = sign_in(base, "keeper", base + "/auth/callback", True)
            if status not in (302, 303) or not location.startswith(base + "/auth/callback?ticket="):
                raise AssertionError(f"the keeper's own sign-in did not return to it ({status}, {location!r}): {body[:200]}")

            # Nobody has an account yet, so signing in is the first run; and an
            # application can ask whether a keeper session still stands.
            with urllib.request.urlopen(base + "/auth/login", timeout=10) as response:
                first = response.read().decode()
            assert_contains(first, ["Sign in with the access token", "Access token"], "the first-run page")
            with urllib.request.urlopen(base + "/auth/session/" + SESSION, timeout=10) as response:
                if response.status != 200:
                    raise AssertionError("a standing session is not said to stand")
            try:
                urllib.request.urlopen(base + "/auth/session/0123456789abcdef", timeout=10)
                raise AssertionError("an unknown session is said to stand")
            except urllib.error.HTTPError as answer:
                if answer.code != 404:
                    raise AssertionError(f"an unknown session answers {answer.code}")

            page = get(base, "/applications")
            assert_contains(
                page,
                ["Applications", "Install an application"],
                "applications page",
            )
            # Rows are fetched into the table by HTMX, not baked into the page.
            rows = get(base, "/api/applications/rows")
            assert_contains(
                rows,
                ["RoboHub Keeper", "RoboHub Mesh", "keeper-hosted"],
                "application rows",
            )

            # The alert channels are the providers the keeper binds; the plugins
            # are the installed set under plugins/.
            plugins = get(base, "/plugins")
            assert_contains(
                plugins,
                ["Alert channels", "robohub-provider-log", "robohub-provider-email",
                 "robohub-provider-telegram", "Installed plugins", "robohub-auth",
                 "Install a plugin"],
                "plugin registry",
            )
            tested = post(base, "/plugins/test", {"name": "robohub-provider-log"})
            assert_contains(tested, ["handed to robohub-provider-log"], "alert channel test")
            alert_log = Path(state) / ".rho" / "keeper" / "alerts.log"
            if not alert_log.exists() or "Test alert" not in alert_log.read_text():
                raise AssertionError("the local alert channel wrote no alert")
            toggled = post(base, "/plugins/toggle", {"name": "robohub-provider-email", "enabled": "1"})
            assert_contains(toggled, ["enabled for the keeper"], "alert channel toggle")
            bind_conf = Path(state) / ".rho" / "apps" / "keeper" / "bind.conf"
            if "robohub-provider-email.enabled=true" not in bind_conf.read_text():
                raise AssertionError("the alert channel setting was not written to bind.conf")
            toggled = post(base, "/plugins/toggle", {"name": "robohub-auth", "enabled": "0"})
            assert_contains(toggled, ["disabled for the keeper"], "plugin toggle")
            plugin_state = Path(state) / "state" / "plugins.txt"
            if "robohub-auth=0" not in plugin_state.read_text():
                raise AssertionError("the keeper plugin override was not written")

            micro = get(base, "/app-modules")
            assert_contains(
                micro,
                ["Modules", "Inventory", "inventory", "Scheduler", "scheduler", "Widgets", "widgets",
                 "Install a module"],
                "modules registry",
            )

            # The keeper is listed, but it cannot remove itself.
            refusal = post(base, "/applications/uninstall", {"name": "keeper"})
            assert_contains(refusal, ["cannot uninstall itself"], "keeper uninstall")
            assert_contains(get(base, "/applications"), ["RoboHub Keeper"], "keeper still listed")

            # The programs' view of the same catalogue.
            catalogue = json.loads(get(base, "/api/v1/apps"))
            names = {app["name"]: app for app in catalogue["apps"]}
            if "keeper" not in names or "mesh" not in names:
                raise AssertionError(f"the catalogue does not hold the keeper and Mesh: {sorted(names)}")
            if names["keeper"]["state"] != "keeper" or names["keeper"]["port"] != str(port):
                raise AssertionError(f"the keeper's own record is wrong: {names['keeper']}")

            forged = post(base, "/applications/install", {"name": "demo", "source": str(demo)})
            assert_contains(forged, ["not drawn by this keeper"], "an install without the form's token")
            installed = post(
                base,
                "/applications/install",
                {"name": "demo", "source": str(demo), "menu": "1", "csrf": csrf_token(base)},
            )
            assert_contains(installed, ["demo was installed", "being built and started"], "install")
            catalogue_file = Path(state) / "state" / "installed.yml"
            assert_contains(catalogue_file.read_text(), ["demo:", "origin: \"external\""], "catalogue record")
            # Building a folder is a job; demo has no sources, so the job fails and
            # says why, and the row says it is not built.
            failed = wait_job(base, "demo")
            if failed["status"] != "failed" or "build failed" not in failed["reason"]:
                raise AssertionError(f"building demo did not fail as it should: {failed}")
            assert_contains(get(base, "/api/applications/rows"),
                            ["Demo App", "not built"], "installed row")
            home = get(base, "/")
            rail = home[home.index('<nav class="rh-rail">'):home.index("</nav>", home.index('<nav class="rh-rail">'))]
            assert_contains(rail, ["Demo App", "/apps/demo"], "pinned menu entry")
            assert_contains(get(base, "/apps/demo"), ["Demo App", "Dependencies", "Uninstall"], "the application's page")
            assert_contains(home, ["rh-switch", "Demo App", "rh-card"], "the switcher and the overview")
            assert_contains(get(base, "/jobs/strip"), ["demo"], "the strip names the job")

            built = post(base, "/applications/build", {"name": "demo"})
            assert_contains(built, ["demo is being built"], "build")
            if wait_job(base, "demo")["status"] != "failed":
                raise AssertionError("a build of an application with no sources did not fail")

            # The unit is the keeper's, written from the manifest and the catalogue:
            # one written for where the application used to be is written again.
            unit = Path(state) / ".config" / "systemd" / "user" / "demo.service"
            unit.write_text("[Service]\nWorkingDirectory=/nowhere/demo-app\nExecStart=/nowhere/demo-app/build/demo\n",
                            encoding="utf-8")
            restarted = post(base, "/applications/restart", {"name": "demo"})
            assert_contains(restarted, ["demo is being built and started"], "restart of a stale unit")
            # The unit runs the release in use, never the folder's build.
            releases_home = Path(state) / "state" / "apps"
            assert_contains(unit.read_text(), ["Written by the RoboHub keeper",
                                               "WorkingDirectory=" + str(releases_home / "demo" / "current"),
                                               "ExecStart=" + str(releases_home / "demo" / "current" / "demo"),
                                               "EnvironmentFile="], "rewritten unit")
            wait_job(base, "demo")
            redeployed = post(base, "/applications/redeploy", {"name": "demo"})
            assert_contains(redeployed, ["being built and redeployed"], "redeploy")
            if wait_job(base, "demo")["status"] != "failed":
                raise AssertionError("a redeploy of an application with no sources did not fail")
            env_file = Path(state) / "state" / "workspaces" / "demo" / "app.env"
            assert_contains(env_file.read_text(), ["RHO_APP_NAME=demo", "RHO_HTTP_ADDR=127.0.0.1:9009",
                                                   "RHO_APP_SECRET=", "ROBOHUB_KEEPER_URL="], "environment")
            if env_file.stat().st_mode & 0o077:
                raise AssertionError("the environment file is readable by others")

            unpinned = post(base, "/applications/menu", {"name": "demo", "pinned": "0"})
            assert_contains(unpinned, ["no longer in the keeper menu"], "unpin")
            home = get(base, "/")
            rail = home[home.index('<nav class="rh-rail">'):home.index("</nav>", home.index('<nav class="rh-rail">'))]
            assert "Demo App" not in rail, "an application taken out of the menu is still in the rail"

            removed = post(base, "/applications/uninstall", {"name": "demo"})
            assert_contains(removed, ["taken out of the keeper"], "uninstall")
            assert demo.is_dir(), "an external application's folder is left where it is"
            assert not unit.exists(), "the unit of an uninstalled application is removed"
            assert "demo:" not in catalogue_file.read_text(), "an uninstalled application stays in the catalogue"
            assert "Demo App" not in get(base, "/applications")

            # An application that builds: each redeploy makes a release of the
            # build (the program, its manifest, static/ and deploy.files) and puts
            # it in use; a rollback puts the one before back. systemd cannot start
            # the unit in this test's home, so the jobs end failed after that.
            hello = make_hello(Path(state))
            post(base, "/applications/install", {"name": "hello", "source": str(hello), "csrf": csrf_token(base)})
            wait_job(base, "hello", 120)
            current = releases_home / "hello" / "current"
            if not current.is_symlink() or not (current / "hello").exists():
                raise AssertionError("the first start made no release")
            for wanted in ("module.yml", "static/a.txt", "notes.txt"):
                if not (current / wanted).exists():
                    raise AssertionError(f"the release has no {wanted}")
            first = os.readlink(current)

            def redeploy() -> dict:
                time.sleep(1.1)
                post(base, "/applications/redeploy", {"name": "hello"})
                return wait_job(base, "hello", 120)

            # A release that answers stays in use.
            stand_in = Stand_in(9011)
            try:
                redeploy()
                second = os.readlink(current)
                if second == first or not Path(second).is_dir():
                    raise AssertionError(f"a redeploy did not put a new release in use: {first} {second}")
                assert_contains(get(base, "/overview/app/hello"), ["Release", Path(second).name, "Roll back"], "the release in use")
                redeploy()
                third = os.readlink(current)
                # A rollback goes to the release made before the one in use, and a
                # second rollback further back, not to the release the first left.
                rolled = json.loads(post_json(base, "/api/v1/apps/hello/rollback"))
                assert_contains(rolled["message"], ["previous release"], "rollback")
                wait_job(base, "hello", 60)
                if os.readlink(current) != second:
                    raise AssertionError(f"the rollback did not put the release before back: {os.readlink(current)}")
                post_json(base, "/api/v1/apps/hello/rollback")
                wait_job(base, "hello", 60)
                if os.readlink(current) != first:
                    raise AssertionError(f"a second rollback did not go further back: {os.readlink(current)} (third {third})")
            finally:
                stand_in.stop()

            # A release that does not answer is taken back out of use: the one
            # before it is in use again, and the job says so.
            job = redeploy()
            if os.readlink(current) != first:
                raise AssertionError(f"a release that did not answer stayed in use: {os.readlink(current)}")
            if job["status"] != "failed" or "is back in use" not in job["reason"]:
                raise AssertionError(f"the failed redeploy's job: {job}")
            failed = [r for r in (releases_home / "hello" / "releases").iterdir() if (r / ".failed").exists()]
            if len(failed) != 1:
                raise AssertionError(f"the release that did not answer is not marked: {failed}")

            # Three releases are kept, by when they were made.
            stand_in = Stand_in(9011)
            try:
                for _ in range(3):
                    redeploy()
            finally:
                stand_in.stop()
            if len(list((releases_home / "hello" / "releases").iterdir())) != 3:
                raise AssertionError("more than three releases were kept")
            # A job that says it is running but holds no lock (it was killed, or
            # the machine restarted) does not keep the application busy for ever.
            stale = state_dir / "jobs" / f"{int(time.time()) - 120}-hello-redeploy-dead"
            stale.mkdir(parents=True)
            (stale / "meta").write_text(f"hello|redeploy|{int(time.time()) - 120}\n", encoding="utf-8")
            (stale / "status").write_text("running\n", encoding="utf-8")
            app = json.loads(get(base, "/api/v1/apps/hello"))
            if app["job"]:
                raise AssertionError(f"a stale job keeps the application busy: {app['job']}")
            if not (stale / "status").read_text(encoding="utf-8").startswith("failed"):
                raise AssertionError("the stale job was not marked failed")

            post(base, "/applications/uninstall", {"name": "hello"})
            # Its releases go with it: the same name installed again starts afresh.
            if (releases_home / "hello").exists():
                raise AssertionError("uninstalling left the releases behind")
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            if process.returncode not in (0, -15, -9):
                output = process.stdout.read() if process.stdout else ""
                raise SystemExit(f"keeper exited with {process.returncode}:\n{output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
