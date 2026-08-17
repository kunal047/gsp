"""Real, feed-derived alert engine.

Alerts are computed from ACTUAL analytics on the 31 live camera feeds — no
external/mock databases:

  * congestion  — per-camera vehicle count exceeds a threshold
  * surge       — vehicle count spikes above a live per-camera baseline (EMA)
  * watchlist   — an OPERATOR-defined BOLO (vehicle type + colour, or plate)
                  matches a real detection

The VAHAN / eGujCop / AFIS connectors are intentionally NOT faked here; those
are real integrations for deployment (documented in the HLD) and cannot be
queried from this environment.
"""
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from . import models

CONGESTION_MIN = int(os.getenv("CONGESTION_MIN", "10"))
SURGE_FLOOR = int(os.getenv("SURGE_FLOOR", "6"))
SURGE_FACTOR = float(os.getenv("SURGE_FACTOR", "1.8"))
EMA_ALPHA = float(os.getenv("EMA_ALPHA", "0.3"))
THROTTLE_SECONDS = int(os.getenv("ALERT_THROTTLE", "90"))

# in-memory per-camera traffic baseline (prototype: single backend process)
_ema: dict[str, float] = {}


def _now():
    return datetime.now(timezone.utc)


def _throttled(db: Session, kind: str, camera_id: str) -> bool:
    recent = (
        db.query(models.Alert)
        .filter(
            models.Alert.kind == kind,
            models.Alert.camera_id == camera_id,
            models.Alert.ts >= _now() - timedelta(seconds=THROTTLE_SECONDS),
        )
        .first()
    )
    return recent is not None


def _raise(db, kind, camera, reason, severity, count=None, det=None, wl_id=None):
    if _throttled(db, kind, camera.camera_id):
        return None
    a = models.Alert(
        kind=kind,
        watchlist_id=wl_id,
        detection_id=det.id if det else None,
        camera_id=camera.camera_id,
        camera_name=camera.name,
        city=camera.city,
        lat=camera.lat,
        lng=camera.lng,
        plate=det.plate if det else None,
        vehicle_type=det.vehicle_type if det else None,
        color=det.color if det else None,
        vehicle_count=count,
        reason=reason,
        source="Traffic Analytics",
        severity=severity,
        snapshot=det.snapshot if det else None,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def process_frame(db: Session, camera, vehicle_count: int):
    """Congestion + surge alerts from a real per-frame vehicle count."""
    cid = camera.camera_id
    prev = _ema.get(cid)
    created = []

    if vehicle_count >= CONGESTION_MIN:
        sev = "high" if vehicle_count >= CONGESTION_MIN + 4 else "medium"
        a = _raise(
            db,
            "congestion",
            camera,
            f"Congestion — {vehicle_count} vehicles in frame",
            sev,
            count=vehicle_count,
        )
        if a:
            created.append(a)

    if prev is not None and vehicle_count >= max(
        SURGE_FLOOR, SURGE_FACTOR * prev
    ):
        a = _raise(
            db,
            "surge",
            camera,
            f"Traffic surge — {vehicle_count} vehicles (baseline ~{prev:.0f})",
            "medium",
            count=vehicle_count,
        )
        if a:
            created.append(a)

    _ema[cid] = (
        float(vehicle_count)
        if prev is None
        else EMA_ALPHA * vehicle_count + (1 - EMA_ALPHA) * prev
    )
    return created


# --- Representative watchlist database (challenge Step 3) ------------------
# Synthetic records of interest — NOT live government data. Vehicle entries
# (plate / attribute) match live detections now; person entries need face
# recognition (roadmap) and sit in the DB as complete structure.
SEED_WATCHLIST = [
    {
        "category": "stolen_vehicle", "kind": "plate", "plate_norm": "GJ01AB1234",
        "label": "Maruti Swift (white) · GJ 01 AB 1234", "case_ref": "FIR 214/2026",
        "reason": "Stolen vehicle", "severity": "high",
    },
    {
        "category": "blacklisted_vehicle", "kind": "attribute",
        "vehicle_type": "truck", "color": "white",
        "label": "White truck · suspected contraband", "case_ref": "NCB/2026/07",
        "reason": "Blacklisted — contraband movement", "severity": "high",
    },
    {
        "category": "suspect_vehicle", "kind": "attribute",
        "vehicle_type": "car", "color": "red",
        "label": "Red car · hit & run suspect", "case_ref": "FIR 88/2026",
        "reason": "Suspect vehicle (Navrangpura PS)", "severity": "medium",
    },
    {
        "category": "wanted_person", "kind": "person",
        "label": "Wanted suspect · face on record", "case_ref": "CID/2026/12",
        "reason": "Wanted — requires face recognition (roadmap)", "severity": "high",
    },
    {
        "category": "missing_person", "kind": "person",
        "label": "Missing minor · last seen Paldi", "case_ref": "MP/2026/33",
        "reason": "Missing person — requires face recognition (roadmap)",
        "severity": "high",
    },
]


def seed_watchlist(db: Session):
    if db.query(models.Watchlist).count() > 0:
        return
    for w in SEED_WATCHLIST:
        db.add(models.Watchlist(source="Representative dataset", **w))
    db.commit()


def _wl_matches(item: models.Watchlist, det: models.DetectionEvent):
    """Return the match dimension ('plate'|'attribute') or None."""
    if item.kind == "plate":
        if det.plate_norm and item.plate_norm == det.plate_norm:
            return "plate"
        return None
    if item.kind == "attribute":
        if item.vehicle_type and item.vehicle_type != det.vehicle_type:
            return None
        if item.color and item.color != det.color:
            return None
        if item.vehicle_type or item.color:
            return "attribute"
    return None  # person entries match via face recognition (roadmap)


def check_watchlist(db: Session, det: models.DetectionEvent):
    created = []
    items = (
        db.query(models.Watchlist)
        .filter(models.Watchlist.active.is_(True))
        .all()
    )
    for item in items:
        matched_on = _wl_matches(item, det)
        if not matched_on:
            continue
        recent = (
            db.query(models.Alert)
            .filter(
                models.Alert.watchlist_id == item.id,
                models.Alert.camera_id == det.camera_id,
                models.Alert.ts
                >= _now() - timedelta(seconds=THROTTLE_SECONDS),
            )
            .first()
        )
        if recent:
            continue
        a = models.Alert(
            kind="watchlist",
            watchlist_id=item.id,
            watchlist_category=item.category,
            case_ref=item.case_ref,
            matched_on=matched_on,
            detection_id=det.id,
            camera_id=det.camera_id,
            camera_name=det.camera_name,
            city=det.city,
            lat=det.lat,
            lng=det.lng,
            plate=det.plate,
            vehicle_type=det.vehicle_type,
            color=det.color,
            reason=f"{item.label} — {item.reason}",
            source="Watchlist match",
            severity=item.severity,
            snapshot=det.snapshot,
        )
        db.add(a)
        db.commit()
        db.refresh(a)
        created.append(a)
    return created
