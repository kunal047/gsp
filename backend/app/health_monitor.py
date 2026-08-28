"""Real camera health monitor.

Liveness is taken from the provider's authoritative per-camera state
(`/api/cameras/{id}/state` -> `status`), not from pulling media. The provider
serves a live HLS edge; the legacy progressive `/stream/{id}` MP4 is a ~1.3 GB
non-faststart file that intermittently stalls, so probing it produced false
offline flapping. On a real online->offline transition we raise a feed_offline
alert.
"""
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from . import models
from .db import SessionLocal

INTERVAL = int(os.getenv("HEALTH_INTERVAL", "90"))
TIMEOUT = int(os.getenv("HEALTH_TIMEOUT", "6"))


def _state_url(cam) -> str | None:
    base = (cam.source or "").rstrip("/")
    if not base:
        return None
    provider_id = cam.camera_id.split("-")[-1].lstrip("0") or "0"
    return f"{base}/api/cameras/{provider_id}/state"


def _probe_rtsp(stream_url: str) -> str:
    """RTSP has no HTTP status; use a TCP connect to the media server as a
    liveness check (refused -> offline, timeout -> degraded, open -> online)."""
    parsed = urllib.parse.urlparse(stream_url)
    host, port = parsed.hostname, parsed.port or 554
    if not host:
        return "degraded"
    sock = socket.socket()
    sock.settimeout(TIMEOUT)
    try:
        sock.connect((host, port))
        return "online"
    except (ConnectionRefusedError, OSError) as error:
        return "offline" if isinstance(error, ConnectionRefusedError) else "degraded"
    finally:
        sock.close()


def probe(cam) -> str:
    if cam.source_adapter != "csitms_api":
        if not cam.stream_url:
            return "degraded"
        if cam.stream_url.startswith("rtsp://"):
            return _probe_rtsp(cam.stream_url)
        request = urllib.request.Request(
            cam.stream_url,
            headers={"Range": "bytes=0-2048", "User-Agent": "netra/health"},
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                return "online" if response.status in (200, 206) else "degraded"
        except urllib.error.HTTPError as error:
            return "offline" if error.code >= 500 else "degraded"
        except Exception:
            return "degraded"
    url = _state_url(cam)
    if not url:
        return "degraded"
    req = urllib.request.Request(url, headers={"User-Agent": "netra/health"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = json.load(r)
        return "online" if data.get("status") == "live" else "offline"
    except Exception:
        return "degraded"  # transient network issue, not a confirmed outage


def _raise_offline_alert(db, cam):
    db.add(
        models.Alert(
            kind="feed_offline",
            camera_id=cam.camera_id,
            camera_name=cam.name,
            city=cam.city,
            source_system=cam.source_system,
            lat=cam.lat,
            lng=cam.lng,
            reason=f"Camera feed offline - {cam.name}",
            source="Health Monitor",
            severity="high",
        )
    )
    db.commit()


def run_once():
    # Snapshot the cameras and release the DB connection BEFORE probing. Probing
    # 30+ feeds (each up to TIMEOUT) can take minutes; holding a Supabase session
    # open that long lets the pooler drop it, so the later commit died with
    # "SSL SYSCALL error: EOF". Probe with no DB held, then commit once.
    db = SessionLocal()
    try:
        snapshot = [(c.id, c.camera_id, c.source_adapter, c.stream_url,
                     c.source, c.health_status) for c in db.query(models.Camera).all()]
    finally:
        db.close()

    class _Probe:  # minimal shim so probe() can read attributes off a tuple row
        def __init__(self, row):
            (self.id, self.camera_id, self.source_adapter, self.stream_url,
             self.source, self.health_status) = row

    rows = [_Probe(r) for r in snapshot]
    results = {}
    with ThreadPoolExecutor(max_workers=12) as pool:
        for cam, status in zip(rows, pool.map(probe, rows)):
            results[cam.id] = status

    changed = [(r, results[r.id]) for r in rows if results[r.id] != r.health_status]
    if not changed:
        return
    db = SessionLocal()
    try:
        for shim, status in changed:
            cam = db.query(models.Camera).filter(models.Camera.id == shim.id).first()
            if not cam:
                continue
            was = cam.health_status
            cam.health_status = status
            if status == "offline" and was != "offline":
                _raise_offline_alert(db, cam)
        db.commit()
    finally:
        db.close()


def _loop():
    # small initial delay so the app finishes onboarding first
    time.sleep(10)
    while True:
        try:
            run_once()
        except Exception as e:  # noqa: BLE001
            print(f"[health] monitor error: {e}")
        time.sleep(INTERVAL)


def start():
    threading.Thread(target=_loop, daemon=True).start()
