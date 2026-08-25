from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class CameraBase(BaseModel):
    camera_id: str
    name: Optional[str] = None
    department: Optional[str] = None
    department_full: Optional[str] = None
    ownership: Optional[str] = "Government"
    city: Optional[str] = None
    site: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    coords_approx: Optional[bool] = False
    camera_type: Optional[str] = None
    resolution: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    protocol: Optional[str] = None
    vms_platform: Optional[str] = None
    stream_url: Optional[str] = None
    codec: Optional[str] = None
    container: Optional[str] = None
    delivery: Optional[str] = None
    storage_type: Optional[str] = None
    retention_days: Optional[int] = None
    connectivity: Optional[str] = None
    health_status: Optional[str] = "online"
    amc_expiry: Optional[str] = None
    analytics_enabled: Optional[bool] = False
    source: Optional[str] = None
    source_system: Optional[str] = "Manual / CSV"
    source_adapter: Optional[str] = "manual"
    external_id: Optional[str] = None
    dept_inferred: Optional[bool] = False
    installed_at: Optional[datetime] = None
    maintenance_status: Optional[str] = "unknown"
    last_service_at: Optional[datetime] = None
    next_service_at: Optional[datetime] = None
    eol_at: Optional[datetime] = None
    maintenance_notes: Optional[str] = None


class CameraCreate(CameraBase):
    pass


class CameraLifecycleUpdate(BaseModel):
    installed_at: Optional[datetime] = None
    maintenance_status: Literal[
        "unknown", "healthy", "due", "overdue", "under_maintenance", "retired"
    ]
    last_service_at: Optional[datetime] = None
    next_service_at: Optional[datetime] = None
    eol_at: Optional[datetime] = None
    maintenance_notes: Optional[str] = Field(default=None, max_length=2000)


class CameraOut(CameraBase):
    id: int

    class Config:
        from_attributes = True


class BulkResult(BaseModel):
    inserted: int
    skipped: int
    total: int


class DetectionIn(BaseModel):
    camera_id: str
    event_type: str = "vehicle"  # anpr | vehicle
    plate: Optional[str] = None
    vehicle_type: Optional[str] = None
    color: Optional[str] = None
    confidence: float = 0.0
    plate_confidence: Optional[float] = None
    track_uuid: Optional[str] = None
    track_id: Optional[int] = None
    track_hits: int = Field(default=1, ge=1)
    class_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    color_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    event_ts: Optional[datetime] = None
    time_source: str = "ingest"
    direction: Optional[str] = None
    dwell_seconds: Optional[float] = Field(default=None, ge=0.0)
    motion_px_per_second: Optional[float] = Field(default=None, ge=0.0)
    stopped: bool = False
    wrong_way: Optional[bool] = None
    bbox_x1: Optional[int] = None
    bbox_y1: Optional[int] = None
    bbox_x2: Optional[int] = None
    bbox_y2: Optional[int] = None
    snapshot_b64: Optional[str] = None


class DetectionOut(BaseModel):
    id: int
    camera_id: str
    camera_name: Optional[str] = None
    city: Optional[str] = None
    source_system: Optional[str] = None
    source_adapter: Optional[str] = None
    event_type: str
    plate: Optional[str] = None
    plate_norm: Optional[str] = None
    vehicle_type: Optional[str] = None
    color: Optional[str] = None
    confidence: float
    plate_confidence: Optional[float] = None
    track_uuid: Optional[str] = None
    track_id: Optional[int] = None
    track_hits: int = 1
    class_confidence: Optional[float] = None
    color_confidence: Optional[float] = None
    snapshot: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    ts: Optional[datetime] = None
    ingested_at: Optional[datetime] = None
    time_source: str = "ingest"
    direction: Optional[str] = None
    dwell_seconds: Optional[float] = None
    motion_px_per_second: Optional[float] = None
    stopped: bool = False
    wrong_way: Optional[bool] = None
    bbox_x1: Optional[int] = None
    bbox_y1: Optional[int] = None
    bbox_x2: Optional[int] = None
    bbox_y2: Optional[int] = None
    alert_ids: list[int] = Field(default_factory=list)

    class Config:
        from_attributes = True
