#!/usr/bin/env python3
"""Netra demo preflight: fail fast before an evaluator sees the system."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = os.getenv("NETRA_API_BASE", "http://localhost:8000").rstrip("/")
FRONTEND = os.getenv("NETRA_FRONTEND_BASE", "http://localhost:5173").rstrip("/")
EXPECTED_CAMERAS = int(os.getenv("NETRA_EXPECTED_CAMERAS", "30"))


class Check:
    def __init__(self, label: str, ok: bool, detail: str):
        self.label, self.ok, self.detail = label, ok, detail


def request(path: str, token: str | None = None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with urllib.request.urlopen(
        urllib.request.Request(f"{API}{path}", headers=headers), timeout=15
    ) as response:
        return json.load(response)


def login() -> str:
    username = os.getenv("NETRA_USER", "commissioner")
    password = os.getenv("NETRA_PASSWORD")
    if not password:
        raise RuntimeError("set NETRA_PASSWORD for authenticated checks")
    body = json.dumps({"username": username, "password": password}).encode()
    req = urllib.request.Request(
        f"{API}/api/auth/login",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.load(response)["access_token"]


def main() -> int:
    checks: list[Check] = []
    for command in ("docker", "ffmpeg"):
        checks.append(Check(command, bool(shutil.which(command)), shutil.which(command) or "missing"))
    checks.append(Check("plate demo clip", (ROOT / "data/clips/plate-demo.mp4").is_file(), "data/clips/plate-demo.mp4"))
    checks.append(Check("frontend lockfile", (ROOT / "frontend/package-lock.json").is_file(), "frontend/package-lock.json"))
    checks.append(Check("environment file", (ROOT / ".env").is_file(), ".env"))

    try:
        result = subprocess.run(
            ["docker", "compose", "config", "--quiet"], cwd=ROOT,
            capture_output=True, text=True, timeout=30,
        )
        checks.append(Check("Compose configuration", result.returncode == 0, (result.stderr or "valid").strip()))
    except Exception as exc:  # noqa: BLE001
        checks.append(Check("Compose configuration", False, str(exc)))

    try:
        health = request("/api/health")
        ok = health.get("status") == "ok" and health.get("cameras", 0) >= EXPECTED_CAMERAS
        checks.append(Check("API and camera inventory", ok, f"{health.get('cameras', 0)} cameras; status={health.get('status')}"))
        checks.append(Check("source ingestion", not health.get("ingest_error"), health.get("ingest_error") or "no ingest error"))
    except Exception as exc:  # noqa: BLE001
        checks.append(Check("API and camera inventory", False, str(exc)))

    try:
        with urllib.request.urlopen(FRONTEND, timeout=10) as response:
            checks.append(Check("frontend", response.status == 200, f"HTTP {response.status}"))
    except Exception as exc:  # noqa: BLE001
        checks.append(Check("frontend", False, str(exc)))

    try:
        token = login()
        me = request("/api/auth/me", token)
        readiness = request("/api/reports/readiness", token)
        federation = request("/api/reports/federation", token)
        checks.append(Check("signed authentication", bool(me.get("user")), f"{me.get('user')} / {me.get('role')}"))
        statuses = {str(item["model"]): item["status"] for item in readiness["models"]}
        checks.append(Check("model readiness", all(value == "pass" for value in statuses.values()), json.dumps(statuses, sort_keys=True)))
        checks.append(Check("two-system federation", federation.get("federated") is True, f"{federation.get('adapter_system_count', 0)} adapted systems"))
    except Exception as exc:  # noqa: BLE001
        checks.append(Check("authenticated readiness", False, str(exc)))

    width = max(len(check.label) for check in checks)
    for check in checks:
        print(f"{'PASS' if check.ok else 'FAIL':4}  {check.label:<{width}}  {check.detail}")
    failed = [check for check in checks if not check.ok]
    print(f"\n{len(checks) - len(failed)}/{len(checks)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
