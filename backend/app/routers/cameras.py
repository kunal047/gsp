from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import crud, models, schemas
from ..db import get_db
from ..rbac import Principal, audit, principal, require_actor

router = APIRouter(prefix="/api", tags=["cameras"])


@router.get("/cameras", response_model=List[schemas.CameraOut])
def list_cameras(
    department: Optional[str] = None,
    health_status: Optional[str] = None,
    camera_type: Optional[str] = None,
    city: Optional[str] = None,
    analytics_enabled: Optional[bool] = None,
    source_system: Optional[str] = None,
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
    if source_system:
        query = query.filter(models.Camera.source_system == source_system)
    if q:
        like = f"%{q}%"
        query = query.filter(
            models.Camera.name.ilike(like) | models.Camera.camera_id.ilike(like)
        )
    return query.order_by(models.Camera.camera_id).all()


@router.get("/cameras/{camera_id}", response_model=schemas.CameraOut)
def get_camera(
    camera_id: str,
    db: Session = Depends(get_db),
    p: Principal = Depends(principal),
):
    query = db.query(models.Camera).filter(models.Camera.camera_id == camera_id)
    if p.role == "district_officer" and p.scope:
        query = query.filter(models.Camera.city == p.scope)
    cam = query.first()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    return cam


@router.patch("/cameras/{camera_id}/lifecycle", response_model=schemas.CameraOut)
def update_camera_lifecycle(
    camera_id: str,
    data: schemas.CameraLifecycleUpdate,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_actor),
):
    query = db.query(models.Camera).filter(models.Camera.camera_id == camera_id)
    if p.role == "district_officer" and p.scope:
        query = query.filter(models.Camera.city == p.scope)
    camera = query.first()
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    for field, value in data.model_dump().items():
        setattr(camera, field, value)
    db.commit()
    db.refresh(camera)
    audit(db, p, "registry.lifecycle_update", f"{camera_id} · {camera.maintenance_status}")
    return camera


@router.post("/cameras", response_model=schemas.CameraOut, status_code=201)
def create_camera(
    data: schemas.CameraCreate,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_actor),
):
    if p.role == "district_officer" and p.scope and data.city != p.scope:
        raise HTTPException(status_code=403, detail="camera is outside district scope")
    if (
        db.query(models.Camera)
        .filter(models.Camera.camera_id == data.camera_id)
        .first()
    ):
        raise HTTPException(status_code=409, detail="camera_id already exists")
    cam = crud.create_camera(db, data)
    audit(db, p, "registry.camera_create", f"{cam.camera_id} · {cam.city or 'Unknown'}")
    return cam


@router.post("/cameras/bulk", response_model=schemas.BulkResult)
def bulk_import(
    rows: List[schemas.CameraCreate],
    db: Session = Depends(get_db),
    p: Principal = Depends(require_actor),
):
    if p.role == "district_officer" and p.scope:
        outside = [r.camera_id for r in rows if r.city != p.scope]
        if outside:
            raise HTTPException(
                status_code=403,
                detail=f"{len(outside)} camera(s) are outside district scope",
            )
    result = crud.upsert_missing(db, [r.model_dump() for r in rows])
    audit(
        db,
        p,
        "registry.bulk_import",
        f"{result.inserted} inserted · {result.skipped} skipped · {result.total} submitted",
    )
    return result


@router.post("/ingest/live", response_model=schemas.BulkResult)
def ingest_live(
    db: Session = Depends(get_db),
    p: Principal = Depends(require_actor),
):
    """Onboard the real government feed (live.corp8.cloud) via adapter."""
    from ..live_ingest import get_mapped_live

    rows = get_mapped_live()
    result = crud.upsert_missing(db, rows)
    audit(db, p, "registry.live_onboard", f"{result.inserted} inserted")
    return result


@router.get("/adapters")
def adapters(db: Session = Depends(get_db)):
    """Configured federation adapters plus their persisted camera coverage."""
    from ..adapters import adapter_catalog

    counts = dict(
        db.query(models.Camera.source_system, func.count(models.Camera.id))
        .group_by(models.Camera.source_system)
        .all()
    )
    return [
        {**item, "camera_count": counts.get(item["source_system"], 0)}
        for item in adapter_catalog()
    ]


@router.post("/ingest/adapters")
def ingest_adapters(p: Principal = Depends(require_actor)):
    """Discover and onboard every configured source-system adapter."""
    from ..main import health, ingest_cameras

    ingest_cameras()
    return health()


@router.delete("/cameras/{camera_id}", status_code=204)
def delete_camera(
    camera_id: str,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_actor),
):
    query = db.query(models.Camera).filter(models.Camera.camera_id == camera_id)
    if p.role == "district_officer" and p.scope:
        query = query.filter(models.Camera.city == p.scope)
    cam = query.first()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    db.delete(cam)
    db.commit()
    audit(db, p, "registry.camera_delete", camera_id)


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
        "by_source_system": group(models.Camera.source_system),
        "analytics_enabled": analytics,
    }


@router.get("/gap-analysis")
def gap_analysis(
    db: Session = Depends(get_db),
    p: Principal = Depends(principal),
):
    """Coverage & health gap report from the real registry (Model 1)."""
    from collections import defaultdict

    query = db.query(models.Camera)
    if p.role == "district_officer" and p.scope:
        query = query.filter(models.Camera.city == p.scope)
    cams = query.all()
    now = datetime.now(timezone.utc)
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
    maintenance_due = [
        c for c in cams
        if c.maintenance_status in {"due", "overdue"}
        or (c.next_service_at is not None and c.next_service_at <= now)
    ]
    end_of_life = [c for c in cams if c.eol_at is not None and c.eol_at <= now]
    incomplete_assets = [
        c for c in cams
        if not c.installed_at or not c.make or not c.model or not c.resolution
    ]
    return {
        "total": total,
        "online": online,
        "offline": len(offline_cams),
        "coverage_pct": round(100 * online / total) if total else 0,
        "thin_coverage": [d["city"] for d in districts if d["total"] <= 1],
        "districts": districts,
        "offline_cameras": offline_cams,
        "maintenance_due": len(maintenance_due),
        "end_of_life": len(end_of_life),
        "incomplete_asset_records": len(incomplete_assets),
        "lifecycle_completeness_pct": round(
            100 * (total - len(incomplete_assets)) / total
        ) if total else 0,
        "maintenance_cameras": [
            {
                "camera_id": c.camera_id,
                "name": c.name,
                "city": c.city,
                "maintenance_status": c.maintenance_status,
                "next_service_at": c.next_service_at,
                "eol_at": c.eol_at,
            }
            for c in maintenance_due
        ],
    }


@router.get("/departments")
def departments(db: Session = Depends(get_db)):
    rows = (
        db.query(models.Camera.department, models.Camera.department_full)
        .distinct()
        .all()
    )
    return [{"code": r[0], "full": r[1]} for r in rows if r[0]]
