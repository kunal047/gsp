"""In-process camera metadata cache for the high-frequency ingest paths.

`POST /api/frame` (per sampled frame) and `POST /api/detections` (per event)
looked up the camera row on every call. Against a remote managed Postgres that
is a ~600 ms round-trip that also pins a pooled connection, so the ingest tier
saturated at ~15 req/s (pool size / latency). Camera metadata is effectively
static, so we cache it in-process with a short TTL - the hot path becomes
in-memory and the DB connection is freed for real writes.
"""
import time
from threading import Lock
from types import SimpleNamespace

from . import models

TTL_SECONDS = 30.0

_cache: dict[str, SimpleNamespace] = {}
_loaded_at = 0.0
_lock = Lock()


def _refresh(db) -> None:
    global _loaded_at
    rows = db.query(
        models.Camera.camera_id, models.Camera.name, models.Camera.city,
        models.Camera.source_system, models.Camera.source_adapter,
        models.Camera.lat, models.Camera.lng,
    ).all()
    fresh = {
        r[0]: SimpleNamespace(
            camera_id=r[0], name=r[1], city=r[2], source_system=r[3],
            source_adapter=r[4], lat=r[5], lng=r[6],
        )
        for r in rows
    }
    with _lock:
        _cache.clear()
        _cache.update(fresh)
        _loaded_at = time.monotonic()


def get_camera(db, camera_id: str):
    """Return a lightweight camera view for the hot paths, or None if unknown.

    Refreshes on TTL expiry; on a miss it does at most one guarded reload so a
    just-onboarded camera is picked up promptly without a query per frame."""
    now = time.monotonic()
    if not _cache or now - _loaded_at > TTL_SECONDS:
        _refresh(db)
    cam = _cache.get(camera_id)
    if cam is None and time.monotonic() - _loaded_at > 1.0:
        _refresh(db)
        cam = _cache.get(camera_id)
    return cam


def invalidate() -> None:
    global _loaded_at
    with _lock:
        _loaded_at = 0.0
