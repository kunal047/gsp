from datetime import timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import integrations, models
from ..db import get_db
from ..rbac import Principal, audit, principal, require_actor

router = APIRouter(prefix="/api", tags=["alerts"])


@router.get("/alerts/baselines")
def alert_baselines(
    db: Session = Depends(get_db), p: Principal = Depends(principal)
):
    """Live alert calibration: the learned per-camera traffic baseline, sample
    count, warm-up state and effective congestion threshold."""
    rows = integrations.baseline_snapshot()
    if p.role == "district_officer" and p.scope:
        scoped = {
            c.camera_id
            for c in db.query(models.Camera.camera_id)
            .filter(models.Camera.city == p.scope)
            .all()
        }
        rows = [r for r in rows if r["camera_id"] in scoped]
    return {
        "warmup_samples": integrations.WARMUP_SAMPLES,
        "congestion_floor": integrations.CONGESTION_MIN,
        "baseline_factor": integrations.CONGESTION_BASELINE_FACTOR,
        "cameras": rows,
    }


@router.put("/alerts/baselines/{camera_id}/threshold")
def set_congestion_threshold(
    camera_id: str,
    body: dict,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_actor),
):
    """Operator override of a camera's congestion threshold (null = adaptive)."""
    cam = (
        db.query(models.Camera)
        .filter(models.Camera.camera_id == camera_id)
        .first()
    )
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    if p.role == "district_officer" and p.scope and cam.city != p.scope:
        raise HTTPException(status_code=403, detail="camera is outside district scope")
    raw = body.get("threshold")
    threshold = None if raw in (None, "", "auto") else int(raw)
    if threshold is not None and threshold < 1:
        raise HTTPException(status_code=422, detail="threshold must be >= 1")
    effective = integrations.set_congestion_override(db, camera_id, threshold)
    audit(db, p, "alerts.threshold_override",
          f"{camera_id} · {'auto' if threshold is None else threshold}")
    return {"camera_id": camera_id, "override": threshold, "effective_threshold": effective}


def _operational_alerts(db: Session):
    tracked_ids = select(models.DetectionEvent.id).where(
        models.DetectionEvent.track_uuid.isnot(None)
    )
    return db.query(models.Alert).filter(
        or_(
            models.Alert.kind == "feed_offline",
            models.Alert.time_source != "ingest",
            models.Alert.detection_id.in_(tracked_ids),
        )
    )


@router.get("/alerts")
def list_alerts(
    limit: int = Query(50, le=500),
    since_id: Optional[int] = None,
    acknowledged: Optional[bool] = None,
    db: Session = Depends(get_db),
):
    q = _operational_alerts(db)
    if since_id:
        q = q.filter(models.Alert.id > since_id)
    if acknowledged is not None:
        q = q.filter(models.Alert.acknowledged.is_(acknowledged))
    rows = q.order_by(models.Alert.id.desc()).limit(limit).all()
    return [
        {
            "id": a.id,
            "kind": a.kind,
            "watchlist_category": a.watchlist_category,
            "case_ref": a.case_ref,
            "matched_on": a.matched_on,
            "match_confidence": a.match_confidence,
            "detection_id": a.detection_id,
            "camera_id": a.camera_id,
            "camera_name": a.camera_name,
            "city": a.city,
            "lat": a.lat,
            "lng": a.lng,
            "plate": a.plate,
            "vehicle_type": a.vehicle_type,
            "color": a.color,
            "vehicle_count": a.vehicle_count,
            "reason": a.reason,
            "source": a.source,
            "source_system": a.source_system,
            "severity": a.severity,
            "snapshot": a.snapshot,
            "acknowledged": a.acknowledged,
            "ts": a.ts,
            "ingested_at": a.ingested_at,
            "time_source": a.time_source,
        }
        for a in rows
    ]


@router.get("/alerts/stats")
def alert_stats(db: Session = Depends(get_db)):
    operational = _operational_alerts(db)
    total = operational.with_entities(func.count(models.Alert.id)).scalar()
    unack = (
        operational.with_entities(func.count(models.Alert.id))
        .filter(models.Alert.acknowledged.is_(False))
        .scalar()
    )
    return {"total": total, "unacknowledged": unack}


@router.get("/alerts/{alert_id}/evidence")
def alert_evidence(
    alert_id: int,
    window_minutes: int = Query(5, ge=1, le=60),
    db: Session = Depends(get_db),
):
    """Alert evidence plus nearby sightings from the same camera.

    The prototype retains event snapshots, not central video. Camera stream
    metadata is returned so the UI can also show the federated live feed.
    """
    alert = db.query(models.Alert).filter(models.Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="alert not found")
    camera = (
        db.query(models.Camera)
        .filter(models.Camera.camera_id == alert.camera_id)
        .first()
    )
    start = alert.ts - timedelta(minutes=window_minutes)
    end = alert.ts + timedelta(minutes=window_minutes)
    detections = (
        db.query(models.DetectionEvent)
        .filter(
            models.DetectionEvent.camera_id == alert.camera_id,
            models.DetectionEvent.ts >= start,
            models.DetectionEvent.ts <= end,
        )
        .order_by(models.DetectionEvent.ts.asc())
        .limit(200)
        .all()
    )
    return {
        "alert_id": alert.id,
        "alert_ts": alert.ts,
        "window_minutes": window_minutes,
        "camera": {
            "camera_id": camera.camera_id,
            "name": camera.name,
            "stream_url": camera.stream_url,
            "container": camera.container,
            "health_status": camera.health_status,
            "source_system": camera.source_system,
            "source_adapter": camera.source_adapter,
        } if camera else None,
        "timeline": [
            {
                "id": d.id,
                "ts": d.ts,
                "event_type": d.event_type,
                "plate": d.plate,
                "vehicle_type": d.vehicle_type,
                "color": d.color,
                "confidence": d.confidence,
                "track_id": d.track_id,
                "track_hits": d.track_hits,
                "class_confidence": d.class_confidence,
                "time_source": d.time_source,
                "direction": d.direction,
                "dwell_seconds": d.dwell_seconds,
                "stopped": d.stopped,
                "wrong_way": d.wrong_way,
                "snapshot": (
                    alert.snapshot
                    if d.id == alert.detection_id and alert.snapshot
                    else d.snapshot
                ),
                "is_alert_detection": d.id == alert.detection_id,
            }
            for d in detections
        ],
    }


@router.post("/alerts/{alert_id}/ack")
def ack_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_actor),
):
    a = db.query(models.Alert).filter(models.Alert.id == alert_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="alert not found")
    a.acknowledged = True
    db.commit()
    audit(db, p, "alert.ack", f"alert #{a.id} - {a.reason}")
    return {"id": a.id, "acknowledged": True}


def _wl_dict(w: models.Watchlist) -> dict:
    return {
        "id": w.id,
        "category": w.category,
        "label": w.label,
        "kind": w.kind,
        "plate_norm": w.plate_norm,
        "vehicle_type": w.vehicle_type,
        "color": w.color,
        "case_ref": w.case_ref,
        "reason": w.reason,
        "source": w.source,
        "severity": w.severity,
        "min_confidence": w.min_confidence,
        "min_track_hits": w.min_track_hits,
        "active": w.active,
    }


@router.get("/watchlist")
def list_watchlist(
    q: Optional[str] = None,
    category: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = db.query(models.Watchlist)
    if category:
        query = query.filter(models.Watchlist.category == category)
    if q:
        like = f"%{q}%"
        query = query.filter(
            models.Watchlist.label.ilike(like)
            | models.Watchlist.plate_norm.ilike(like)
            | models.Watchlist.case_ref.ilike(like)
        )
    return [_wl_dict(w) for w in query.order_by(models.Watchlist.id).all()]


@router.post("/watchlist")
def add_watchlist(
    item: dict,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_actor),
):
    plate = (item.get("plate_norm") or "").upper().replace(" ", "") or None
    kind = "plate" if plate else "attribute"
    label = item.get("label") or plate or (
        f"{item.get('color','')} {item.get('vehicle_type','')}".strip()
    )
    w = models.Watchlist(
        category=item.get("category", "suspect_vehicle"),
        label=label or "Watchlist entry",
        kind=kind,
        plate_norm=plate,
        vehicle_type=item.get("vehicle_type"),
        color=item.get("color"),
        case_ref=item.get("case_ref"),
        reason=item.get("reason", "Manual watchlist entry"),
        source="Representative dataset",
        severity=item.get("severity", "high"),
        min_confidence=float(item.get("min_confidence", 0.65)),
        min_track_hits=int(item.get("min_track_hits", 3)),
        active=True,
    )
    db.add(w)
    db.commit()
    db.refresh(w)
    audit(db, p, "watchlist.add", f"{w.category}: {w.label} ({w.case_ref})")
    return _wl_dict(w)


@router.delete("/watchlist/{wid}", status_code=204)
def del_watchlist(
    wid: int,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_actor),
):
    w = db.query(models.Watchlist).filter(models.Watchlist.id == wid).first()
    if not w:
        raise HTTPException(status_code=404, detail="watchlist entry not found")
    detail = f"{w.category}: {w.label} ({w.case_ref})"
    db.delete(w)
    db.commit()
    audit(db, p, "watchlist.delete", detail)
