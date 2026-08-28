"""Representative asset-lifecycle seed (challenge Step 3 - representative data).

The live feed API (`/api/ingest`) publishes only stream info - it carries NO
make/model/install-date/AMC. In deployment that metadata comes from the
department's asset-management / CMDB / procurement system, which is not reachable
from this environment. To exercise Model 1's asset-lifecycle features
(ageing/EOL, maintenance status, gap analysis) we seed a REPRESENTATIVE record
per camera, clearly labelled as such in `maintenance_notes`, and only where a
field is empty - operator edits via the lifecycle API are never overwritten.
"""
import hashlib
from datetime import datetime, timedelta, timezone

from . import models

REF = datetime(2026, 8, 26, tzinfo=timezone.utc)  # anchor for relative dates
NOTE = "Representative asset record - department CMDB/procurement integration pending (feed API carries no asset metadata)."

# (vendor, [models], resolution) - realistic government-CCTV vendors.
CATALOG = [
    ("Hikvision", ["DS-2CD2085FWD-I", "DS-2CD2T47G2-L", "iDS-2CD7A46G0-IZS"], "8MP (3840×2160)"),
    ("Dahua", ["IPC-HFW5442E-ZE", "IPC-HDBW3841E-AS", "ITC431-RW1F-L"], "4MP (2688×1520)"),
    ("CP Plus", ["CP-UNC-TA81L5C-MDS", "CP-VNC-V51R6C"], "5MP (2592×1944)"),
    ("Bosch", ["FLEXIDOME IP 8000i", "DINION IP 5000i"], "6MP (3072×1728)"),
    ("Axis", ["P1448-LE", "Q1798-LE"], "8MP (3840×2160)"),
    ("Honeywell", ["HC35W45R3", "HBD3PR2"], "4MP (2560×1440)"),
]


def _h(camera_id: str, salt: str) -> int:
    return int(hashlib.md5(f"{camera_id}:{salt}".encode()).hexdigest(), 16)


def _record(camera_id: str) -> dict:
    vendor, models_, resolution = CATALOG[_h(camera_id, "v") % len(CATALOG)]
    model = models_[_h(camera_id, "m") % len(models_)]

    age_years = _h(camera_id, "age") % 10          # 0..9 years old (spread 2016-2026)
    installed = REF - timedelta(days=age_years * 365 + (_h(camera_id, "d") % 365))
    eol = installed + timedelta(days=8 * 365)      # ~8-year service life

    # Last service in the past year; next service 6 months after.
    last_service = REF - timedelta(days=_h(camera_id, "svc") % 360)
    next_service = last_service + timedelta(days=182)

    if eol < REF:
        status = "retired"
    elif next_service < REF - timedelta(days=30):
        status = "overdue"
    elif next_service < REF:
        status = "due"
    else:
        status = "healthy"

    amc = (last_service + timedelta(days=365)).date().isoformat()
    return {
        "make": vendor, "model": model, "resolution": resolution,
        "installed_at": installed, "eol_at": eol,
        "last_service_at": last_service, "next_service_at": next_service,
        "maintenance_status": status, "amc_expiry": amc,
        "maintenance_notes": NOTE,
    }


def seed_asset_lifecycle(db) -> int:
    """Fill empty lifecycle fields with a representative record. Idempotent."""
    filled = 0
    for cam in db.query(models.Camera).all():
        rec = _record(cam.camera_id)
        changed = False
        for field, value in rec.items():
            if getattr(cam, field, None) in (None, ""):
                setattr(cam, field, value)
                changed = True
        # maintenance_status defaults to "unknown"; upgrade it if still unset.
        if cam.maintenance_status in (None, "", "unknown") and rec["maintenance_status"]:
            cam.maintenance_status = rec["maintenance_status"]
            changed = True
        if changed:
            filled += 1
    db.commit()
    return filled
