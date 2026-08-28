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

# Per-camera traffic baseline cache, hydrated from CameraBaseline on startup and
# persisted back periodically so it survives restarts.
class _Baseline:
    __slots__ = ("ema", "count", "peak", "override", "since_persist")

    def __init__(self, ema=0.0, count=0, peak=0, override=None):
        self.ema = ema
        self.count = count
        self.peak = peak
        self.override = override          # operator-pinned congestion threshold
        self.since_persist = 0


_baselines: dict[str, _Baseline] = {}
_dirty: set[str] = set()          # camera_ids with unpersisted baseline changes
_flush_lock = Lock()


def _now():
    return datetime.now(timezone.utc)


def load_baselines(db: Session) -> int:
    """Hydrate the in-memory baselines from the database at startup."""
    _baselines.clear()
    for row in db.query(models.CameraBaseline).all():
        _baselines[row.camera_id] = _Baseline(
            ema=row.ema, count=row.sample_count, peak=row.peak,
            override=row.congestion_threshold,
        )
    return len(_baselines)


def _persist_baseline(db: Session, cid: str, b: _Baseline):
    row = (
        db.query(models.CameraBaseline)
        .filter(models.CameraBaseline.camera_id == cid)
        .first()
    )
    if row is None:
        row = models.CameraBaseline(camera_id=cid)
        db.add(row)
    row.ema = round(b.ema, 3)
    row.sample_count = b.count
    row.peak = b.peak
    row.congestion_threshold = b.override
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
    for cid, b in _baselines.items():
        out.append({
            "camera_id": cid,
            "baseline": round(b.ema, 1),
            "samples": b.count,
            "peak": b.peak,
            "warmed": b.count >= WARMUP_SAMPLES,
            "congestion_threshold": congestion_threshold(cid),
            "override": b.override,
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

    # Surge = a real spike above the learned baseline. Held off until the camera
    # is warmed so a freshly-loaded baseline can't trigger a phantom surge.
    if warmed and prev is not None and vehicle_count >= max(
        SURGE_FLOOR, SURGE_FACTOR * prev
    ):
        a = _raise(
            db, "surge", camera,
            f"Traffic surge - {vehicle_count} vehicles (baseline ~{prev:.0f})",
            "medium", count=vehicle_count, event_ts=event_ts, time_source=time_source,
        )
        if a:
            created.append(a)

    # Update the baseline in memory and mark it dirty. Persistence is batched by
    # a background flusher (flush_dirty) so the hot ingest path does NO DB writes.
    b.ema = float(vehicle_count) if prev is None else (
        EMA_ALPHA * vehicle_count + (1 - EMA_ALPHA) * b.ema
    )
    b.count += 1
    b.peak = max(b.peak, vehicle_count)
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
            row.ema = round(b.ema, 3)
            row.sample_count = b.count
            row.peak = b.peak
            row.congestion_threshold = b.override
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
