import base64
import binascii
import hashlib
import os
import re
import time
import uuid
from datetime import datetime
from math import asin, cos, radians, sin, sqrt
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import cache, integrations, models, schemas, storage
from ..bus import publish_detection
from ..db import get_db
from ..rbac import Principal, audit, principal, require_ingestor

router = APIRouter(prefix="/api", tags=["detections"])

SNAP_DIR = os.getenv("SNAPSHOT_DIR", "/snapshots")
EVIDENCE_DEDUP_SECONDS = int(os.getenv("EVIDENCE_DEDUP_SECONDS", "600"))
_evidence_seen: dict[tuple[str, str, str], float] = {}


def normalize_plate(plate: Optional[str]) -> Optional[str]:
    if not plate:
        return None
    return re.sub(r"[^A-Z0-9]", "", plate.upper())


def _parse_ts(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _save_snapshot(b64: str) -> Optional[str]:
    """Decode the evidence JPEG and persist it to object storage (Supabase
    Storage), falling back to the local volume. Returns the reference stored on
    the row: '/api/evidence/<key>' for object storage, '/snapshots/<key>' local."""
    raw = _decode_snapshot(b64)
    if raw is None:
        return None
    return storage.save(raw)


def _decode_snapshot(b64: str) -> Optional[bytes]:
    try:
        raw = base64.b64decode(b64.split(",")[-1], validate=True)
    except (ValueError, binascii.Error):
        return None
    # The analytics contract emits JPEG. Reject arbitrary/empty bytes so a
    # non-null database path always points to actual visual evidence.
    if len(raw) < 128 or not raw.startswith(b"\xff\xd8") or not raw.endswith(b"\xff\xd9"):
        return None
    return raw


def _snapshot_digest(b64: str) -> Optional[str]:
    raw = _decode_snapshot(b64)
    return hashlib.sha256(raw).hexdigest() if raw else None


def _drop_duplicate_evidence(db: Session, alerts, camera_id: str, digest: str):
    """Discard alert rows whose exact evidence frame recently appeared.

    Watchlist cases are deduplicated independently. Traffic congestion and
    surge share one group so a single frame becomes one operational incident.
    """
    now = time.monotonic()
    alerts = sorted(alerts, key=lambda alert: alert.kind != "congestion")
    kept = []
    dropped = 0
    for alert in alerts:
        group = (
            f"watchlist:{alert.case_ref or alert.watchlist_id}"
            if alert.kind == "watchlist"
            else "traffic"
        )
        key = (camera_id, group, digest)
        previous = _evidence_seen.get(key)
        if previous is not None and now - previous < EVIDENCE_DEDUP_SECONDS:
            db.delete(alert)
            dropped += 1
        else:
            _evidence_seen[key] = now
            kept.append(alert)
    if len(_evidence_seen) > 2000:
        cutoff = now - EVIDENCE_DEDUP_SECONDS
        for key, seen_at in list(_evidence_seen.items()):
            if seen_at < cutoff:
                _evidence_seen.pop(key, None)
    return kept, dropped


@router.post("/detections", response_model=schemas.DetectionOut)
def ingest_detection(
    d: schemas.DetectionIn,
    db: Session = Depends(get_db),
    _p: Principal = Depends(require_ingestor),
):
    if d.track_uuid:
        existing = (
            db.query(models.DetectionEvent)
            .filter(models.DetectionEvent.track_uuid == d.track_uuid)
            .first()
        )
        if existing:
            existing.alert_ids = []
            return existing
    if not d.snapshot_b64:
        raise HTTPException(
            status_code=422,
            detail="snapshot_b64 is required; evidence-less detections are not stored",
        )
    snap = _save_snapshot(d.snapshot_b64)
    if not snap:
        raise HTTPException(
            status_code=422,
            detail="snapshot could not be decoded or saved; detection was not stored",
        )
    cam = cache.get_camera(db, d.camera_id)
    event_ts = d.event_ts or d.first_seen
    first_seen = d.first_seen or event_ts
    last_seen = d.last_seen or event_ts
    if first_seen and last_seen and last_seen < first_seen:
        raise HTTPException(
            status_code=422,
            detail="last_seen must be greater than or equal to first_seen",
        )
    ev = models.DetectionEvent(
        camera_id=d.camera_id,
        camera_name=cam.name if cam else d.camera_id,
        city=cam.city if cam else None,
        source_system=cam.source_system if cam else None,
        source_adapter=cam.source_adapter if cam else None,
        event_type=d.event_type,
        plate=d.plate,
        plate_norm=normalize_plate(d.plate),
        vehicle_type=d.vehicle_type,
        color=d.color,
        confidence=d.confidence,
        plate_confidence=d.plate_confidence,
        track_uuid=d.track_uuid,
        track_id=d.track_id,
        track_hits=d.track_hits,
        class_confidence=d.class_confidence,
        color_confidence=d.color_confidence,
        snapshot=snap,
        lat=cam.lat if cam else None,
        lng=cam.lng if cam else None,
        first_seen=first_seen,
        last_seen=last_seen,
        ts=event_ts,
        time_source=d.time_source,
        direction=d.direction,
        dwell_seconds=d.dwell_seconds,
        motion_px_per_second=d.motion_px_per_second,
        stopped=d.stopped,
        wrong_way=d.wrong_way,
        bbox_x1=d.bbox_x1,
        bbox_y1=d.bbox_y1,
        bbox_x2=d.bbox_x2,
        bbox_y2=d.bbox_y2,
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
            "source_system": ev.source_system,
            "source_adapter": ev.source_adapter,
            "event_type": ev.event_type,
            "plate": ev.plate,
            "vehicle_type": ev.vehicle_type,
            "track_uuid": ev.track_uuid,
            "track_id": ev.track_id,
            "ts": ev.ts,
        }
    )
    # Operator watchlist (BOLO) match -> real-time alert
    matches = integrations.check_watchlist(db, ev)
    # Cloned/duplicate-plate detection: same plate, two cameras, impossible speed.
    clone = integrations.check_impossible_movement(db, ev)
    if clone:
        matches = matches + [clone]
    # The worker uses these IDs to upload the full contextual frame only when
    # a match occurred. Pydantic reads this transient attribute into the API
    # response; it is intentionally not a database column.
    ev.alert_ids = [alert.id for alert in matches]
    return ev


@router.post("/detections/{detection_id}/evidence")
def detection_evidence(
    detection_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    _p: Principal = Depends(require_ingestor),
):
    """Replace a match crop with its selectively retained context frame."""
    detection = (
        db.query(models.DetectionEvent)
        .filter(models.DetectionEvent.id == detection_id)
        .first()
    )
    if not detection or detection.camera_id != payload.get("camera_id"):
        return {"attached": 0}
    requested = payload.get("alert_ids") or []
    alerts = (
        db.query(models.Alert)
        .filter(
            models.Alert.id.in_(requested),
            models.Alert.detection_id == detection_id,
            models.Alert.kind == "watchlist",
        )
        .all()
    )
    snapshot_b64 = payload.get("snapshot_b64")
    if not alerts or not snapshot_b64:
        return {"attached": 0}
    digest = _snapshot_digest(snapshot_b64)
    if not digest:
        return {"attached": 0}
    alerts, dropped = _drop_duplicate_evidence(
        db, alerts, detection.camera_id, digest
    )
    if not alerts:
        db.commit()
        return {"attached": 0, "duplicates_dropped": dropped}
    context_frame = _save_snapshot(snapshot_b64)
    if not context_frame:
        return {"attached": 0}
    for alert in alerts:
        alert.snapshot = context_frame
    db.commit()
    return {
        "attached": len(alerts),
        "duplicates_dropped": dropped,
        "snapshot": context_frame,
    }


@router.post("/frame")
def frame_summary(
    payload: dict,
    db: Session = Depends(get_db),
    _p: Principal = Depends(require_ingestor),
):
    """Per-frame vehicle count from the worker -> real congestion/surge alerts
    computed from the live feed (no external DB)."""
    cam = cache.get_camera(db, payload.get("camera_id"))
    if not cam:
        return {"alerts": 0, "alert_ids": []}
    count = int(payload.get("vehicle_count", 0))
    created = integrations.process_frame(
        db,
        cam,
        count,
        event_ts=_parse_ts(payload.get("event_ts")),
        time_source=payload.get("time_source") or "ingest",
    )
    return {"alerts": len(created), "alert_ids": [a.id for a in created]}


@router.post("/frame/evidence")
def frame_evidence(
    payload: dict,
    db: Session = Depends(get_db),
    _p: Principal = Depends(require_ingestor),
):
    """Attach one selectively retained full frame to traffic alerts.

    The worker calls this only after `/frame` reports newly-created alerts, so
    ordinary sampled frames are never persisted centrally.
    """
    camera_id = payload.get("camera_id")
    alert_ids = payload.get("alert_ids") or []
    snapshot_b64 = payload.get("snapshot_b64")
    if not camera_id or not alert_ids or not snapshot_b64:
        return {"attached": 0}
    alerts = (
        db.query(models.Alert)
        .filter(
            models.Alert.id.in_(alert_ids),
            models.Alert.camera_id == camera_id,
            models.Alert.kind.in_(("congestion", "surge")),
        )
        .all()
    )
    if not alerts:
        return {"attached": 0}
    digest = _snapshot_digest(snapshot_b64)
    if not digest:
        return {"attached": 0}
    alerts, dropped = _drop_duplicate_evidence(db, alerts, camera_id, digest)
    if not alerts:
        db.commit()
        return {"attached": 0, "duplicates_dropped": dropped}
    evidence = _save_snapshot(snapshot_b64)
    if not evidence:
        return {"attached": 0}
    for alert in alerts:
        alert.snapshot = evidence
    db.commit()
    return {
        "attached": len(alerts),
        "duplicates_dropped": dropped,
        "snapshot": evidence,
    }


@router.get("/detections", response_model=List[schemas.DetectionOut])
def list_detections(
    limit: int = Query(50, le=500),
    since_id: Optional[int] = None,
    camera_id: Optional[str] = None,
    plate: Optional[str] = None,
    event_type: Optional[str] = None,
    include_legacy: bool = False,
    db: Session = Depends(get_db),
):
    q = db.query(models.DetectionEvent)
    if not include_legacy:
        q = q.filter(models.DetectionEvent.track_uuid.isnot(None))
    if since_id:
        q = q.filter(models.DetectionEvent.id > since_id)
    if camera_id:
        q = q.filter(models.DetectionEvent.camera_id == camera_id)
    if event_type:
        q = q.filter(models.DetectionEvent.event_type == event_type)
    if plate:
        q = q.filter(models.DetectionEvent.plate_norm == normalize_plate(plate))
    return q.order_by(models.DetectionEvent.id.desc()).limit(limit).all()


PLATE_FUZZ = int(os.getenv("TRACK_PLATE_FUZZ", "1"))


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a or not b:
        return len(a) or len(b)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _resolve_plate_matches(db, query_plate):
    """Find stored plates matching an operator's query, tolerant to ANPR error
    and partial input. Returns (matched_norms, match_type):

      exact   - stored verbatim
      partial - the query is a fragment of a stored plate, or vice-versa (an
                operator recalls only part of a number)
      fuzzy   - within PLATE_FUZZ edits (an OCR misread such as B<->8, O<->0)
    """
    norm = normalize_plate(query_plate)
    if not norm:
        return set(), "none"
    distinct = [
        row[0]
        for row in db.query(models.DetectionEvent.plate_norm)
        .filter(models.DetectionEvent.plate_norm.isnot(None))
        .distinct()
        .all()
    ]
    if norm in distinct:
        return {norm}, "exact"
    partial = {pn for pn in distinct if norm in pn or (len(norm) >= 4 and pn in norm)}
    if partial:
        return partial, "partial"
    fuzzy = {
        pn
        for pn in distinct
        if abs(len(pn) - len(norm)) <= PLATE_FUZZ
        and _levenshtein(pn, norm) <= PLATE_FUZZ
    }
    if fuzzy:
        return fuzzy, "fuzzy"
    return set(), "none"


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
    cameras - the scored 'movement history' output."""
    q = db.query(models.DetectionEvent)
    q = q.filter(models.DetectionEvent.track_uuid.isnot(None))
    mode = None
    match_type = None
    matched_plates: list[str] = []
    if plate:
        matched, match_type = _resolve_plate_matches(db, plate)
        matched_plates = sorted(matched)
        # Fall back to the exact (empty) filter if nothing matched, so the query
        # returns a clean empty route rather than everything.
        q = q.filter(
            models.DetectionEvent.plate_norm.in_(matched)
            if matched
            else models.DetectionEvent.plate_norm == normalize_plate(plate)
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
            "source_system": r.source_system,
            "source_adapter": r.source_adapter,
            "lat": r.lat,
            "lng": r.lng,
            "ts": r.ts,
            "plate": r.plate,
            "plate_norm": r.plate_norm,
            "vehicle_type": r.vehicle_type,
            "color": r.color,
            "snapshot": r.snapshot,
            "track_uuid": r.track_uuid,
            "track_id": r.track_id,
            "track_hits": r.track_hits,
            "class_confidence": r.class_confidence,
            "color_confidence": r.color_confidence,
            "first_seen": r.first_seen,
            "last_seen": r.last_seen,
            "time_source": r.time_source,
            "direction": r.direction,
            "dwell_seconds": r.dwell_seconds,
            "motion_px_per_second": r.motion_px_per_second,
            "stopped": r.stopped,
            "wrong_way": r.wrong_way,
        }
        for r in rows
        if r.lat is not None and r.lng is not None
    ]
    # Aggregate into a clean path: each camera once, ordered by first sighting,
    # with a sighting count and first/last-seen window. When a fuzzy/partial plate
    # query resolves to MORE THAN ONE plate, the resolved plates are different
    # vehicles, so aggregate per (plate, camera) and keep each plate's trajectory
    # separate - otherwise the timeline would splice two vehicles into one route.
    multi_plate = mode == "plate" and len(matched_plates) > 1
    agg: dict = {}
    for r in route:
        pnorm = r["plate_norm"]
        key = (pnorm, r["camera_id"]) if multi_plate else r["camera_id"]
        a = agg.get(key)
        if a is None:
            agg[key] = {
                "camera_id": r["camera_id"],
                "camera_name": r["camera_name"],
                "city": r["city"],
                "source_system": r["source_system"],
                "lat": r["lat"],
                "lng": r["lng"],
                "plate": r["plate"],
                "plate_norm": pnorm,
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
    if multi_plate:
        # Group by plate, then order by first sighting within that plate.
        path = sorted(agg.values(), key=lambda x: (x["plate_norm"] or "", x["first_seen"]))
    else:
        path = sorted(agg.values(), key=lambda x: x["first_seen"])

    # Inter-camera hop metrics turn the path into an investigative timeline:
    # distance, elapsed time and implied speed between consecutive sightings,
    # flagging physically impossible jumps (a likely misread or cloned plate).
    # A hop is only drawn between two sightings of the SAME vehicle, so it is
    # suppressed at the start and across a plate boundary in multi-plate results.
    for i, stop in enumerate(path):
        prev = path[i - 1] if i > 0 else None
        if prev is None or (multi_plate and stop["plate_norm"] != prev["plate_norm"]):
            stop["hop"] = None
            continue
        dist = round(_haversine_km(prev["lat"], prev["lng"], stop["lat"], stop["lng"]), 2)
        gap = None
        if stop["first_seen"] and prev["last_seen"]:
            gap = max(0.0, (stop["first_seen"] - prev["last_seen"]).total_seconds())
        speed = round(dist / (gap / 3600.0), 1) if gap and gap > 0 else None
        stop["hop"] = {
            "from_camera": prev["camera_name"],
            "distance_km": dist,
            "gap_seconds": round(gap) if gap is not None else None,
            "speed_kmh": speed,
            "implausible": bool(speed is not None and speed > IMPLAUSIBLE_SPEED_KMH),
        }

    q = {"plate": plate, "vehicle_type": vehicle_type, "color": color}
    audit(
        db,
        p,
        "vehicle.track",
        f"{mode}:{match_type or '-'} match {q} -> {len(route)} sightings / {len(agg)} cameras",
    )
    return {
        "mode": mode,
        "match": match_type,
        "matched_plates": matched_plates,
        "query": q,
        "count": len(route),
        "cameras": len(agg),
        "route": route,
        "path": path,
    }


# Speed above which an inter-camera hop is flagged "impossible" in the /track
# timeline. Deliberately the SAME threshold the cloned-plate alert uses
# (CLONE_MAX_SPEED_KMH) so the timeline and the alert engine agree; distinct from
# the tracker's reachability gate below, which is a tighter same-vehicle test.
IMPLAUSIBLE_SPEED_KMH = float(os.getenv("CLONE_MAX_SPEED_KMH", "150"))

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
            models.DetectionEvent.track_uuid.isnot(None),
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
            "source_system": s.source_system,
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
    operational = models.DetectionEvent.track_uuid.isnot(None)
    total = (
        db.query(func.count(models.DetectionEvent.id)).filter(operational).scalar()
    )
    anpr = (
        db.query(func.count(models.DetectionEvent.id))
        .filter(operational, models.DetectionEvent.event_type == "anpr")
        .scalar()
    )
    plates = (
        db.query(func.count(func.distinct(models.DetectionEvent.plate_norm)))
        .filter(operational, models.DetectionEvent.plate_norm.isnot(None))
        .scalar()
    )
    cams = (
        db.query(func.count(func.distinct(models.DetectionEvent.camera_id)))
        .filter(operational)
        .scalar()
    )
    return {
        "total": total,
        "anpr": anpr,
        "unique_plates": plates,
        "active_cameras": cams,
    }
