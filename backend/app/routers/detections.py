import base64
import os
import re
import uuid
from math import asin, cos, radians, sin, sqrt
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import integrations, models, schemas
from ..bus import publish_detection
from ..db import get_db
from ..rbac import Principal, audit, principal

router = APIRouter(prefix="/api", tags=["detections"])

SNAP_DIR = os.getenv("SNAPSHOT_DIR", "/snapshots")


def normalize_plate(plate: Optional[str]) -> Optional[str]:
    if not plate:
        return None
    return re.sub(r"[^A-Z0-9]", "", plate.upper())


def _save_snapshot(b64: str) -> Optional[str]:
    try:
        raw = base64.b64decode(b64.split(",")[-1])
        os.makedirs(SNAP_DIR, exist_ok=True)
        fn = f"{uuid.uuid4().hex}.jpg"
        with open(os.path.join(SNAP_DIR, fn), "wb") as f:
            f.write(raw)
        return f"/snapshots/{fn}"
    except Exception as e:  # noqa: BLE001
        print(f"[detections] snapshot save failed: {e}")
        return None


@router.post("/detections", response_model=schemas.DetectionOut)
def ingest_detection(d: schemas.DetectionIn, db: Session = Depends(get_db)):
    cam = (
        db.query(models.Camera)
        .filter(models.Camera.camera_id == d.camera_id)
        .first()
    )
    snap = _save_snapshot(d.snapshot_b64) if d.snapshot_b64 else None
    ev = models.DetectionEvent(
        camera_id=d.camera_id,
        camera_name=cam.name if cam else d.camera_id,
        city=cam.city if cam else None,
        event_type=d.event_type,
        plate=d.plate,
        plate_norm=normalize_plate(d.plate),
        vehicle_type=d.vehicle_type,
        color=d.color,
        confidence=d.confidence,
        plate_confidence=d.plate_confidence,
        snapshot=snap,
        lat=cam.lat if cam else None,
        lng=cam.lng if cam else None,
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    publish_detection(
        {
            "id": ev.id,
            "camera_id": ev.camera_id,
            "camera_name": ev.camera_name,
            "city": ev.city,
            "event_type": ev.event_type,
            "plate": ev.plate,
            "vehicle_type": ev.vehicle_type,
            "ts": ev.ts,
        }
    )
    # Operator watchlist (BOLO) match -> real-time alert
    integrations.check_watchlist(db, ev)
    return ev


@router.post("/frame")
def frame_summary(payload: dict, db: Session = Depends(get_db)):
    """Per-frame vehicle count from the worker -> real congestion/surge alerts
    computed from the live feed (no external DB)."""
    cam = (
        db.query(models.Camera)
        .filter(models.Camera.camera_id == payload.get("camera_id"))
        .first()
    )
    if not cam:
        return {"alerts": 0}
    count = int(payload.get("vehicle_count", 0))
    created = integrations.process_frame(db, cam, count)
    return {"alerts": len(created)}


@router.get("/detections", response_model=List[schemas.DetectionOut])
def list_detections(
    limit: int = Query(50, le=500),
    since_id: Optional[int] = None,
    camera_id: Optional[str] = None,
    plate: Optional[str] = None,
    event_type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(models.DetectionEvent)
    if since_id:
        q = q.filter(models.DetectionEvent.id > since_id)
    if camera_id:
        q = q.filter(models.DetectionEvent.camera_id == camera_id)
    if event_type:
        q = q.filter(models.DetectionEvent.event_type == event_type)
    if plate:
        q = q.filter(
            models.DetectionEvent.plate_norm.like(f"%{normalize_plate(plate)}%")
        )
    return q.order_by(models.DetectionEvent.id.desc()).limit(limit).all()


@router.get("/track")
def track(
    plate: Optional[str] = None,
    vehicle_type: Optional[str] = None,
    color: Optional[str] = None,
    limit: int = Query(300, le=1000),
    db: Session = Depends(get_db),
    p: Principal = Depends(principal),
):
    """Hybrid cross-camera tracking. Match a target either by plate (ANPR) or by
    vehicle attributes (type + colour), and return a time-ordered route across
    cameras — the scored 'movement history' output."""
    q = db.query(models.DetectionEvent)
    mode = None
    if plate:
        q = q.filter(
            models.DetectionEvent.plate_norm.like(f"%{normalize_plate(plate)}%")
        )
        mode = "plate"
    else:
        if vehicle_type:
            q = q.filter(models.DetectionEvent.vehicle_type == vehicle_type)
        if color:
            q = q.filter(models.DetectionEvent.color == color)
        mode = "attribute"
    rows = (
        q.order_by(models.DetectionEvent.ts.asc()).limit(limit).all()
    )
    route = [
        {
            "id": r.id,
            "camera_id": r.camera_id,
            "camera_name": r.camera_name,
            "city": r.city,
            "lat": r.lat,
            "lng": r.lng,
            "ts": r.ts,
            "plate": r.plate,
            "vehicle_type": r.vehicle_type,
            "color": r.color,
            "snapshot": r.snapshot,
        }
        for r in rows
        if r.lat is not None and r.lng is not None
    ]
    # Aggregate into a clean path: each camera once, ordered by first sighting,
    # with a sighting count and first/last-seen window.
    agg: dict = {}
    for r in route:
        cid = r["camera_id"]
        a = agg.get(cid)
        if a is None:
            agg[cid] = {
                "camera_id": cid,
                "camera_name": r["camera_name"],
                "city": r["city"],
                "lat": r["lat"],
                "lng": r["lng"],
                "first_seen": r["ts"],
                "last_seen": r["ts"],
                "count": 1,
                "snapshot": r["snapshot"],
            }
        else:
            a["last_seen"] = r["ts"]
            a["count"] += 1
            if r["snapshot"] and not a["snapshot"]:
                a["snapshot"] = r["snapshot"]
    path = sorted(agg.values(), key=lambda x: x["first_seen"])

    q = {"plate": plate, "vehicle_type": vehicle_type, "color": color}
    audit(
        db,
        p,
        "vehicle.track",
        f"{mode} match {q} -> {len(route)} sightings / {len(agg)} cameras",
    )
    return {
        "mode": mode,
        "query": q,
        "count": len(route),
        "cameras": len(agg),
        "route": route,
        "path": path,
    }


# --- Space-time single-vehicle tracker ------------------------------------
MAX_SPEED_KMH = float(os.getenv("TRACK_MAX_SPEED", "80"))  # can't teleport
TYPICAL_SPEED_KMH = float(os.getenv("TRACK_TYPICAL_SPEED", "30"))
MAX_HOP_SECONDS = int(os.getenv("TRACK_MAX_HOP_S", "1200"))  # 20 min
MAX_HOP_KM = float(os.getenv("TRACK_MAX_HOP_KM", "25"))
MAX_HOPS = int(os.getenv("TRACK_MAX_HOPS", "10"))


def _haversine_km(a_lat, a_lng, b_lat, b_lng):
    dlat = radians(b_lat - a_lat)
    dlng = radians(b_lng - a_lng)
    h = (
        sin(dlat / 2) ** 2
        + cos(radians(a_lat)) * cos(radians(b_lat)) * sin(dlng / 2) ** 2
    )
    return 2 * 6371.0 * asin(sqrt(h))


@router.get("/track/vehicle")
def track_single_vehicle(
    vehicle_type: str,
    color: str,
    start_id: Optional[int] = None,
    db: Session = Depends(get_db),
    p: Principal = Depends(principal),
):
    """Reconstruct ONE vehicle's most-plausible trajectory. Starting from a
    sighting, only follow to a next-camera sighting that is physically reachable
    (spatio-temporal gate on inter-camera distance vs elapsed time). Attribute +
    reachability isolates a single vehicle from the class without a plate."""
    pool = (
        db.query(models.DetectionEvent)
        .filter(
            models.DetectionEvent.vehicle_type == vehicle_type,
            models.DetectionEvent.color == color,
            models.DetectionEvent.lat.isnot(None),
            models.DetectionEvent.ts.isnot(None),
        )
        .order_by(models.DetectionEvent.ts.asc())
        .all()
    )
    if not pool:
        return {"mode": "single-vehicle", "hops": 0, "path": [], "rejected": 0}

    start = None
    if start_id is not None:
        start = next((d for d in pool if d.id == start_id), None)
    start = start or pool[0]

    path = [start]
    used_cams = {start.camera_id}
    current = start
    rejected = 0
    for _ in range(MAX_HOPS):
        best, best_score = None, None
        for c in pool:
            if c.camera_id in used_cams:
                continue
            dt = (c.ts - current.ts).total_seconds()
            if dt <= 0:
                continue
            dist = _haversine_km(current.lat, current.lng, c.lat, c.lng)
            if dist > MAX_HOP_KM or dt > MAX_HOP_SECONDS:
                continue
            min_dt = dist / MAX_SPEED_KMH * 3600.0  # physical floor
            if dt < min_dt:
                rejected += 1  # would require impossible speed
                continue
            expected = (dist / TYPICAL_SPEED_KMH * 3600.0) if dist > 0 else 0.0
            score = abs(dt - expected)
            if best_score is None or score < best_score:
                best, best_score = c, score
        if best is None:
            break
        path.append(best)
        used_cams.add(best.camera_id)
        current = best

    stops = []
    for i, s in enumerate(path):
        stop = {
            "id": s.id,
            "camera_id": s.camera_id,
            "camera_name": s.camera_name,
            "city": s.city,
            "lat": s.lat,
            "lng": s.lng,
            "ts": s.ts,
            "snapshot": s.snapshot,
            "gap_s": None,
            "dist_km": None,
            "speed_kmh": None,
        }
        if i > 0:
            prev = path[i - 1]
            dt = (s.ts - prev.ts).total_seconds()
            dist = _haversine_km(prev.lat, prev.lng, s.lat, s.lng)
            stop["gap_s"] = int(dt)
            stop["dist_km"] = round(dist, 2)
            stop["speed_kmh"] = round(dist / (dt / 3600.0), 1) if dt > 0 else 0
        stops.append(stop)

    audit(
        db,
        p,
        "vehicle.track_single",
        f"{color} {vehicle_type} from #{start.id} -> {len(stops)} hops",
    )
    return {
        "mode": "single-vehicle",
        "vehicle_type": vehicle_type,
        "color": color,
        "start_id": start.id,
        "hops": len(stops),
        "rejected_infeasible": rejected,
        "path": stops,
    }


@router.get("/detections/stats")
def detection_stats(db: Session = Depends(get_db)):
    total = db.query(func.count(models.DetectionEvent.id)).scalar()
    anpr = (
        db.query(func.count(models.DetectionEvent.id))
        .filter(models.DetectionEvent.event_type == "anpr")
        .scalar()
    )
    plates = (
        db.query(func.count(func.distinct(models.DetectionEvent.plate_norm)))
        .filter(models.DetectionEvent.plate_norm.isnot(None))
        .scalar()
    )
    cams = (
        db.query(func.count(func.distinct(models.DetectionEvent.camera_id)))
        .scalar()
    )
    return {
        "total": total,
        "anpr": anpr,
        "unique_plates": plates,
        "active_cameras": cams,
    }
