"""Shared helpers for camera persistence."""
from typing import Optional

from geoalchemy2.elements import WKTElement
from sqlalchemy.orm import Session

from . import models, schemas


def _geom(lat: Optional[float], lng: Optional[float]):
    if lat is None or lng is None:
        return None
    return WKTElement(f"POINT({lng} {lat})", srid=4326)


def create_camera(db: Session, data: schemas.CameraCreate) -> models.Camera:
    payload = data.model_dump()
    payload["external_id"] = payload.get("external_id") or payload["camera_id"]
    payload["geom"] = _geom(payload.get("lat"), payload.get("lng"))
    cam = models.Camera(**payload)
    db.add(cam)
    db.commit()
    db.refresh(cam)
    return cam


def upsert_missing(db: Session, rows: list[dict]) -> schemas.BulkResult:
    existing = {
        camera.camera_id: camera for camera in db.query(models.Camera).all()
    }
    inserted = 0
    skipped = 0
    for row in rows:
        current = existing.get(row.get("camera_id"))
        if current:
            # Refresh adapter-owned discovery metadata while preserving operator
            # lifecycle fields and analytics choices.
            for field in (
                "name", "department", "department_full", "ownership", "city",
                "site", "lat", "lng", "coords_approx", "camera_type",
                "resolution", "make", "model", "protocol", "vms_platform",
                "stream_url", "codec", "container", "delivery", "storage_type",
                "retention_days", "connectivity", "health_status", "source",
                "source_system", "source_adapter", "external_id", "dept_inferred",
            ):
                if field in row:
                    setattr(current, field, row[field])
            current.geom = _geom(row.get("lat"), row.get("lng"))
            skipped += 1
            continue
        row = dict(row)
        row["external_id"] = row.get("external_id") or row["camera_id"]
        row["geom"] = _geom(row.get("lat"), row.get("lng"))
        camera = models.Camera(**row)
        db.add(camera)
        existing[row["camera_id"]] = camera
        inserted += 1
    db.commit()
    return schemas.BulkResult(
        inserted=inserted, skipped=skipped, total=len(rows)
    )
