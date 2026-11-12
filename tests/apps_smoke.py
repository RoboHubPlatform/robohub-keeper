#!/usr/bin/env python3
"""Smoke test for the keeper's applications registry.

Builds the keeper, starts it against a temporary state directory, and walks the
applications page the way a browser does: discovery from the tree, install of
an application that already lives on the machine, adding it to the left menu,
removing it again, and the refusal to uninstall the keeper itself.

The test uses the repository's own applications and does not need a board or a
network beyond the loopback listener. A missing application or registry is a
failed test, because the page's promise is that its lists come from the tree.

Run from anywhere:

    python3 applications/keeper/tests/apps_smoke.py
"""

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
ROBOHUB = KEEPER.parents[1]
PROJECTS = ROBOHUB.parent
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
        env["RHO_HTTP_ADDR"] = f":{port}"
        # The applications page is behind the keeper's own session. Give the
        # smoke run one valid local session instead of disabling auth.
        state_dir = Path(env["RHO_KEEPER_STATE_DIR"])
        state_dir.mkdir(parents=True, exist_ok=True)
        session_line = f"{SESSION}|{int(time.time()) + 3600}|smoke\n"
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

            installed = post(
                base,
                "/applications/install",
                {"name": "demo", "source": str(demo), "menu": "1"},
            )
            assert_contains(installed, ["demo was installed"], "install")
            assert_contains(get(base, "/api/applications/rows"),
                            ["Demo App", "not built"], "installed row")
            assert_contains(get(base, "/"), ["Demo App", "app-open"], "pinned menu entry")

            # Build builds and nothing else: demo has no sources, so it says the
            # build failed rather than that it was built.
            built = post(base, "/applications/build", {"name": "demo"})
            assert_contains(built, ["build failed"], "build of an application with no sources")
            # A service unit written for where the application used to be is
            # written again on a restart, which builds it from where it is now.
            units = Path(state) / ".config" / "systemd" / "user"
            units.mkdir(parents=True, exist_ok=True)
            (units / "demo.service").write_text(
                "[Service]\nWorkingDirectory=/nowhere/demo-app\n"
                "Environment=ROBOHUB_APP_MANIFEST=/nowhere/demo-app/module.yml\n"
                "Environment=RHO_HTTP_ADDR=:9009\nExecStart=/nowhere/demo-app/build/demo\n",
                encoding="utf-8")
            restarted = post(base, "/applications/restart", {"name": "demo"})
            assert_contains(restarted, ["Could not deploy demo again", "the build failed"],
                            "restart of an application whose unit is out of date")
            redeployed = post(base, "/applications/redeploy", {"name": "demo"})
            assert_contains(redeployed, ["the build failed"], "redeploy")
            (units / "demo.service").unlink()

            unpinned = post(base, "/applications/menu", {"name": "demo", "pinned": "0"})
            assert_contains(unpinned, ["no longer in the keeper menu"], "unpin")
            assert "Demo App" not in get(base, "/")

            removed = post(base, "/applications/uninstall", {"name": "demo"})
            assert_contains(removed, ["removed from the registry"], "uninstall")
            assert demo.is_dir(), "an external application's folder is left where it is"
            assert "Demo App" not in get(base, "/applications")
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
