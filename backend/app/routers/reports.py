"""Audited CSV evidence exports for evaluation and operations."""

import csv
import io
from datetime import datetime, timezone
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


@router.get("/readiness")
def evaluation_readiness(
    db: Session = Depends(get_db),
    p: Principal = Depends(principal),
):
    """Measured Model 1–3 readiness from persisted, non-synthetic evidence."""
    cameras = db.query(models.Camera)
    events = db.query(models.DetectionEvent)
    if p.role == "district_officer" and p.scope:
        cameras = cameras.filter(models.Camera.city == p.scope)
        events = events.filter(models.DetectionEvent.city == p.scope)

    total = cameras.count()
    geocoded = cameras.filter(
        models.Camera.lat.isnot(None), models.Camera.lng.isnot(None)
    ).count()
    lifecycle_complete = cameras.filter(
        models.Camera.installed_at.isnot(None),
        models.Camera.make.isnot(None),
        models.Camera.model.isnot(None),
    ).count()
    online = cameras.filter(models.Camera.health_status == "online").count()
    analytics_cameras = cameras.filter(models.Camera.analytics_enabled.is_(True)).count()
    tracked_events = events.filter(models.DetectionEvent.track_uuid.isnot(None)).count()
    evidence_events = events.filter(
        models.DetectionEvent.track_uuid.isnot(None),
        models.DetectionEvent.snapshot.isnot(None),
        models.DetectionEvent.snapshot != "",
    ).count()
    active_evidence_cameras = events.filter(
        models.DetectionEvent.track_uuid.isnot(None),
        models.DetectionEvent.snapshot.isnot(None),
        models.DetectionEvent.snapshot != "",
    ).with_entities(func.count(func.distinct(models.DetectionEvent.camera_id))).scalar() or 0

    federation = federation_report(db=db, p=p)
    model_1_pass = total > 0 and geocoded == total and lifecycle_complete == total
    model_2_pass = online > 0 and evidence_events > 0
    evidence_pct = round((evidence_events / tracked_events * 100) if tracked_events else 0, 1)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "models": [
            {
                "model": 1,
                "title": "Camera registry and GIS",
                "status": "pass" if model_1_pass else ("partial" if total else "blocked"),
                "summary": f"{total} registered cameras; {geocoded} mapped; {lifecycle_complete} complete asset records.",
                "checks": [
                    {"label": "Registered cameras", "value": total, "ok": total > 0},
                    {"label": "GIS coordinates", "value": f"{geocoded}/{total}", "ok": total > 0 and geocoded == total},
                    {"label": "Complete lifecycle records", "value": f"{lifecycle_complete}/{total}", "ok": total > 0 and lifecycle_complete == total},
                ],
                "blocker": None if model_1_pass else "Department-verified make, model and installation dates are still incomplete.",
            },
            {
                "model": 2,
                "title": "Unified viewing and metadata analytics",
                "status": "pass" if model_2_pass else ("partial" if online else "blocked"),
                "summary": f"{online} live cameras; {evidence_events} evidence-backed tracked events from {active_evidence_cameras} cameras.",
                "checks": [
                    {"label": "Online feeds", "value": online, "ok": online > 0},
                    {"label": "Analytics-enabled cameras", "value": analytics_cameras, "ok": analytics_cameras > 0},
                    {"label": "Tracked events with evidence", "value": f"{evidence_events}/{tracked_events} ({evidence_pct}%)", "ok": evidence_events > 0 and evidence_events == tracked_events},
                ],
                "blocker": None if model_2_pass else "No evidence-backed tracked event has completed on a live source.",
            },
            {
                "model": 3,
                "title": "VMS federation",
                "status": "pass" if federation["federated"] else "blocked",
                "summary": f"{federation['adapter_system_count']} independently adapted source system(s); {federation['camera_count']} normalized cameras.",
                "checks": [
                    {"label": "Independent source adapters", "value": federation["adapter_system_count"], "ok": federation["adapter_system_count"] >= 2},
                    {"label": "Normalized cameras", "value": federation["camera_count"], "ok": federation["camera_count"] > 0},
                    {"label": "Federated event provenance", "value": federation["event_count"], "ok": federation["event_count"] > 0},
                ],
                "blocker": federation["demonstration_gap"],
            },
        ],
    }
