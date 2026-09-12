"""Real, feed-derived alert engine.

Alerts are computed from ACTUAL analytics on the 31 live camera feeds - no
external/mock databases:

  * congestion  - per-camera vehicle count exceeds a threshold
  * surge       - vehicle count spikes above a live per-camera baseline (EMA)
  * watchlist   - an OPERATOR-defined BOLO (vehicle type + colour, or plate)
                  matches a real detection

The VAHAN / eGujCop / AFIS connectors are intentionally NOT faked here; those
are real integrations for deployment (documented in the HLD) and cannot be
queried from this environment.
"""
import json
import math
import os
from datetime import datetime, timedelta, timezone
from threading import Lock

from sqlalchemy.orm import Session

from . import models

CONGESTION_MIN = int(os.getenv("CONGESTION_MIN", "10"))  # absolute floor
# Adaptive congestion: once warmed, a camera is congested at
# max(CONGESTION_MIN, baseline * CONGESTION_BASELINE_FACTOR), so a busy junction
# doesn't alert at its normal load and a quiet lane still trips at the floor.
CONGESTION_BASELINE_FACTOR = float(os.getenv("CONGESTION_BASELINE_FACTOR", "1.6"))
SURGE_FLOOR = int(os.getenv("SURGE_FLOOR", "6"))
SURGE_FACTOR = float(os.getenv("SURGE_FACTOR", "1.8"))
EMA_ALPHA = float(os.getenv("EMA_ALPHA", "0.3"))
# Frames a camera must observe before adaptive congestion / surge may fire; until
# then the baseline is still forming and only the absolute floor applies. Stops
# cold-start false alerts after a restart.
WARMUP_SAMPLES = int(os.getenv("BASELINE_WARMUP_SAMPLES", "15"))
PERSIST_EVERY = int(os.getenv("BASELINE_PERSIST_EVERY", "20"))
THROTTLE_SECONDS = int(os.getenv("ALERT_THROTTLE", "90"))
ATTRIBUTE_MIN_CONFIDENCE = float(os.getenv("ATTRIBUTE_MIN_CONFIDENCE", "0.65"))
ATTRIBUTE_MIN_CLASS_CONFIDENCE = float(
    os.getenv("ATTRIBUTE_MIN_CLASS_CONFIDENCE", "0.75")
)
ATTRIBUTE_MIN_COLOR_CONFIDENCE = float(
    os.getenv("ATTRIBUTE_MIN_COLOR_CONFIDENCE", "0.67")
)
PLATE_MIN_CONFIDENCE = float(os.getenv("PLATE_MATCH_MIN_CONFIDENCE", "0.55"))
HEAVY_VEHICLE_CLASS_CONFIDENCE = float(
    os.getenv("HEAVY_VEHICLE_CLASS_CONFIDENCE", "0.85")
)

# Time-of-day dayparts: surge is judged against the SAME daypart's baseline so a
# normal morning rush is not read as a spike against the flat 24h average.
DAYPARTS = ["night", "morning", "afternoon", "evening"]  # 0-6, 6-12, 12-18, 18-24


def _bucket_of(dt) -> int:
    return (dt or _now()).hour // 6


# Per-camera traffic baseline cache, hydrated from CameraBaseline on startup and
# persisted back periodically so it survives restarts.
class _Baseline:
    __slots__ = ("ema", "count", "peak", "override", "since_persist", "buckets")

    def __init__(self, ema=0.0, count=0, peak=0, override=None, buckets=None):
        self.ema = ema
        self.count = count
        self.peak = peak
        self.override = override          # operator-pinned congestion threshold
        self.since_persist = 0
        # per-daypart EMAs: {bucket_int: {"ema": float, "count": int}}
        self.buckets = buckets or {}


_baselines: dict[str, _Baseline] = {}
_dirty: set[str] = set()          # camera_ids with unpersisted baseline changes
_flush_lock = Lock()
# Guards mutation/iteration of the baseline state dicts. FastAPI runs the sync
# ingest endpoints in a threadpool, so process_frame can run concurrently with
# the background flusher; without this, json.dumps iterating b.buckets while
# another thread inserts a daypart key raises "dict changed size during
# iteration". Held only around in-memory dict ops, never across a DB call.
_state_lock = Lock()


def _now():
    return datetime.now(timezone.utc)


def load_baselines(db: Session) -> int:
    """Hydrate the in-memory baselines from the database at startup."""
    _baselines.clear()
    for row in db.query(models.CameraBaseline).all():
        buckets = {}
        if getattr(row, "buckets", None):
            try:
                buckets = {int(k): v for k, v in json.loads(row.buckets).items()}
            except (ValueError, TypeError):
                buckets = {}
        _baselines[row.camera_id] = _Baseline(
            ema=row.ema, count=row.sample_count, peak=row.peak,
            override=row.congestion_threshold, buckets=buckets,
        )
    return len(_baselines)


def _snapshot_row(b: _Baseline) -> dict:
    """Consistent, serialized copy of a baseline's persistable fields, taken under
    the state lock so the daypart dict is never read mid-mutation."""
    with _state_lock:
        return {
            "ema": round(b.ema, 3),
            "sample_count": b.count,
            "peak": b.peak,
            "congestion_threshold": b.override,
            "buckets": (
                json.dumps({str(k): v for k, v in b.buckets.items()})
                if b.buckets else None
            ),
        }


def _apply_row(row: models.CameraBaseline, snap: dict):
    row.ema = snap["ema"]
    row.sample_count = snap["sample_count"]
    row.peak = snap["peak"]
    row.congestion_threshold = snap["congestion_threshold"]
    row.buckets = snap["buckets"]


def _persist_baseline(db: Session, cid: str, b: _Baseline):
    row = (
        db.query(models.CameraBaseline)
        .filter(models.CameraBaseline.camera_id == cid)
        .first()
    )
    if row is None:
        row = models.CameraBaseline(camera_id=cid)
        db.add(row)
    _apply_row(row, _snapshot_row(b))
    db.commit()


def congestion_threshold(cid: str) -> int:
    """The camera's effective congestion cut-off: operator override, else the
    adaptive baseline once warmed, else the absolute floor."""
    b = _baselines.get(cid)
    if b is None:
        return CONGESTION_MIN
    if b.override is not None:
        return b.override
    if b.count >= WARMUP_SAMPLES:
        return max(CONGESTION_MIN, round(b.ema * CONGESTION_BASELINE_FACTOR))
    return CONGESTION_MIN


def baseline_snapshot() -> list[dict]:
    """Current calibration state, for the ops/alerts API."""
    out = []
    now_bucket = _bucket_of(None)
    for cid, b in list(_baselines.items()):
        with _state_lock:
            bstate = dict(b.buckets.get(now_bucket) or {})
        out.append({
            "camera_id": cid,
            "baseline": round(b.ema, 1),
            "samples": b.count,
            "peak": b.peak,
            "warmed": b.count >= WARMUP_SAMPLES,
            "congestion_threshold": congestion_threshold(cid),
            "override": b.override,
            "daypart": DAYPARTS[now_bucket],
            "daypart_baseline": round(bstate.get("ema", 0.0), 1),
            "daypart_warmed": bstate.get("count", 0) >= WARMUP_SAMPLES,
        })
    return sorted(out, key=lambda r: r["camera_id"])


def forget_baseline(db: Session, cid: str):
    """Drop a camera's baseline from memory and the DB (called on camera delete)."""
    _baselines.pop(cid, None)
    with _flush_lock:
        _dirty.discard(cid)
    db.query(models.CameraBaseline).filter(
        models.CameraBaseline.camera_id == cid
    ).delete()


def set_congestion_override(db: Session, cid: str, threshold: int | None):
    b = _baselines.setdefault(cid, _Baseline())
    b.override = threshold
    _persist_baseline(db, cid, b)
    return congestion_threshold(cid)


def _throttled(db: Session, kind: str, camera_id: str) -> bool:
    recent = (
        db.query(models.Alert)
        .filter(
            models.Alert.kind == kind,
            models.Alert.camera_id == camera_id,
            models.Alert.ingested_at
            >= _now() - timedelta(seconds=THROTTLE_SECONDS),
        )
        .first()
    )
    return recent is not None


def _raise(
    db,
    kind,
    camera,
    reason,
    severity,
    count=None,
    det=None,
    wl_id=None,
    event_ts=None,
    time_source="ingest",
):
    if _throttled(db, kind, camera.camera_id):
        return None
    a = models.Alert(
        kind=kind,
        watchlist_id=wl_id,
        detection_id=det.id if det else None,
        camera_id=camera.camera_id,
        camera_name=camera.name,
        city=camera.city,
        source_system=camera.source_system,
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
        ts=det.ts if det else event_ts,
        time_source=det.time_source if det else time_source,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def process_frame(
    db: Session,
    camera,
    vehicle_count: int,
    event_ts=None,
    time_source="ingest",
):
    """Congestion + surge alerts from a real per-frame vehicle count, calibrated
    against a persisted per-camera baseline."""
    cid = camera.camera_id
    b = _baselines.setdefault(cid, _Baseline())
    prev = b.ema if b.count > 0 else None
    warmed = b.count >= WARMUP_SAMPLES
    threshold = congestion_threshold(cid)
    created = []

    if vehicle_count >= threshold:
        sev = "high" if vehicle_count >= threshold + 4 else "medium"
        a = _raise(
            db, "congestion", camera,
            f"Congestion - {vehicle_count} vehicles (threshold {threshold})",
            sev, count=vehicle_count, event_ts=event_ts, time_source=time_source,
        )
        if a:
            created.append(a)

    # Surge = a real spike above the learned baseline. Judged against the SAME
    # daypart's baseline once that daypart is warm (so a normal morning rush is
    # not a spike vs the flat 24h average); falls back to the overall baseline.
    bucket = _bucket_of(event_ts)
    with _state_lock:
        bstate = b.buckets.get(bucket)
        bucket_ema = bstate["ema"] if bstate else 0.0
        bucket_count = bstate["count"] if bstate else 0
    if bucket_count >= WARMUP_SAMPLES:
        surge_base, surge_label = bucket_ema, f"{DAYPARTS[bucket]} baseline"
    elif warmed and prev is not None:
        surge_base, surge_label = prev, "baseline"
    else:
        surge_base, surge_label = None, None
    if surge_base is not None and vehicle_count >= max(SURGE_FLOOR, SURGE_FACTOR * surge_base):
        a = _raise(
            db, "surge", camera,
            f"Traffic surge - {vehicle_count} vehicles ({surge_label} ~{surge_base:.0f})",
            "medium", count=vehicle_count, event_ts=event_ts, time_source=time_source,
        )
        if a:
            created.append(a)

    # Update the overall + daypart baselines in memory and mark dirty. Persistence
    # is batched by a background flusher so the hot ingest path does NO DB writes.
    # Mutations are under _state_lock so a concurrent flush never iterates a dict
    # that is being resized.
    with _state_lock:
        b.ema = float(vehicle_count) if prev is None else (
            EMA_ALPHA * vehicle_count + (1 - EMA_ALPHA) * b.ema
        )
        b.count += 1
        b.peak = max(b.peak, vehicle_count)
        bstate = b.buckets.setdefault(bucket, {"ema": 0.0, "count": 0})
        bstate["ema"] = float(vehicle_count) if bstate["count"] == 0 else (
            EMA_ALPHA * vehicle_count + (1 - EMA_ALPHA) * bstate["ema"]
        )
        bstate["count"] += 1
    _dirty.add(cid)
    return created


def flush_dirty(db: Session) -> int:
    """Write all baselines changed since the last flush in ONE transaction.
    Called on a timer by a background thread; keeps DB writes off the hot path."""
    with _flush_lock:
        cids = list(_dirty)
        _dirty.clear()
    if not cids:
        return 0
    try:
        for cid in cids:
            b = _baselines.get(cid)
            if b is None:
                continue
            row = (
                db.query(models.CameraBaseline)
                .filter(models.CameraBaseline.camera_id == cid)
                .first()
            )
            if row is None:
                row = models.CameraBaseline(camera_id=cid)
                db.add(row)
            _apply_row(row, _snapshot_row(b))
        db.commit()
        return len(cids)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        with _flush_lock:
            _dirty.update(cids)  # retry on the next tick
        print(f"[alerts] baseline flush failed: {exc}")
        return 0


# --- Representative watchlist database (challenge Step 3) ------------------
# Synthetic records of interest - NOT live government data. Vehicle entries
# (plate / attribute) match live detections now; person entries need face
# recognition (roadmap) and sit in the DB as complete structure.
SEED_WATCHLIST = [
    {
        "category": "stolen_vehicle", "kind": "plate", "plate_norm": "GJ01AB1234",
        "label": "Maruti Swift (white) · GJ 01 AB 1234", "case_ref": "FIR 214/2026",
        "reason": "Stolen vehicle", "severity": "high", "min_confidence": 0.55,
        "min_track_hits": 3,
    },
    {
        "category": "blacklisted_vehicle", "kind": "attribute",
        "vehicle_type": "truck", "color": "white",
        "label": "White truck · suspected contraband", "case_ref": "NCB/2026/07",
        "reason": "Blacklisted - contraband movement", "severity": "high",
        "min_confidence": 0.72, "min_track_hits": 4,
    },
    {
        "category": "suspect_vehicle", "kind": "attribute",
        "vehicle_type": "car", "color": "red",
        "label": "Red car · hit & run suspect", "case_ref": "FIR 88/2026",
        "reason": "Suspect vehicle (Navrangpura PS)", "severity": "medium",
        "min_confidence": 0.68, "min_track_hits": 3,
    },
    {
        "category": "wanted_person", "kind": "person",
        "label": "Wanted suspect · face on record", "case_ref": "CID/2026/12",
        "reason": "Wanted - requires face recognition (roadmap)", "severity": "high",
    },
    {
        "category": "missing_person", "kind": "person",
        "label": "Missing minor · last seen Paldi", "case_ref": "MP/2026/33",
        "reason": "Missing person - requires face recognition (roadmap)",
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
    """Return (dimension, confidence) only for persistent, reliable tracks."""
    required_hits = item.min_track_hits or 3
    if (det.track_hits or 1) < required_hits:
        return None
    if item.kind == "plate":
        confidence = float(det.plate_confidence or 0.0)
        threshold = max(PLATE_MIN_CONFIDENCE, item.min_confidence or 0.0)
        if (
            det.plate_norm
            and item.plate_norm == det.plate_norm
            and confidence >= threshold
        ):
            return "plate", confidence
        return None
    if item.kind == "attribute":
        if item.vehicle_type and item.vehicle_type != det.vehicle_type:
            return None
        if item.color and item.color != det.color:
            return None
        if item.vehicle_type or item.color:
            detector_confidence = float(det.confidence or 0.0)
            class_confidence = float(det.class_confidence or 0.0)
            color_confidence = float(det.color_confidence or 0.0)
            required_class = (
                HEAVY_VEHICLE_CLASS_CONFIDENCE
                if det.vehicle_type in {"bus", "truck", "auto_rickshaw"}
                else ATTRIBUTE_MIN_CLASS_CONFIDENCE
            )
            threshold = max(ATTRIBUTE_MIN_CONFIDENCE, item.min_confidence or 0.0)
            if (
                detector_confidence < threshold
                or class_confidence < required_class
                or (item.color and color_confidence < ATTRIBUTE_MIN_COLOR_CONFIDENCE)
            ):
                return None
            confidence = min(
                detector_confidence,
                class_confidence,
                color_confidence if item.color else 1.0,
            )
            return "attribute", confidence
    return None  # person entries match via face recognition (roadmap)


# --- Cloned / duplicate-plate detection (impossible movement) --------------
# The same plate seen at two cameras too far apart to reach in the elapsed time
# is physically impossible: either a serious ANPR misread or a cloned/duplicate
# plate. This is a real-time federation check across ALL source systems.
CLONE_MAX_SPEED_KMH = float(os.getenv("CLONE_MAX_SPEED_KMH", "150"))
CLONE_MIN_GAP_S = int(os.getenv("CLONE_MIN_GAP_S", "20"))
CLONE_MIN_KM = float(os.getenv("CLONE_MIN_KM", "0.5"))
CLONE_LOOKBACK_S = int(os.getenv("CLONE_LOOKBACK_S", "3600"))
# Controlled test rigs publish one looping clip on several "cameras", so the same
# plate appears at multiple locations by construction - meaningless for a
# cross-camera speed check. Exclude those source systems; real feeds are checked.
CLONE_EXCLUDE_SYSTEMS = {
    s for s in os.getenv("CLONE_EXCLUDE_SOURCE_SYSTEMS", "Independent RTSP System").split("|") if s
}


def _haversine_km(a_lat, a_lng, b_lat, b_lng):
    dlat = math.radians(b_lat - a_lat)
    dlng = math.radians(b_lng - a_lng)
    h = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(a_lat)) * math.cos(math.radians(b_lat))
        * math.sin(dlng / 2) ** 2
    )
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def check_impossible_movement(db: Session, ev: models.DetectionEvent):
    """Raise a cloned-plate alert if this plate was just read at a DIFFERENT
    camera too far away to have been reached in the elapsed time."""
    if (
        ev.event_type != "anpr"
        or not ev.plate_norm
        or ev.lat is None
        or ev.lng is None
        or ev.ts is None
        or ev.source_system in CLONE_EXCLUDE_SYSTEMS
    ):
        return None
    prior = (
        db.query(models.DetectionEvent)
        .filter(
            models.DetectionEvent.plate_norm == ev.plate_norm,
            models.DetectionEvent.camera_id != ev.camera_id,
            models.DetectionEvent.id != ev.id,
            models.DetectionEvent.lat.isnot(None),
            models.DetectionEvent.ts >= ev.ts - timedelta(seconds=CLONE_LOOKBACK_S),
            models.DetectionEvent.ts <= ev.ts,
        )
        .order_by(models.DetectionEvent.ts.desc())
        .first()
    )
    if (
        not prior
        or prior.lat is None
        or prior.ts is None
        or prior.source_system in CLONE_EXCLUDE_SYSTEMS
    ):
        return None
    gap = abs((ev.ts - prior.ts).total_seconds())
    if gap < CLONE_MIN_GAP_S:
        return None  # near-simultaneous: clock skew / overlapping FOV, ambiguous
    dist = _haversine_km(prior.lat, prior.lng, ev.lat, ev.lng)
    if dist < CLONE_MIN_KM:
        return None
    speed = dist / (gap / 3600.0)
    if speed <= CLONE_MAX_SPEED_KMH:
        return None
    # Throttle per PLATE at this camera, not camera-wide: two different cloned
    # plates hitting the same busy ANPR camera must both alert.
    recent_clone = (
        db.query(models.Alert)
        .filter(
            models.Alert.kind == "cloned_plate",
            models.Alert.camera_id == ev.camera_id,
            models.Alert.plate == ev.plate,
            models.Alert.ingested_at >= _now() - timedelta(seconds=THROTTLE_SECONDS),
        )
        .first()
    )
    if recent_clone is not None:
        return None
    cross = prior.source_system != ev.source_system
    reason = (
        f"Plate {ev.plate} at {prior.camera_name} then {ev.camera_name} - "
        f"{dist:.1f} km in {gap:.0f}s (~{speed:.0f} km/h), physically impossible - "
        f"possible cloned/duplicate plate" + (" (across systems)" if cross else "")
    )
    alert = models.Alert(
        kind="cloned_plate",
        detection_id=ev.id,
        camera_id=ev.camera_id,
        camera_name=ev.camera_name,
        city=ev.city,
        source_system=ev.source_system,
        lat=ev.lat,
        lng=ev.lng,
        plate=ev.plate,
        vehicle_type=ev.vehicle_type,
        color=ev.color,
        reason=reason,
        source="Federation Analytics",
        severity="high",
        snapshot=ev.snapshot,
        ts=ev.ts,
        time_source=ev.time_source,
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert


def check_watchlist(db: Session, det: models.DetectionEvent):
    created = []
    items = (
        db.query(models.Watchlist)
        .filter(models.Watchlist.active.is_(True))
        .all()
    )
    for item in items:
        match = _wl_matches(item, det)
        if not match:
            continue
        matched_on, match_confidence = match
        recent = (
            db.query(models.Alert)
            .filter(
                models.Alert.watchlist_id == item.id,
                models.Alert.camera_id == det.camera_id,
                models.Alert.ingested_at
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
            match_confidence=match_confidence,
            detection_id=det.id,
            camera_id=det.camera_id,
            camera_name=det.camera_name,
            city=det.city,
            source_system=det.source_system,
            lat=det.lat,
            lng=det.lng,
            plate=det.plate,
            vehicle_type=det.vehicle_type,
            color=det.color,
            reason=f"{item.label} - {item.reason}",
            source="Watchlist match",
            severity=item.severity,
            snapshot=det.snapshot,
            ts=det.ts,
            time_source=det.time_source,
        )
        db.add(a)
        db.commit()
        db.refresh(a)
        created.append(a)
    return created
