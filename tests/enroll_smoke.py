#!/usr/bin/env python3
"""Smoke test for node enrollment and verification.

Builds the keeper, starts it against a temporary state directory on the
loopback, and checks the enrollment rules over HTTP: a token names its device
and expiry, the placement is the token's and not the request's, an enrolled
device is not replaced without a re-enroll token, a token is spent once even
when it is presented many times at once, credentials are stored as salted
hashes (and plaintext ones from an older keeper are migrated), and the two
unauthenticated endpoints have a request budget per client.

    python3 tests/enroll_smoke.py
"""

import concurrent.futures
import json
import os
import socket
import stat
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
RHO_CMD = str(RHO) if RHO.exists() else "rho"

LEGACY_CREDENTIAL = "ab" * 32


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


def post(base: str, path: str, fields: dict, client: str) -> tuple:
    data = urllib.parse.urlencode(fields).encode()
    request = urllib.request.Request(base + path, data=data, method="POST")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    # Each step is counted as its own client, so the budget test is the only
    # one that spends a budget.
    request.add_header("X-Forwarded-For", client)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as answer:
        body = answer.read().decode()
        try:
            return answer.code, json.loads(body)
        except ValueError:
            return answer.code, {"raw": body}


def enroll(base: str, token: str, device: str, client: str, **placement) -> tuple:
    fields = {"token": token, "device_id": device, "public_key": "cHVibGlj"}
    fields.update(placement)
    return post(base, "/api/enroll", fields, client)


def expect(condition: bool, what: str) -> None:
    if not condition:
        raise AssertionError(what)
    print(f"[PASS] {what}")


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
    future = int(time.time()) + 3600
    with tempfile.TemporaryDirectory(prefix="keeper-enroll-") as home:
        state = Path(home) / "state"
        nodes = state / "nodes"
        nodes.mkdir(parents=True)
        # A record an older keeper wrote, with its credential in the clear.
        legacy = nodes / "legacy-01.txt"
        legacy.write_text(f"legacy-01|cHVi|default|1|3|{LEGACY_CREDENTIAL}|1700000000\n", encoding="utf-8")
        legacy.chmod(0o600)
        tokens = state / "enrollment.tokens"
        tokens.write_text(
            f"nodevice||default|1|5|{future}|\n"
            f"noexpiry|garden-01|default|1|5|0|\n"
            f"good|garden-01|default|1|5|{future}|\n"
            f"second|garden-01|default|1|5|{future}|\n"
            f"again|garden-01|default|2|6|{future}|reenroll\n"
            f"race|racer-01|default|1|9|{future}|\n",
            encoding="utf-8")
        tokens.chmod(0o600)
        env = dict(os.environ)
        env.setdefault("RHO_HOME", os.path.join(os.path.expanduser("~"), ".rho"))
        env["ROBOHUB_WORKSPACE"] = str(PROJECTS)
        env["RHO_KEEPER_STATE_DIR"] = str(state)
        env["HOME"] = home
        env["RHO_HTTP_ADDR"] = f"127.0.0.1:{port}"
        keys = Path(home) / ".rho" / "auth"
        keys.mkdir(parents=True)
        subprocess.run([RHO_CMD, "auth", "keygen", "--dir", str(keys), "--force"],
                       check=True, capture_output=True, text=True)
        process = subprocess.Popen([str(binary)], cwd=ROBOHUB, env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            wait_for(base)

            record = legacy.read_text(encoding="utf-8")
            expect(LEGACY_CREDENTIAL not in record and "|s1$" in record,
                   "a plaintext credential is hashed when the keeper starts")
            status, answer = post(base, "/api/nodes/verify",
                                  {"device_id": "legacy-01", "credential": LEGACY_CREDENTIAL}, "10.1.0.1")
            expect(status == 200 and answer.get("node") == 3, "a migrated credential still verifies")

            status, answer = enroll(base, "nodevice", "garden-01", "10.1.0.2")
            expect(status == 403 and "no device" in answer.get("error", ""), "a token without a device is refused")
            status, answer = enroll(base, "noexpiry", "garden-01", "10.1.0.2")
            expect(status == 403 and "expiry" in answer.get("error", ""), "a token without an expiry is refused")

            status, answer = enroll(base, "good", "garden-01", "10.1.0.3", project="default", area="1", node="8")
            expect(status == 403 and "placement" in answer.get("error", ""),
                   "a request whose placement is not its token's is refused")
            status, answer = enroll(base, "good", "garden-02", "10.1.0.3")
            expect(status == 403, "a token is refused for another device")

            status, answer = enroll(base, "good", "garden-01", "10.1.0.4")
            expect(status == 200 and answer.get("area") == 1 and answer.get("node") == 5,
                   "a request without a placement is enrolled at the token's")
            credential = answer.get("credential", "")
            record_path = nodes / "garden-01.txt"
            record = record_path.read_text(encoding="utf-8")
            expect(credential and credential not in record and "|s1$" in record,
                   "the credential is stored as a salted hash")
            expect(stat.S_IMODE(record_path.stat().st_mode) == 0o600, "the node record is 0600")
            expect(record.split("|")[3:5] == ["1", "5"], "the record holds the token's placement")

            status, _ = enroll(base, "good", "garden-01", "10.1.0.5")
            expect(status == 409, "a spent token is refused")
            status, answer = enroll(base, "second", "garden-01", "10.1.0.5")
            expect(status == 409 and "already enrolled" in answer.get("error", ""),
                   "an enrolled device is not replaced by an ordinary token")
            status, answer = post(base, "/api/nodes/verify",
                                  {"device_id": "garden-01", "credential": credential}, "10.1.0.6")
            expect(status == 200 and answer.get("node") == 5, "the first credential still verifies")

            status, answer = enroll(base, "again", "garden-01", "10.1.0.7")
            expect(status == 200 and answer.get("area") == 2, "a re-enroll token replaces the device")
            status, _ = post(base, "/api/nodes/verify",
                             {"device_id": "garden-01", "credential": credential}, "10.1.0.8")
            expect(status == 403, "the replaced credential no longer verifies")
            status, _ = post(base, "/api/nodes/verify",
                             {"device_id": "garden-01", "credential": answer["credential"]}, "10.1.0.8")
            expect(status == 200, "the new one does")

            # One token presented many times at once enrolls once.
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(
                    lambda i: enroll(base, "race", "racer-01", f"10.2.0.{i}")[0], range(8)))
            expect(results.count(200) == 1, f"a token presented eight times at once enrolls once ({results})")
            lines = tokens.read_text(encoding="utf-8").splitlines()
            expect(len(lines) == 6 and all(line.endswith("|used") for line in lines
                                           if line.split("|")[0] in ("good", "again", "race")),
                   "the token file keeps every line and marks the spent ones")
            expect(stat.S_IMODE(tokens.stat().st_mode) == 0o600, "the token file stays 0600")
            expect(not (state / "enrollment.tokens.lock").exists(), "the token lock is released")

            # The budget: one client, past its limit.
            codes = [post(base, "/api/nodes/verify", {"device_id": "x", "credential": "y"}, "10.3.0.1")[0]
                     for _ in range(61)]
            expect(codes[:60].count(403) == 60 and codes[60] == 429,
                   "verification has a budget per client")
            other, _ = post(base, "/api/nodes/verify", {"device_id": "x", "credential": "y"}, "10.3.0.2")
            expect(other == 403, "another client has its own budget")
            codes = [enroll(base, "none", "nobody", "10.3.0.3")[0] for _ in range(11)]
            expect(codes[10] == 429 and 429 not in codes[:10], "enrollment has a budget per client")
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    print("keeper enrollment smoke ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
