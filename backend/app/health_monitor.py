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
import threading
import time
import urllib.error
import urllib.request

from . import models
from .db import SessionLocal

INTERVAL = int(os.getenv("HEALTH_INTERVAL", "90"))
TIMEOUT = int(os.getenv("HEALTH_TIMEOUT", "10"))


def _state_url(cam) -> str | None:
    base = (cam.source or "").rstrip("/")
    if not base:
        return None
    provider_id = cam.camera_id.split("-")[-1].lstrip("0") or "0"
    return f"{base}/api/cameras/{provider_id}/state"


def probe(cam) -> str:
    if cam.source_adapter != "csitms_api":
        if not cam.stream_url:
            return "degraded"
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
            reason=f"Camera feed offline — {cam.name}",
            source="Health Monitor",
            severity="high",
        )
    )
    db.commit()


def run_once():
    db = SessionLocal()
    try:
        cams = db.query(models.Camera).all()
        for c in cams:
            status = probe(c)
            if status != c.health_status:
                was = c.health_status
                c.health_status = status
                db.commit()
                if status == "offline" and was != "offline":
                    _raise_offline_alert(db, c)
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
