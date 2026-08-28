#!/usr/bin/env python3
"""Netra 50-feed scalability benchmark - ingestion tier.

Drives the REAL running backend with the per-frame analytics traffic that N live
feeds produce (`POST /api/frame` - the high-frequency congestion/surge path that
does a camera lookup + baseline update + alert check per call). Sweeps
concurrency to find the sustained throughput and latency curve, then reports how
many feeds the ingestion tier supports at the SCALABILITY.md sampling rate.

Pure stdlib so it runs anywhere. Analytics per-feed ML cost is measured
separately (bench/analytics_cost.py, run inside the analytics container).

Env: BENCH_BASE (default http://localhost:8000), BENCH_FEEDS (50),
     BENCH_FPS (5), BENCH_USER/BENCH_PASS for onboarding.
"""
import json
import os
import statistics
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = os.getenv("BENCH_BASE", "http://localhost:8000").rstrip("/")
FEEDS = int(os.getenv("BENCH_FEEDS", "50"))
FPS = float(os.getenv("BENCH_FPS", "5"))          # SCALABILITY.md sampling rate
USER = os.getenv("BENCH_USER", "commissioner")
PASS = os.getenv("BENCH_PASS", "netra-admin")
PREFIX = "BENCH-"


def _req(method, path, body=None, token=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read()
            return (time.perf_counter() - t0) * 1000, r.status, None
    except urllib.error.HTTPError as e:
        return (time.perf_counter() - t0) * 1000, e.code, None
    except Exception as e:  # noqa: BLE001
        return (time.perf_counter() - t0) * 1000, 0, str(e)


def login():
    req = urllib.request.Request(
        BASE + "/api/auth/login",
        data=json.dumps({"username": USER, "password": PASS}).encode(),
        method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)["access_token"]


def onboard(token):
    rows = [{
        "camera_id": f"{PREFIX}{i:03d}", "name": f"Bench Feed {i:03d}",
        "city": "Benchmark", "source_system": "Benchmark", "source_adapter": "bench",
        "external_id": f"bench-{i}", "lat": 23.0 + i * 0.001, "lng": 72.0,
        "analytics_enabled": True, "health_status": "online",
    } for i in range(1, FEEDS + 1)]
    _, status, err = _req("POST", "/api/cameras/bulk", rows, token=token)
    return status, err


def cleanup(token):
    for i in range(1, FEEDS + 1):
        _req("DELETE", f"/api/cameras/{PREFIX}{i:03d}", token=token)


def phase(concurrency, duration, count=2):
    """Closed-loop: `concurrency` workers POST /api/frame as fast as they can for
    `duration` seconds. count is kept below any threshold to measure pure ingest."""
    stop = time.time() + duration
    lat, errors, n = [], 0, [0]
    lock = threading.Lock()

    def worker(wid):
        nonlocal errors
        local = []
        i = 0
        while time.time() < stop:
            cam = f"{PREFIX}{((wid * 7 + i) % FEEDS) + 1:03d}"
            ms, status, err = _req("POST", "/api/frame",
                                   {"camera_id": cam, "vehicle_count": count}, timeout=30)
            local.append(ms)
            if status != 200:
                with lock:
                    errors += 1
            i += 1
        with lock:
            lat.extend(local)
            n[0] += len(local)

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        for w in range(concurrency):
            pool.submit(worker, w)
    elapsed = time.perf_counter() - t0
    lat.sort()
    def pct(p):
        return lat[min(len(lat) - 1, int(len(lat) * p))] if lat else 0
    return {
        "concurrency": concurrency, "requests": len(lat), "seconds": round(elapsed, 1),
        "rps": round(len(lat) / elapsed, 1), "errors": errors,
        "p50_ms": round(pct(0.50), 1), "p95_ms": round(pct(0.95), 1),
        "p99_ms": round(pct(0.99), 1),
        "mean_ms": round(statistics.mean(lat), 1) if lat else 0,
    }


def main():
    print(f"[bench] target: {FEEDS} feeds @ {FPS} fps = {FEEDS * FPS:.0f} req/s on {BASE}", flush=True)
    token = login()
    status, err = onboard(token)
    print(f"[bench] onboarded {FEEDS} bench cameras (bulk status {status})", flush=True)
    time.sleep(1)

    results = []
    for c in [1, 30, 100, 200, 300]:
        r = phase(c, duration=8)
        results.append(r)
        print(f"[bench] conc={c:>3}  {r['rps']:>7} req/s  "
              f"p50={r['p50_ms']:>6}ms p95={r['p95_ms']:>7}ms p99={r['p99_ms']:>7}ms  "
              f"errors={r['errors']}", flush=True)

    max_rps = max(r["rps"] for r in results)
    feeds_supported = max_rps / FPS
    summary = {
        "target_feeds": FEEDS, "sampling_fps": FPS,
        "target_rps": FEEDS * FPS, "max_sustained_rps": max_rps,
        "feeds_supported_single_backend": round(feeds_supported),
        "meets_target": max_rps >= FEEDS * FPS,
        "phases": results,
    }
    print("\n[bench] === INGESTION SUMMARY ===", flush=True)
    print(f"[bench] max sustained: {max_rps} req/s -> "
          f"{feeds_supported:.0f} feeds @ {FPS}fps on ONE backend process", flush=True)
    print(f"[bench] 50-feed target ({FEEDS*FPS:.0f} req/s) met: {summary['meets_target']}", flush=True)
    with open(os.getenv("BENCH_OUT", "/tmp/bench_ingest.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print(f"[bench] wrote {os.getenv('BENCH_OUT', '/tmp/bench_ingest.json')}", flush=True)

    cleanup(token)
    print(f"[bench] cleaned up {FEEDS} bench cameras", flush=True)


if __name__ == "__main__":
    main()
