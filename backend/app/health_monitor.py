"""Real camera health monitor.

Periodically probes each camera's actual stream endpoint and updates its
health_status (online / degraded / offline) from the true HTTP response. On an
online→offline transition it raises a real 'feed_offline' alert. No simulation:
cameras 6 & 22 (HTTP 500 at source) are detected as genuinely offline.
"""
import os
import threading
import time
import urllib.error
import urllib.request

from . import models
from .db import SessionLocal

INTERVAL = int(os.getenv("HEALTH_INTERVAL", "90"))
TIMEOUT = int(os.getenv("HEALTH_TIMEOUT", "8"))


def probe(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={"Range": "bytes=0-2048", "User-Agent": "netra/health"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return "online" if r.status in (200, 206) else "degraded"
    except urllib.error.HTTPError as e:
        return "offline" if e.code >= 500 else "degraded"
    except Exception:
        return "offline"


def _raise_offline_alert(db, cam):
    db.add(
        models.Alert(
            kind="feed_offline",
            camera_id=cam.camera_id,
            camera_name=cam.name,
            city=cam.city,
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
            if not c.stream_url:
                continue
            status = probe(c.stream_url)
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
