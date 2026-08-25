"""Audited CSV evidence exports for evaluation and operations."""

import csv
import io
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models
from ..db import get_db
from ..rbac import Principal, audit, principal

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _csv_response(filename: str, header: list[str], rows: list[list[object]]):
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(header)
    # Prevent spreadsheet formula injection from operator/source-controlled text.
    def safe(value: object):
        if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
            return "'" + value
        return value

    writer.writerows([[safe(value) for value in row] for row in rows])
    return Response(
        content=stream.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _scope_cameras(query, p: Principal):
    if p.role == "district_officer" and p.scope:
        return query.filter(models.Camera.city == p.scope)
    return query


@router.get("/cameras.csv")
def camera_registry_csv(
    q: Optional[str] = None,
    department: Optional[str] = None,
    health_status: Optional[str] = None,
    db: Session = Depends(get_db),
    p: Principal = Depends(principal),
):
    query = _scope_cameras(db.query(models.Camera), p)
    if q:
        like = f"%{q}%"
        query = query.filter(
            models.Camera.camera_id.ilike(like)
            | models.Camera.name.ilike(like)
            | models.Camera.site.ilike(like)
        )
    if department:
        query = query.filter(models.Camera.department == department)
    if health_status:
        query = query.filter(models.Camera.health_status == health_status)
    cameras = query.order_by(models.Camera.camera_id).all()
    audit(db, p, "registry.export", f"{len(cameras)} camera rows")
    return _csv_response(
        "netra-camera-registry.csv",
        [
            "camera_id", "name", "department", "city", "site", "lat", "lng",
            "camera_type", "protocol", "codec", "container", "stream_url",
            "health_status", "analytics_enabled", "source", "source_system",
            "source_adapter", "external_id", "installed_at",
            "maintenance_status", "last_service_at", "next_service_at",
            "eol_at", "maintenance_notes",
        ],
        [[
            c.camera_id, c.name, c.department, c.city, c.site, c.lat, c.lng,
            c.camera_type, c.protocol, c.codec, c.container, c.stream_url,
            c.health_status, c.analytics_enabled, c.source, c.source_system,
            c.source_adapter, c.external_id, c.installed_at,
            c.maintenance_status, c.last_service_at, c.next_service_at,
            c.eol_at, c.maintenance_notes,
        ] for c in cameras],
    )


@router.get("/detections.csv")
def detections_csv(
    plate: Optional[str] = None,
    vehicle_type: Optional[str] = None,
    color: Optional[str] = None,
    camera_id: Optional[str] = None,
    detection_ids: Optional[str] = None,
    limit: int = Query(1000, ge=1, le=10000),
    db: Session = Depends(get_db),
    p: Principal = Depends(principal),
):
    query = db.query(models.DetectionEvent).filter(
        models.DetectionEvent.track_uuid.isnot(None)
    )
    if p.role == "district_officer" and p.scope:
        query = query.filter(models.DetectionEvent.city == p.scope)
    if plate:
        normalized = "".join(ch for ch in plate.upper() if ch.isalnum())
        query = query.filter(models.DetectionEvent.plate_norm.like(f"%{normalized}%"))
    if vehicle_type:
        query = query.filter(models.DetectionEvent.vehicle_type == vehicle_type)
    if color:
        query = query.filter(models.DetectionEvent.color == color)
    if camera_id:
        query = query.filter(models.DetectionEvent.camera_id == camera_id)
    if detection_ids:
        ids = [int(value) for value in detection_ids.split(",") if value.strip().isdigit()]
        query = query.filter(models.DetectionEvent.id.in_(ids))
    events = query.order_by(models.DetectionEvent.ts.asc()).limit(limit).all()
    audit(
        db,
        p,
        "detections.export",
        f"plate={plate or '-'} type={vehicle_type or '-'} color={color or '-'} -> {len(events)} rows",
    )
    return _csv_response(
        "netra-movement-evidence.csv",
        [
            "detection_id", "timestamp", "camera_id", "camera_name", "district",
            "latitude", "longitude", "event_type", "registration_number",
            "vehicle_type", "color", "confidence", "evidence_snapshot",
            "track_uuid", "track_id", "track_hits", "class_confidence",
            "color_confidence", "first_seen", "last_seen", "time_source",
            "direction", "dwell_seconds", "motion_px_per_second", "stopped",
            "wrong_way", "source_system", "source_adapter",
        ],
        [[
            e.id, e.ts.isoformat() if e.ts else "", e.camera_id, e.camera_name,
            e.city, e.lat, e.lng, e.event_type, e.plate, e.vehicle_type, e.color,
            e.confidence, e.snapshot,
            e.track_uuid, e.track_id, e.track_hits, e.class_confidence,
            e.color_confidence,
            e.first_seen.isoformat() if e.first_seen else "",
            e.last_seen.isoformat() if e.last_seen else "",
            e.time_source, e.direction, e.dwell_seconds,
            e.motion_px_per_second, e.stopped, e.wrong_way,
            e.source_system, e.source_adapter,
        ] for e in events],
    )


@router.get("/federation")
def federation_report(
    db: Session = Depends(get_db),
    p: Principal = Depends(principal),
):
    """Normalized Model 3 coverage and event activity per source system."""
    camera_query = db.query(
        models.Camera.source_system,
        models.Camera.source_adapter,
        func.count(models.Camera.id),
        func.count(models.Camera.id).filter(models.Camera.health_status == "online"),
        func.count(models.Camera.id).filter(models.Camera.analytics_enabled.is_(True)),
    )
    event_query = db.query(
        models.DetectionEvent.source_system,
        func.count(models.DetectionEvent.id),
        func.count(func.distinct(models.DetectionEvent.camera_id)),
    ).filter(models.DetectionEvent.track_uuid.isnot(None))
    if p.role == "district_officer" and p.scope:
        camera_query = camera_query.filter(models.Camera.city == p.scope)
        event_query = event_query.filter(models.DetectionEvent.city == p.scope)
    camera_rows = camera_query.group_by(
        models.Camera.source_system, models.Camera.source_adapter
    ).all()
    event_rows = {
        row[0]: {"events": row[1], "active_cameras": row[2]}
        for row in event_query.group_by(models.DetectionEvent.source_system).all()
    }
    systems = [
        {
            "source_system": source or "Unknown",
            "source_adapter": adapter or "unknown",
            "cameras": count,
            "online": online,
            "analytics_enabled": analytics,
            **event_rows.get(source, {"events": 0, "active_cameras": 0}),
        }
        for source, adapter, count, online, analytics in camera_rows
    ]
    adapter_systems = [item for item in systems if item["source_adapter"] != "manual"]
    return {
        "systems": systems,
        "system_count": len(systems),
        "adapter_system_count": len(adapter_systems),
        "camera_count": sum(item["cameras"] for item in systems),
        "event_count": sum(item["events"] for item in systems),
        "federated": len(adapter_systems) >= 2,
        "demonstration_gap": (
            None if len(adapter_systems) >= 2
            else "Configure one independent RTSP/VMS source to prove cross-system federation."
        ),
    }
