#!/usr/bin/env python3
"""Run and record the scored vehicle-search workflow against a live Netra API."""

from __future__ import annotations

import csv
import io
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = os.getenv("NETRA_API_BASE", "http://localhost:8000").rstrip("/")
PLATE = os.getenv("NETRA_TEST_PLATE", "GJ01AB1234")
USER = os.getenv("NETRA_USER", "commissioner")
PASSWORD = os.getenv("NETRA_PASSWORD")
EXPECTED_HOPS = int(os.getenv("NETRA_EXPECTED_HOPS", "3"))
OUT = Path(os.getenv("NETRA_REHEARSAL_OUT", "submission/evidence/rehearsal-result.json"))


def fetch(path: str, token: str, *, raw: bool = False):
    request = urllib.request.Request(
        f"{API}{path}", headers={"Authorization": f"Bearer {token}"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = response.read()
        return payload if raw else json.loads(payload)


def main() -> int:
    if not PASSWORD:
        raise SystemExit("NETRA_PASSWORD is required")
    started = time.perf_counter()
    body = json.dumps({"username": USER, "password": PASSWORD}).encode()
    login = urllib.request.Request(
        f"{API}/api/auth/login", data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(login, timeout=15) as response:
        token = json.load(response)["access_token"]
    authenticated_ms = round((time.perf_counter() - started) * 1000, 1)

    health = fetch("/api/health", token)
    query = urllib.parse.urlencode({"plate": PLATE})
    search_started = time.perf_counter()
    route = fetch(f"/api/track?{query}", token)
    search_ms = round((time.perf_counter() - search_started) * 1000, 1)
    csv_bytes = fetch(f"/api/reports/detections.csv?{query}", token, raw=True)
    rows = list(csv.DictReader(io.StringIO(csv_bytes.decode())))
    sightings = route.get("sightings") or route.get("route") or []
    unique_cameras = sorted({str(row.get("camera_id")) for row in rows if row.get("camera_id")})
    passed = len(unique_cameras) >= EXPECTED_HOPS and len(rows) >= EXPECTED_HOPS
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "plate": PLATE,
        "passed": passed,
        "expected_hops": EXPECTED_HOPS,
        "csv_rows": len(rows),
        "unique_cameras": unique_cameras,
        "route_sightings": len(sightings),
        "authentication_ms": authenticated_ms,
        "search_ms": search_ms,
        "total_ms": round((time.perf_counter() - started) * 1000, 1),
        "camera_inventory": health.get("cameras"),
        "ingest_error": health.get("ingest_error"),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
