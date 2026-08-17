from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import crud, models, schemas
from ..db import get_db
from ..rbac import Principal, principal

router = APIRouter(prefix="/api", tags=["cameras"])


@router.get("/cameras", response_model=List[schemas.CameraOut])
def list_cameras(
    department: Optional[str] = None,
    health_status: Optional[str] = None,
    camera_type: Optional[str] = None,
    city: Optional[str] = None,
    analytics_enabled: Optional[bool] = None,
    q: Optional[str] = None,
    db: Session = Depends(get_db),
    p: Principal = Depends(principal),
):
    query = db.query(models.Camera)
    # RBAC: a district officer only sees cameras in their district.
    if p.role == "district_officer" and p.scope:
        query = query.filter(models.Camera.city == p.scope)
    if department:
        query = query.filter(models.Camera.department == department)
    if health_status:
        query = query.filter(models.Camera.health_status == health_status)
    if camera_type:
        query = query.filter(models.Camera.camera_type == camera_type)
    if city:
        query = query.filter(models.Camera.city == city)
    if analytics_enabled is not None:
        query = query.filter(models.Camera.analytics_enabled == analytics_enabled)
    if q:
        like = f"%{q}%"
        query = query.filter(
            models.Camera.name.ilike(like) | models.Camera.camera_id.ilike(like)
        )
    return query.order_by(models.Camera.camera_id).all()


@router.get("/cameras/{camera_id}", response_model=schemas.CameraOut)
def get_camera(camera_id: str, db: Session = Depends(get_db)):
    cam = (
        db.query(models.Camera)
        .filter(models.Camera.camera_id == camera_id)
        .first()
    )
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    return cam


@router.post("/cameras", response_model=schemas.CameraOut, status_code=201)
def create_camera(data: schemas.CameraCreate, db: Session = Depends(get_db)):
    if (
        db.query(models.Camera)
        .filter(models.Camera.camera_id == data.camera_id)
        .first()
    ):
        raise HTTPException(status_code=409, detail="camera_id already exists")
    return crud.create_camera(db, data)


@router.post("/cameras/bulk", response_model=schemas.BulkResult)
def bulk_import(rows: List[schemas.CameraCreate], db: Session = Depends(get_db)):
    return crud.upsert_missing(db, [r.model_dump() for r in rows])


@router.post("/ingest/live", response_model=schemas.BulkResult)
def ingest_live(db: Session = Depends(get_db)):
    """Onboard the real government feed (live.sentinelgujarat.in) via adapter."""
    from ..live_ingest import get_mapped_live

    rows = get_mapped_live()
    return crud.upsert_missing(db, rows)


@router.delete("/cameras/{camera_id}", status_code=204)
def delete_camera(camera_id: str, db: Session = Depends(get_db)):
    cam = (
        db.query(models.Camera)
        .filter(models.Camera.camera_id == camera_id)
        .first()
    )
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    db.delete(cam)
    db.commit()


@router.get("/stats")
def stats(
    db: Session = Depends(get_db), p: Principal = Depends(principal)
):
    # RBAC: district officers see stats for their district only.
    scope = (
        p.scope if p.role == "district_officer" and p.scope else None
    )

    def base():
        q = db.query(models.Camera)
        return q.filter(models.Camera.city == scope) if scope else q

    def group(col):
        q = db.query(col, func.count())
        if scope:
            q = q.filter(models.Camera.city == scope)
        return {k: v for k, v in q.group_by(col).all()}

    total = base().count()
    analytics = base().filter(models.Camera.analytics_enabled.is_(True)).count()
    return {
        "total": total,
        "by_department": group(models.Camera.department),
        "by_status": group(models.Camera.health_status),
        "by_type": group(models.Camera.camera_type),
        "by_city": group(models.Camera.city),
        "analytics_enabled": analytics,
    }


@router.get("/gap-analysis")
def gap_analysis(db: Session = Depends(get_db)):
    """Coverage & health gap report from the real registry (Model 1)."""
    from collections import defaultdict

    cams = db.query(models.Camera).all()
    by = defaultdict(lambda: {"total": 0, "online": 0, "degraded": 0, "offline": 0})
    for c in cams:
        d = by[c.city or "Unknown"]
        d["total"] += 1
        d[c.health_status] = d.get(c.health_status, 0) + 1
    districts = sorted(
        [{"city": k, **v} for k, v in by.items()],
        key=lambda x: x["total"],
        reverse=True,
    )
    total = len(cams)
    online = sum(1 for c in cams if c.health_status == "online")
    offline_cams = [
        {"camera_id": c.camera_id, "name": c.name, "city": c.city, "site": c.site}
        for c in cams
        if c.health_status == "offline"
    ]
    return {
        "total": total,
        "online": online,
        "offline": len(offline_cams),
        "coverage_pct": round(100 * online / total) if total else 0,
        "thin_coverage": [d["city"] for d in districts if d["total"] <= 1],
        "districts": districts,
        "offline_cameras": offline_cams,
    }


@router.get("/departments")
def departments(db: Session = Depends(get_db)):
    rows = (
        db.query(models.Camera.department, models.Camera.department_full)
        .distinct()
        .all()
    )
    return [{"code": r[0], "full": r[1]} for r in rows if r[0]]
