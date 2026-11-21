#!/usr/bin/env python3
"""Smoke test for the keeper's Developer section.

Builds the keeper and starts it against a scratch HOME, state folder and
workspace: a family of two git repositories (robohub, the root, and gateway)
made from rho-req's own test fixture, so nothing here reads or changes the real
workspace. It walks every page as a maintainer and as a reader, makes changes
through the pages and holds them to what `rho req` itself writes for the same
commands on a copy of the workspace, and commits them: to the day's
requirements/ branch through git plumbing when a repository is on main (its
working copy, index and dirty files untouched), and with `git commit -- <paths>`
when it is on another branch.

`rho req` is the rho-req built from the Rho checkout beside this one (or the
binary $RHO_REQ names), reached through a `rho` on PATH that hands `rho req` to
it and every other command to the real toolchain, so the test does not depend
on what is installed in ~/.rho.

Run from anywhere:

    python3 tests/developer_smoke.py
"""

import http.client
import os
import re
import shutil
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
RHO = PROJECTS / "rho" / "bin" / "rho"
RHO_CMD = str(RHO) if RHO.exists() else (shutil.which("rho") or "rho")
REQ_SOURCE = PROJECTS / "rho" / "modules" / "components" / "rho-req"
FIXTURE = REQ_SOURCE / "src" / "rhoreq" / "testdata" / "workspace"

# Session ids as the keeper makes them: 16 random bytes, as hex.
ADMIN = "a0000000000000000000000000000001"     # a ticket with every scope
DEVON = "d0000000000000000000000000000002"     # a person granted keeper:maintainer
READER = "e0000000000000000000000000000003"    # a person who reads
STRANGER = "f0000000000000000000000000000004"  # a session that is no person's, read only

TODAY = time.strftime("%Y-%m-%d")
FAILURES = []


def expect(condition: bool, what: str) -> None:
    if not condition:
        FAILURES.append(what)
        print("FAIL:", what)


def run(args, cwd=None, env=None, check=True) -> str:
    result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise AssertionError(f"{args} failed: {result.stdout}{result.stderr}")
    return result.stdout


def git(repo: Path, *args, check=True) -> str:
    return run(["git", "-C", str(repo), *args], check=check)


def free_port() -> int:
    import socket
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Client:
    """A browser with one session: GET and POST, no redirect followed."""

    def __init__(self, port: int, session: str):
        self.port = port
        self.session = session

    def request(self, method: str, path: str, fields=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        headers = {}
        if self.session:
            headers["Cookie"] = f"keeper_session={self.session}"
        body = None
        if fields is not None:
            body = urllib.parse.urlencode(fields)
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            headers["Origin"] = f"http://127.0.0.1:{self.port}"
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        text = response.read().decode("utf-8", "replace")
        result = (response.status, response.getheader("Location", ""), text, dict(response.getheaders()))
        connection.close()
        return result

    def get(self, path: str):
        return self.request("GET", path)

    def post(self, path: str, fields: dict):
        return self.request("POST", path, fields)


def csrf(page: str) -> str:
    match = re.search(r'name="csrf" value="([^"]*)"', page)
    if not match:
        raise AssertionError("the page carries no CSRF token")
    return match.group(1)


def form_values(page: str) -> dict:
    """What an edit form shows, as a browser would send it back."""
    import html
    values = {}
    for name, value in re.findall(r'<input name="([a-z_]+)" value="([^"]*)"', page):
        values[name] = html.unescape(value)
    for name, value in re.findall(r'<textarea name="([a-z_]+)"[^>]*>(.*?)</textarea>', page, re.S):
        values[name] = html.unescape(value)
    match = re.search(r'<select name="verification">(.*?)</select>', page, re.S)
    if match:
        selected = re.search(r'<option value="([^"]*)" selected>', match.group(1))
        values["verification"] = selected.group(1) if selected else "test"
    return values


def snapshot(repo: Path) -> dict:
    """Everything about a repository a commit must not touch."""
    return {
        "head": git(repo, "rev-parse", "HEAD"),
        "branch": git(repo, "symbolic-ref", "-q", "--short", "HEAD", check=False),
        "status": git(repo, "status", "--porcelain=v1", "--untracked-files=all"),
        "cached": git(repo, "diff", "--cached"),
        "worktree": git(repo, "diff"),
        "index": git(repo, "ls-files", "-s"),
    }


def tree_files(root: Path) -> dict:
    out = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and ".git" not in path.parts:
            out[str(path.relative_to(root))] = path.read_bytes()
    return out


def build_keeper() -> Path:
    result = subprocess.run([RHO_CMD, "build", "."], cwd=KEEPER, text=True, capture_output=True)
    if result.returncode != 0:
        raise SystemExit("keeper build failed:\n" + result.stdout + result.stderr)
    binary = KEEPER / "build" / "keeper"
    if not binary.exists():
        raise SystemExit(f"keeper build wrote no binary at {binary}")
    return binary


def rho_req_binary(scratch: Path) -> Path:
    named = os.environ.get("RHO_REQ")
    if named:
        return Path(named)
    if not (REQ_SOURCE / "src" / "main.go").exists():
        raise SystemExit(f"no rho-req source at {REQ_SOURCE}; set RHO_REQ to a rho-req 0.3.0 binary")
    binary = scratch / "bin" / "rho-req"
    run(["go", "build", "-o", str(binary), "./src"], cwd=REQ_SOURCE)
    return binary


def make_workspace(ws: Path) -> None:
    """The fixture family as git repositories: robohub (the root) and gateway."""
    for name in ("robohub", "gateway", "standalone"):
        shutil.copytree(FIXTURE / name, ws / name)
    reports = ws / "gateway" / "build" / "test-reports"
    reports.mkdir(parents=True)
    for report in (ws / "gateway" / "test-reports.fixture").iterdir():
        shutil.copy(report, reports / report.name)
    # What the keeper needs to find the orchestrator; git keeps no empty folder.
    (ws / "robohub" / "registry" / "modules").mkdir(parents=True)
    identities = {"robohub": ("Ada Maintainer", "ada@example.org"), "gateway": ("Eve Outsider", "eve@example.org")}
    for name, (who, email) in identities.items():
        repo = ws / name
        (repo / ".gitignore").write_text("build/\n", encoding="utf-8")
        git(repo, "init", "-q", "-b", "main")
        git(repo, "config", "user.name", who)
        git(repo, "config", "user.email", email)
        git(repo, "config", "commit.gpgsign", "false")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "fixture")


def write_sessions(home: Path, state: Path) -> None:
    expiry = int(time.time()) + 3600
    # The scopes are what the keeper's sign-in records for each (people_keeper_scopes).
    lines = (f"{ADMIN}|{expiry}|smoke|*\n{DEVON}|{expiry}|devon|keeper:read,keeper:maintainer\n"
             f"{READER}|{expiry}|rita|keeper:operate\n{STRANGER}|{expiry}|stranger|keeper:read\n")
    for folder in (state, home / ".rho" / "keeper"):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "auth-sessions.txt").write_text(lines, encoding="utf-8")


def add_person(store: Path, scratch: Path, name: str, role: str, grants: str) -> None:
    password = scratch / f"pw-{name}"
    password.write_text("a long enough password\n", encoding="utf-8")
    args = [RHO_CMD, "auth", "user", "add", "--name", name, "--role", role, "--store", str(store), "--password-file", str(password)]
    if grants:
        args += ["--grants", grants]
    run(args)
    password.unlink()


def main() -> int:
    binary = build_keeper()
    subprocess.run(["git", "checkout", "-q", "--", "rho.lock"], cwd=KEEPER, check=False)
    port = free_port()
    with tempfile.TemporaryDirectory(prefix="keeper-developer-") as scratch_name:
        scratch = Path(scratch_name)
        req_bin = rho_req_binary(scratch)
        ws = scratch / "ws"
        make_workspace(ws)
        expected = scratch / "expected"
        shutil.copytree(ws, expected, symlinks=True)
        gateway, robohub = ws / "gateway", ws / "robohub"

        # A `rho` that hands `rho req` to the rho-req under test and everything
        # else to the toolchain; `rho req` is missing while the marker exists.
        fake = scratch / "fake-bin"
        fake.mkdir()
        missing = scratch / "no-rho-req"
        (fake / "rho").write_text(
            "#!/bin/sh\n"
            f"if [ \"$1\" = req ]; then\n  if [ -e '{missing}' ]; then echo \"rho: unknown command req\" >&2; exit 2; fi\n"
            f"  shift; exec '{req_bin}' \"$@\"\nfi\n"
            f"exec '{RHO_CMD}' \"$@\"\n", encoding="utf-8")
        (fake / "rho").chmod(0o755)

        def expect_req(*args, repo: Path = expected / "robohub"):
            """The same command, run by hand on the copy of the workspace."""
            env = dict(os.environ, ROBOHUB_WORKSPACE=str(expected))
            # As for the keeper below: a RHO_WORKSPACE left in the environment (CI
            # sets it to the real workspace) adds that workspace's repositories to
            # the fixture's family, and rho req numbers from their ids instead.
            env.pop("RHO_WORKSPACE", None)
            return run([str(req_bin), *args, "--dir", str(repo)], env=env)

        home = scratch / "home"
        state = home / "state"
        write_sessions(home, state)
        # The first person of a store is its admin, whichever it is.
        add_person(state / "users.yml", scratch, "owner", "admin", "")
        add_person(state / "users.yml", scratch, "devon", "viewer", "keeper:maintainer")
        add_person(state / "users.yml", scratch, "rita", "operator", "mesh:*")
        keys = home / ".rho" / "auth"
        keys.mkdir(parents=True, exist_ok=True)
        run([RHO_CMD, "auth", "keygen", "--dir", str(keys), "--force"])
        cwd = scratch / "run"
        cwd.mkdir()

        env = dict(os.environ)
        env.setdefault("RHO_HOME", os.path.join(os.path.expanduser("~"), ".rho"))
        env["HOME"] = str(home)
        env["RHO_KEEPER_STATE_DIR"] = str(state)
        env["ROBOHUB_WORKSPACE"] = str(ws)
        env.pop("ROBOHUB_ROOT", None)
        env.pop("RHO_WORKSPACE", None)
        env["RHO_HTTP_ADDR"] = f"127.0.0.1:{port}"
        env["PATH"] = str(fake) + os.pathsep + env.get("PATH", "")
        process = subprocess.Popen([str(binary)], cwd=cwd, env=env, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True)
        try:
            deadline = time.time() + 30
            while True:
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1):
                        break
                except (urllib.error.URLError, ConnectionError):
                    if time.time() > deadline:
                        raise SystemExit("the keeper did not start")
                    time.sleep(0.2)

            admin, devon, reader, stranger = (Client(port, s) for s in (ADMIN, DEVON, READER, STRANGER))
            nobody = Client(port, "")

            # --- Reading ---------------------------------------------------------
            status, location, _, _ = nobody.get("/developer/requirements")
            expect(status in (302, 303) and "/auth/login" in location, f"a stranger is sent to sign in ({status} {location})")
            status, _, page, _ = reader.get("/")
            expect('href="/developer"' in page, "the rail has a Developer entry")

            status, _, page, _ = reader.get("/developer/requirements")
            ids = re.findall(r'class="dev-req" data-id="([^"]+)"', page)
            expect(status == 200 and set(ids) == {"SYS-0001", "SYS-0002", "SYS-0003", "GW-0001", "GW-0002", "GW-0003", "GW-AUTH-0001"},
                   f"the list is the whole family's requirements: {ids}")
            expect('href="/developer/new"' not in page, "a reader is offered no new requirement")
            _, _, page, _ = reader.get("/developer/requirements?repo=gateway")
            ids = re.findall(r'class="dev-req" data-id="([^"]+)"', page)
            expect(set(ids) == {"GW-0001", "GW-0002", "GW-0003", "GW-AUTH-0001"}, f"filtered by repository: {ids}")
            _, _, page, _ = reader.get("/developer/requirements?status=draft")
            expect(re.findall(r'class="dev-req" data-id="([^"]+)"', page) == ["SYS-0003"], "filtered by status")
            _, _, page, _ = reader.get("/developer/requirements?level=SYS&tag=security")
            expect(re.findall(r'class="dev-req" data-id="([^"]+)"', page) == ["SYS-0002"], "filtered by level and tag")
            _, _, page, _ = reader.get("/developer/requirements?q=POWER")
            expect(re.findall(r'class="dev-req" data-id="([^"]+)"', page) == ["SYS-0001"], "filtered by text, any case")

            status, _, page, _ = reader.get("/developer/requirements/GW-0001")
            expect(status == 200 and "re-establish a session with every enrolled board" in page, "a requirement's statement")
            expect('href="/developer/requirements/SYS-0001"' in page, "what it satisfies is a link")
            expect('href="/developer/adr/gateway/ADR-0001"' in page and 'href="/developer/adr/robohub/ADR-0001"' in page,
                   "its decisions are links, across repositories")
            expect("A power cut must not need a person." in page, "its rationale")
            expect("tests/session_test.rho" in page and '<span class="rh-tag ok">pass</span>' in page, "its tests with their results")
            expect("src/session.rho" in page, "its code")
            expect("dev-maintain" not in page and "/edit" not in page, "a reader sees no edit controls")
            status, _, page, _ = reader.get("/developer/requirements/SYS-0001")
            expect('href="/developer/requirements/GW-0001"' in page, "what satisfies it is a link")
            for bad in ("gw-0001", "GW-9999", "..%2F..%2Fetc", "--force"):
                status, _, _, _ = reader.get("/developer/requirements/" + bad)
                expect(status == 404, f"/developer/requirements/{bad} is not found ({status})")

            status, _, page, _ = reader.get("/developer/trace")
            expect(status == 200 and 'id="dev-release"' in page and "Not releasable" in page, "the release gate says no")
            expect('data-id="GW-0001"' in page and "tag.unresolved" not in page, "the matrix has its rows")
            expect("dangling-tag" in page and "GW-0099" in page, "and its gaps")

            status, _, page, _ = reader.get("/developer/check")
            expect(status == 200 and "gateway/tests/session_test.rho:11" in page and "tag.unresolved" in page,
                   "the check's error with file:line")
            expect("gateway/docs/requirements/node.yml:27" in page, "and its warnings")

            status, _, page, _ = reader.get("/developer/export")
            expect(status == 200 and "Requirements" in page and "Survive a power cut" in page, "the export, rendered")
            expect("&lt;a id=" not in page, "the export shows no raw anchor")
            status, _, text, headers = reader.get("/developer/export/requirements.md")
            expect(status == 200 and text.startswith("# Requirements") and "attachment" in headers.get("Content-Disposition", ""),
                   "the export, for download")

            status, _, page, _ = reader.get("/developer/adr")
            expect(status == 200 and 'href="/developer/adr/gateway/ADR-0002"' in page and "Nodes talk over a mesh bus" in page,
                   "the decisions of every repository")
            expect("dev-new-adr" not in page, "a reader is offered no new decision")
            status, _, page, _ = reader.get("/developer/adr/gateway/ADR-0001")
            expect(status == 200 and "Context" in page and "superseded_by:" not in page, "a decision, rendered without its front matter")
            expect("dev-maintain" not in page, "a reader cannot change a decision")
            for bad in ("standalone/ADR-0001", "gateway/ADR-0009", "gateway/ADR-1", "..%2Fx/ADR-0001"):
                status, _, _, _ = reader.get("/developer/adr/" + bad)
                expect(status == 404, f"/developer/adr/{bad} is not found ({status})")

            # --- A reader changes nothing -----------------------------------------
            token = csrf(reader.get("/applications")[2])
            before = tree_files(ws)
            for path, fields in (
                ("/developer/new", {"repo": "gateway", "level": "NODE", "title": "x", "statement": "y", "verification": "test", "status": "draft"}),
                ("/developer/requirements/GW-0001/edit", {"title": "x"}),
                ("/developer/requirements/GW-0001/status", {"status": "proposed"}),
                ("/developer/adr/new", {"repo": "gateway", "title": "x"}),
                ("/developer/adr/gateway/ADR-0002/status", {"status": "accepted"}),
                ("/developer/adr/gateway/ADR-0002/supersede", {"by": "ADR-0001"}),
                ("/developer/commit", {"repo": "gateway", "confirm": "yes", "changes": ""}),
            ):
                # An operator's session may post; the section itself refuses.
                status, _, page, _ = reader.post(path, dict(fields, csrf=token))
                expect(status == 403 and "Only a maintainer" in page, f"a non-maintainer is refused POST {path} ({status})")
                # A read-only session is refused before the section is reached.
                status, _, _, _ = stranger.post(path, dict(fields, csrf=token))
                expect(status == 403, f"a read-only session is refused POST {path} ({status})")
            for path in ("/developer/new", "/developer/requirements/GW-0001/edit"):
                status, _, _, _ = reader.get(path)
                expect(status == 403, f"a reader is refused GET {path} ({status})")
            expect(tree_files(ws) == before, "nothing a reader sent changed a file")
            status, _, page, _ = reader.get("/developer/commit")
            expect(status == 200 and "dev-commit-form" not in page, "a reader sees no commit button")

            # --- A maintainer changes things, exactly as rho req does -------------
            status, _, page, _ = devon.get("/developer/requirements")
            expect('href="/developer/new"' in page, "a maintainer is offered a new requirement")
            token = csrf(devon.get("/developer/new")[2])
            status, _, _, _ = devon.post("/developer/new", {"repo": "gateway", "level": "NODE", "title": "x", "statement": "y",
                                                              "verification": "test", "status": "draft"})
            expect(status == 403, "a change without the form's token is refused")
            status, _, page, _ = devon.post("/developer/new", {"csrf": token, "repo": "../gateway", "level": "NODE", "title": "x",
                                                                 "statement": "y", "verification": "test", "status": "draft"})
            expect(status == 200 and "not a repository of this workspace" in page, "a repository outside the family is refused")
            status, _, page, _ = devon.post("/developer/new", {"csrf": token, "repo": "standalone", "level": "UNIT", "title": "x",
                                                                 "statement": "y", "verification": "test", "status": "draft"})
            expect("not a repository of this workspace" in page, "a repository of another family is refused")
            status, _, page, _ = devon.post("/developer/new", {"csrf": token, "repo": "gateway", "level": "NODE", "title": "x",
                                                                 "statement": "y", "verification": "test", "status": "draft",
                                                                 "satisfies": "SYS-0001,--force"})
            expect("not one rho req takes" in page, "an option smuggled into a list is refused")
            expect(tree_files(ws) == before, "a refused form changed nothing")
            # The tool's own refusal is shown on the form.
            status, _, page, _ = devon.post("/developer/new", {"csrf": token, "repo": "gateway", "level": "NODE", "title": "Bad link",
                                                                 "statement": "y", "verification": "test", "status": "draft",
                                                                 "satisfies": "GW-0002"})
            expect('id="dev-error"' in page and "rho req" in page and "Bad link" in page, "the tool's error is shown inline, with what was typed")
            expect(tree_files(ws) == before, "a refused requirement wrote nothing")

            status, location, _, _ = devon.post("/developer/new", {
                "csrf": token, "repo": "gateway", "level": "NODE", "title": "Report the firmware version",
                "statement": "The gateway shall report\nthe firmware version of every board.", "rationale": "Support asks.",
                "satisfies": "SYS-0001", "owner": "ada", "tags": "support, ops", "verification": "test", "status": "draft"})
            expect(status in (302, 303) and location.startswith("/developer/requirements/GW-0004"), f"a new requirement ({status} {location})")
            expect_req("new", "--level=NODE", "--title=Report the firmware version",
                       "--statement=The gateway shall report the firmware version of every board.", "--verification=test",
                       "--status=draft", "--rationale=Support asks.", "--satisfies=SYS-0001", "--owner=ada", "--tags=support,ops",
                       repo=expected / "gateway")
            node = "docs/requirements/node.yml"
            expect((gateway / node).read_text() == (expected / "gateway" / node).read_text(), "the new requirement is what rho req writes")
            expect((gateway / node).read_text().startswith("# Gateway requirements.\n"), "the file's comment is kept")
            status, _, page, _ = devon.get(location)
            expect("Created, as rho req wrote it." in page and "dev-maintain" in page, "the new requirement's page, with edit controls")

            # An edit: only what changed is sent, and a statement change reopens it.
            status, _, page, _ = devon.get("/developer/requirements/GW-0001/edit")
            values = form_values(page)
            expect(values.get("title") == "Sessions survive a gateway restart" and values.get("owner") == "maintainer",
                   f"the edit form shows the requirement: {values}")
            values.update({"csrf": csrf(page), "owner": "", "tags": "security, power",
                           "statement": "After a restart the gateway shall re-establish a session with every enrolled board within 20 s, without re-enrollment."})
            status, location, _, _ = devon.post("/developer/requirements/GW-0001/edit", values)
            expect(status in (302, 303) and location.endswith("done=reopened"), f"the edit reopens an approved requirement ({location})")
            expect_req("edit", "GW-0001", "--set",
                       "statement=After a restart the gateway shall re-establish a session with every enrolled board within 20 s, without re-enrollment.",
                       "--remove", "owner", "--set", "tags=security,power")
            expect((gateway / node).read_text() == (expected / "gateway" / node).read_text(), "the edit is what rho req writes")
            _, _, page, _ = devon.get("/developer/requirements/GW-0001")
            expect('<span class="rh-tag">proposed</span>' in page, "and the requirement is proposed again")
            status, location, _, _ = devon.post("/developer/requirements/GW-0001/edit", dict(form_values(devon.get("/developer/requirements/GW-0001/edit")[2]), csrf=token))
            expect(location.endswith("done=unchanged"), "an edit that changes nothing writes nothing")

            # Statuses: allowed, refused by the lifecycle, and an approval's warning.
            status, _, page, _ = devon.post("/developer/requirements/GW-0004/status", {"csrf": token, "status": "verified"})
            expect('id="dev-error"' in page and "verified" in page, "a status the lifecycle refuses shows the tool's error")
            expect((gateway / node).read_text() == (expected / "gateway" / node).read_text(), "and writes nothing")
            status, _, page, _ = devon.post("/developer/requirements/GW-0004/status", {"csrf": token, "status": "proposed"})
            expect('id="dev-done"' in page and "dev-identity" not in page, "draft -> proposed")
            status, _, page, _ = devon.post("/developer/requirements/GW-0004/status", {"csrf": token, "status": "approved"})
            expect("GW-0004 is now approved." in page and "dev-identity" in page and "Eve Outsider" in page,
                   "an approval warns that the committing identity is not a maintainer")
            expect_req("set-status", "GW-0004", "proposed")
            expect_req("set-status", "GW-0004", "approved")
            expect((gateway / node).read_text() == (expected / "gateway" / node).read_text(), "the statuses are what rho req writes")
            status, _, _, _ = devon.post("/developer/requirements/GW-0004/status", {"csrf": token, "status": "--force"})
            expect((gateway / node).read_text() == (expected / "gateway" / node).read_text(), "a status that is an option writes nothing")

            # Decisions: a new one, accepted, superseding another.
            status, _, page, _ = devon.get("/developer/adr")
            expect("dev-new-adr" in page, "a maintainer is offered a new decision")
            status, location, _, _ = devon.post("/developer/adr/new", {"csrf": token, "repo": "gateway", "title": "Keep sessions in a table",
                                                                        "requirements": "GW-0004, GW-0001"})
            expect(status in (302, 303) and location.startswith("/developer/adr/gateway/ADR-0003"), f"a new decision ({location})")
            expect_req("adr", "new", "--title=Keep sessions in a table", "--requirements=GW-0004,GW-0001", repo=expected / "gateway")
            adr = "docs/architecture/adr/0003-keep-sessions-in-a-table.md"
            expect((gateway / adr).read_text() == (expected / "gateway" / adr).read_text(), "the decision is what rho req writes")
            status, _, page, _ = devon.post("/developer/adr/gateway/ADR-0003/status", {"csrf": token, "status": "accepted"})
            expect("gateway:ADR-0003 is now accepted." in page and "dev-identity" in page, "a decision accepted, with the warning")
            status, _, page, _ = devon.post("/developer/adr/gateway/ADR-0002/supersede", {"csrf": token, "by": "ADR-0003"})
            expect("superseded by ADR-0003" in page, "a decision superseded")
            status, _, page, _ = devon.post("/developer/adr/gateway/ADR-0003/status", {"csrf": token, "status": "superseded"})
            expect("not one rho req takes" in page, "superseded is supersede's, not a status to set")
            expect_req("adr", "set-status", "ADR-0003", "accepted", repo=expected / "gateway")
            expect_req("adr", "supersede", "ADR-0002", "ADR-0003", repo=expected / "gateway")
            for path in (adr, "docs/architecture/adr/0002-keep-a-session-table.md"):
                expect((gateway / path).read_text() == (expected / "gateway" / path).read_text(), f"{path} is what rho req writes")

            # A requirement in the root, which is on a feature branch with work of its own staged.
            git(robohub, "checkout", "-q", "-b", "feature/power")
            (robohub / "docs" / "doc" / "index.md").write_text("staged, unrelated\n", encoding="utf-8")
            git(robohub, "add", "docs/doc/index.md")
            (robohub / "notes.txt").write_text("untracked, unrelated\n", encoding="utf-8")
            status, location, _, _ = admin.post("/developer/new", {"csrf": token, "repo": "robohub", "level": "SYS",
                                                                   "title": "Know the firmware", "statement": "The system shall know every board's firmware.",
                                                                   "verification": "inspection", "status": "proposed"})
            expect(location.startswith("/developer/requirements/SYS-0004"), f"an admin is a maintainer too ({location})")

            # --- Commit -------------------------------------------------------------
            (gateway / "src" / "session.rho").write_text((gateway / "src" / "session.rho").read_text() + "// dirty, unrelated\n")
            (gateway / "tests" / "smoke.py").write_text((gateway / "tests" / "smoke.py").read_text() + "# staged, unrelated\n")
            git(gateway, "add", "tests/smoke.py")
            (gateway / "scratch.txt").write_text("untracked, unrelated\n", encoding="utf-8")
            gateway_before = snapshot(gateway)
            gateway_files = tree_files(gateway)

            status, _, page, _ = devon.get("/developer/commit")
            section = page.split('data-repo="gateway"')[1].split("</section>")[0]
            expect(node in section and adr in section and "0002-keep-a-session-table.md" in section, "the commit page lists the changed files")
            expect("src/session.rho" not in section and "scratch.txt" not in section and "smoke.py" not in section,
                   "and nothing outside docs/requirements and docs/architecture")
            expect(f"requirements/{TODAY}" in section and "working copy will not change" in section, "on main it goes to the day's branch")
            expect("dev-identity" in section, "with the identity warning")
            changes = re.search(r'name="changes" value="([^"]*)"', section).group(1)

            status, _, page, _ = devon.post("/developer/commit", {"csrf": token, "repo": "gateway", "changes": changes})
            expect("Tick the box" in page, "a commit needs the confirmation")
            status, _, page, _ = devon.post("/developer/commit", {"csrf": token, "repo": "gateway", "confirm": "yes", "changes": changes + "x"})
            expect("no longer the ones shown" in page, "a commit of other changes than those shown is refused")
            status, _, page, _ = devon.post("/developer/commit", {"csrf": token, "repo": "..", "confirm": "yes", "changes": changes})
            expect("not a repository of this workspace" in page, "a commit names a family repository")
            expect(git(gateway, "branch", "--list", "requirements/*") == "", "no branch yet")

            status, _, page, _ = devon.post("/developer/commit", {"csrf": token, "repo": "gateway", "confirm": "yes", "changes": changes})
            branch = f"requirements/{TODAY}"
            done = re.search(r'id="dev-done">([^<]*)<', page)
            expect(done is not None and f"committed" in done.group(1) and branch in done.group(1) and
                   "the working copy is unchanged; push or merge it yourself" in done.group(1), f"the commit says where it went: {done and done.group(1)}")
            expect(snapshot(gateway) == gateway_before, "HEAD, branch, index, staged and unstaged changes are as they were")
            expect(tree_files(gateway) == gateway_files, "every file in the working copy is as it was")
            tip = git(gateway, "rev-parse", branch).strip()
            expect(git(gateway, "rev-parse", f"{branch}^").strip() == gateway_before["head"].strip(), "the branch is HEAD plus one commit")
            changed = git(gateway, "diff-tree", "-r", "--name-only", "--no-commit-id", tip).split()
            expect(sorted(changed) == sorted([node, adr, "docs/architecture/adr/0002-keep-a-session-table.md"]),
                   f"the commit carries only those files: {changed}")
            expect(git(gateway, "show", f"{branch}:{node}") == (gateway / node).read_text(), "with their working-copy content")
            message = git(gateway, "log", "-1", "--format=%an <%ae>%n%B", branch)
            expect(message.startswith("Eve Outsider <eve@example.org>\nrequirements: GW-0004, GW-0001, ADR-0002, ADR-0003"),
                   f"the author is the repository's identity and the subject names the ids: {message!r}")
            expect(git(gateway, "remote") == "", "nothing to push to, and nothing pushed")

            _, _, page, _ = devon.get("/developer/commit")
            section = page.split('data-repo="gateway"')[1].split("</section>")[0]
            expect("Nothing to commit." in section, "what is on the branch is not offered again")

            # A later change advances the same branch.
            status, _, page, _ = devon.post("/developer/requirements/GW-0004/status", {"csrf": token, "status": "implemented"})
            expect("GW-0004 is now implemented." in page, "a later change")
            _, _, page, _ = devon.get("/developer/commit")
            section = page.split('data-repo="gateway"')[1].split("</section>")[0]
            changes = re.search(r'name="changes" value="([^"]*)"', section).group(1)
            expect(changes == f"M|{node};", f"only the new change is offered: {changes}")
            status, _, page, _ = devon.post("/developer/commit", {"csrf": token, "repo": "gateway", "confirm": "yes", "changes": changes})
            expect(git(gateway, "rev-parse", f"{branch}^").strip() == tip, "the day's branch advances")
            expect(git(gateway, "log", "-1", "--format=%s", branch).strip() == "requirements: GW-0004", "named by the change")
            expect(git(gateway, "rev-parse", "HEAD") == gateway_before["head"], "HEAD stays where it was")

            # A day's branch that no longer contains HEAD is left alone.
            moved_tip = git(gateway, "rev-parse", branch).strip()
            git(gateway, "commit", "-q", "-m", "work on main")
            _, _, page, _ = devon.get("/developer/commit")
            section = page.split('data-repo="gateway"')[1].split("</section>")[0]
            expect(f"requirements/{TODAY}-2" in section, "a branch that moved away is not advanced")
            changes = re.search(r'name="changes" value="([^"]*)"', section).group(1)
            devon.post("/developer/commit", {"csrf": token, "repo": "gateway", "confirm": "yes", "changes": changes})
            expect(git(gateway, "rev-parse", branch).strip() == moved_tip, "the old branch is untouched")
            expect(git(gateway, "rev-parse", f"requirements/{TODAY}-2^").strip() == git(gateway, "rev-parse", "HEAD").strip(),
                   "the next one starts at HEAD")

            # On another branch: an ordinary commit of the listed paths only.
            robohub_staged = git(robohub, "diff", "--cached", "--name-only")
            _, _, page, _ = devon.get("/developer/commit")
            section = page.split('data-repo="robohub"')[1].split("</section>")[0]
            expect("feature/power" in section and "docs/requirements/system.yml" in section, "the root commits on its own branch")
            changes = re.search(r'name="changes" value="([^"]*)"', section).group(1)
            head_before = git(robohub, "rev-parse", "HEAD").strip()
            status, _, page, _ = devon.post("/developer/commit", {"csrf": token, "repo": "robohub", "confirm": "yes", "changes": changes})
            expect("committed" in page and "feature/power" in page, "committed on the branch it is on")
            expect(git(robohub, "rev-parse", "HEAD^").strip() == head_before, "one commit on feature/power")
            expect(git(robohub, "diff-tree", "-r", "--name-only", "--no-commit-id", "HEAD").split() == ["docs/requirements/system.yml"],
                   "carrying only the requirements file")
            expect(git(robohub, "diff", "--cached", "--name-only") == robohub_staged, "what was staged stays staged")
            expect((robohub / "notes.txt").exists() and git(robohub, "rev-parse", "main").strip() != git(robohub, "rev-parse", "HEAD").strip(),
                   "the untracked file stays and main does not move")
            expect(git(robohub, "log", "-1", "--format=%an %s", "HEAD").strip() == "Ada Maintainer requirements: SYS-0004", "named and authored")

            status, _, _, _ = reader.post("/developer/commit", {"csrf": token, "repo": "robohub", "confirm": "yes", "changes": changes})
            expect(status == 403, "a reader cannot commit")

            leftovers = [p.name for p in (state / "developer").iterdir() if p.suffix == ".tmp" or ".tmp." in p.name]
            expect(leftovers == [], f"no scratch file is left behind: {leftovers}")
            expect(not (gateway / ".git" / "index.lock").exists(), "no index lock is left behind")

            # --- Without rho req ------------------------------------------------------
            missing.write_text("", encoding="utf-8")
            status, _, page, _ = reader.get("/developer/requirements")
            expect(status == 200 and "rho module install rho-req" in page, "without rho req the section says how to install it")
            missing.unlink()
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            if FAILURES:
                output = process.stdout.read() if process.stdout else ""
                print(output[-4000:])
    if FAILURES:
        print(f"keeper developer smoke: {len(FAILURES)} failed")
        return 1
    print("keeper developer smoke ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
