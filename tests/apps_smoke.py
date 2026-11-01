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


def get(base: str, path: str) -> str:
    with urllib.request.urlopen(base + path, timeout=10) as response:
        return response.read().decode("utf-8", "replace")


def post(base: str, path: str, fields: dict) -> str:
    body = urllib.parse.urlencode(fields).encode()
    request = urllib.request.Request(base + path, data=body, method="POST")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8", "replace")


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
        env["ROBOHUB_WORKSPACE"] = str(ROBOHUB)
        env["RHO_KEEPER_STATE_DIR"] = os.path.join(state, "state")
        env["RHO_HTTP_ADDR"] = f":{port}"
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

            page = get(base, "/applications")
            assert_contains(
                page,
                [
                    "Applications",
                    "RoboHub Keeper",
                    "RoboHub Mesh",
                    "keeper-hosted",
                    "Install an application",
                ],
                "applications page",
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
            assert_contains(get(base, "/applications"), ["Demo App", "not built"], "installed row")
            assert_contains(get(base, "/"), ["Demo App", "app-open"], "pinned menu entry")

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
