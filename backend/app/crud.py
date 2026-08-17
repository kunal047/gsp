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
    payload["geom"] = _geom(payload.get("lat"), payload.get("lng"))
    cam = models.Camera(**payload)
    db.add(cam)
    db.commit()
    db.refresh(cam)
    return cam


def upsert_missing(db: Session, rows: list[dict]) -> schemas.BulkResult:
    existing = {c[0] for c in db.query(models.Camera.camera_id).all()}
    inserted = 0
    skipped = 0
    for row in rows:
        if row.get("camera_id") in existing:
            skipped += 1
            continue
        row = dict(row)
        row["geom"] = _geom(row.get("lat"), row.get("lng"))
        db.add(models.Camera(**row))
        existing.add(row["camera_id"])
        inserted += 1
    db.commit()
    return schemas.BulkResult(
        inserted=inserted, skipped=skipped, total=len(rows)
    )
