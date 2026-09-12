from geoalchemy2 import Geography
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    func,
)

from .db import Base


class Camera(Base):
    __tablename__ = "cameras"

    id = Column(Integer, primary_key=True)
    camera_id = Column(String, unique=True, index=True, nullable=False)
    name = Column(String)
    department = Column(String, index=True)
    department_full = Column(String)
    ownership = Column(String, default="Government")
    city = Column(String, index=True)  # district / city (derived from location)
    site = Column(String)  # raw location string from source
    lat = Column(Float)
    lng = Column(Float)
    coords_approx = Column(Boolean, default=False)  # true = geocoded, not surveyed
    camera_type = Column(String, index=True)  # IP / Analog
    resolution = Column(String)
    make = Column(String)
    model = Column(String)
    protocol = Column(String)  # ONVIF/RTSP, HTTP progressive, HLS ...
    vms_platform = Column(String)
    stream_url = Column(String)  # real playable stream endpoint
    codec = Column(String)
    container = Column(String)
    delivery = Column(String)  # progressive / hls
    storage_type = Column(String)  # local / cloud
    retention_days = Column(Integer)
    connectivity = Column(String)  # GSWAN / SD-WAN/VPN
    health_status = Column(String, index=True)  # online / degraded / offline
    amc_expiry = Column(String)
    analytics_enabled = Column(Boolean, default=False)
    source = Column(String)  # data origin (e.g. live.corp8.cloud / seed)
    # Canonical federation provenance. source is the endpoint/operator-facing
    # origin; source_system identifies the independent VMS/domain and remains
    # stable if its URL changes.
    source_system = Column(String, index=True, nullable=False, default="Manual / CSV")
    source_adapter = Column(String, index=True, nullable=False, default="manual")
    external_id = Column(String, nullable=False)
    dept_inferred = Column(Boolean, default=False)
    installed_at = Column(DateTime(timezone=True), nullable=True)
    maintenance_status = Column(String, nullable=False, default="unknown")
    last_service_at = Column(DateTime(timezone=True), nullable=True)
    next_service_at = Column(DateTime(timezone=True), nullable=True)
    eol_at = Column(DateTime(timezone=True), nullable=True)
    maintenance_notes = Column(String, nullable=True)
    # PostGIS geography point (lng lat), SRID 4326
    geom = Column(Geography(geometry_type="POINT", srid=4326))


class DetectionEvent(Base):
    __tablename__ = "detection_events"

    id = Column(Integer, primary_key=True)
    camera_id = Column(String, index=True)
    camera_name = Column(String)
    city = Column(String, index=True)
    source_system = Column(String, index=True, nullable=True)
    source_adapter = Column(String, nullable=True)
    event_type = Column(String, index=True)  # anpr | vehicle
    plate = Column(String, index=True, nullable=True)
    plate_norm = Column(String, index=True, nullable=True)  # normalized for match
    vehicle_type = Column(String, nullable=True)  # car/truck/bus/motorcycle
    color = Column(String, index=True, nullable=True)  # dominant vehicle colour
    confidence = Column(Float)
    plate_confidence = Column(Float, nullable=True)
    track_uuid = Column(String, unique=True, index=True, nullable=True)
    track_id = Column(Integer, nullable=True)
    track_hits = Column(Integer, nullable=False, default=1)
    class_confidence = Column(Float, nullable=True)
    color_confidence = Column(Float, nullable=True)
    snapshot = Column(String, nullable=False)  # required served URL of crop
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    first_seen = Column(DateTime(timezone=True), nullable=True)
    last_seen = Column(DateTime(timezone=True), nullable=True)
    ts = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    ingested_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    time_source = Column(String, nullable=False, default="ingest")
    direction = Column(String, nullable=True)
    dwell_seconds = Column(Float, nullable=True)
    motion_px_per_second = Column(Float, nullable=True)
    stopped = Column(Boolean, nullable=False, default=False)
    wrong_way = Column(Boolean, nullable=True)
    bbox_x1 = Column(Integer, nullable=True)
    bbox_y1 = Column(Integer, nullable=True)
    bbox_x2 = Column(Integer, nullable=True)
    bbox_y2 = Column(Integer, nullable=True)


class Watchlist(Base):
    """Representative watchlist database (challenge Step 3). Records of interest
    that live detections are matched against. NOT live government records -
    synthetic/representative data for demonstration."""

    __tablename__ = "watchlist"

    id = Column(Integer, primary_key=True)
    category = Column(String, index=True)  # stolen_vehicle | blacklisted_vehicle
    #   | suspect_vehicle | wanted_person | missing_person
    label = Column(String)  # human identifier (plate / make-model / description)
    kind = Column(String)  # plate | attribute | person
    plate_norm = Column(String, index=True, nullable=True)
    vehicle_type = Column(String, nullable=True)
    color = Column(String, nullable=True)
    case_ref = Column(String, nullable=True)  # FIR / case number
    reason = Column(String)
    source = Column(String, default="Representative dataset")
    severity = Column(String, default="high")  # high | medium | low
    min_confidence = Column(Float, default=0.65)
    min_track_hits = Column(Integer, default=3)
    active = Column(Boolean, default=True)
    created = Column(DateTime(timezone=True), server_default=func.now())


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True)
    kind = Column(String, index=True)  # congestion | surge | watchlist | cloned_plate | feed_offline
    watchlist_id = Column(Integer, index=True, nullable=True)
    watchlist_category = Column(String, nullable=True)
    case_ref = Column(String, nullable=True)
    matched_on = Column(String, nullable=True)  # plate | attribute
    match_confidence = Column(Float, nullable=True)
    detection_id = Column(Integer, nullable=True)
    vehicle_count = Column(Integer, nullable=True)
    camera_id = Column(String, index=True)
    camera_name = Column(String)
    city = Column(String)
    source_system = Column(String, index=True, nullable=True)
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    plate = Column(String, nullable=True)
    vehicle_type = Column(String, nullable=True)
    color = Column(String, nullable=True)
    reason = Column(String)
    source = Column(String)
    severity = Column(String, default="high")
    snapshot = Column(String, nullable=True)
    acknowledged = Column(Boolean, default=False)
    ts = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    ingested_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    time_source = Column(String, nullable=False, default="ingest")


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True)
    user = Column(String, index=True)
    role = Column(String)
    action = Column(String, index=True)
    detail = Column(String)
    ts = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class CameraBaseline(Base):
    """Persisted per-camera traffic baseline for alert calibration.

    The EMA of the per-frame vehicle count is learned live and stored here so it
    survives restarts (no cold-start false surges), and the congestion threshold
    adapts per camera - a busy junction and a quiet lane no longer share one
    global cut-off. An operator may pin an explicit threshold via override."""

    __tablename__ = "camera_baselines"

    camera_id = Column(String, primary_key=True)
    ema = Column(Float, nullable=False, default=0.0)          # learned normal count
    sample_count = Column(Integer, nullable=False, default=0)  # frames observed
    peak = Column(Integer, nullable=False, default=0)          # highest count seen
    congestion_threshold = Column(Integer, nullable=True)      # operator override; null = adaptive
    buckets = Column(String, nullable=True)                    # JSON: per-daypart EMAs (time-of-day)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class User(Base):
    """Authenticated operator. Identity + role come from a verified signed token,
    NOT from caller-supplied headers - so a client cannot self-assign a role."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String)
    password_hash = Column(String, nullable=False)  # pbkdf2$iter$salt$hash
    role = Column(String, nullable=False, default="viewer")
    scope = Column(String, nullable=True)  # district for district_officer
    active = Column(Boolean, nullable=False, default=True)
    created = Column(DateTime(timezone=True), server_default=func.now())
