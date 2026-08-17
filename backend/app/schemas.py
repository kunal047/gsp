from datetime import datetime
from typing import Optional

from pydantic import BaseModel


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
    dept_inferred: Optional[bool] = False


class CameraCreate(CameraBase):
    pass


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
    snapshot_b64: Optional[str] = None


class DetectionOut(BaseModel):
    id: int
    camera_id: str
    camera_name: Optional[str] = None
    city: Optional[str] = None
    event_type: str
    plate: Optional[str] = None
    plate_norm: Optional[str] = None
    vehicle_type: Optional[str] = None
    color: Optional[str] = None
    confidence: float
    plate_confidence: Optional[float] = None
    snapshot: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    ts: Optional[datetime] = None

    class Config:
        from_attributes = True
