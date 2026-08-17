from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models
from ..db import get_db
from ..rbac import Principal, audit, require_actor

router = APIRouter(prefix="/api", tags=["alerts"])


@router.get("/alerts")
def list_alerts(
    limit: int = Query(50, le=500),
    since_id: Optional[int] = None,
    acknowledged: Optional[bool] = None,
    db: Session = Depends(get_db),
):
    q = db.query(models.Alert)
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
            "severity": a.severity,
            "snapshot": a.snapshot,
            "acknowledged": a.acknowledged,
            "ts": a.ts,
        }
        for a in rows
    ]


@router.get("/alerts/stats")
def alert_stats(db: Session = Depends(get_db)):
    total = db.query(func.count(models.Alert.id)).scalar()
    unack = (
        db.query(func.count(models.Alert.id))
        .filter(models.Alert.acknowledged.is_(False))
        .scalar()
    )
    return {"total": total, "unacknowledged": unack}


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
    audit(db, p, "alert.ack", f"alert #{a.id} — {a.reason}")
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
        active=True,
    )
    db.add(w)
    db.commit()
    db.refresh(w)
    audit(db, p, "watchlist.add", f"{w.category}: {w.label} ({w.case_ref})")
    return _wl_dict(w)


@router.delete("/watchlist/{wid}", status_code=204)
def del_watchlist(wid: int, db: Session = Depends(get_db)):
    w = db.query(models.Watchlist).filter(models.Watchlist.id == wid).first()
    if w:
        db.delete(w)
        db.commit()
