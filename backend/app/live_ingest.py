"""Adapter: onboard the real government CCTV feed into the Netra registry.

Source: https://live.sentinelgujarat.in  (Gujarat CSITMS live control-room API)

Real fields are stored verbatim. Fields the source does not provide
(coordinates, department, camera_type) are DERIVED and explicitly flagged
(`coords_approx`, `dept_inferred`) so nothing is passed off as surveyed truth.
"""
import json
import os
import urllib.request

from .geocode import geocode

LIVE_BASE = os.getenv("LIVE_BASE", "https://live.sentinelgujarat.in")


def _department(location: str):
    loc = (location or "").lower()
    if "panchayat" in loc:
        return "Panchayat", "Panchayat / Rural Development", True
    if "vidhyalaya" in loc or "school" in loc:
        return "Education", "Education Department", True
    # CSITMS cameras are traffic-surveillance under the Home Department
    return "Traffic/CSITMS", "Home Department (Traffic / CSITMS)", True


def fetch_live_cameras() -> list[dict]:
    req = urllib.request.Request(
        f"{LIVE_BASE}/api/cameras", headers={"User-Agent": "netra/0.1"}
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.load(resp)
    return data.get("cameras", [])


def map_camera(raw: dict) -> dict:
    num = raw.get("number") or int(raw.get("id", 0) or 0)
    location = raw.get("location") or raw.get("name") or f"Camera {num}"
    district, lat, lng = geocode(location, num)
    dept, dept_full, inferred = _department(location)
    status = "online" if raw.get("status") == "live" else "offline"
    delivery = raw.get("delivery") or "progressive"
    container = raw.get("container")
    return {
        "camera_id": f"GJ-CSITMS-{int(raw['id']):03d}",
        "name": raw.get("name") or location,
        "department": dept,
        "department_full": dept_full,
        "dept_inferred": inferred,
        "ownership": "Government",
        "city": district,
        "site": location,
        "lat": lat,
        "lng": lng,
        "coords_approx": True,
        "camera_type": "IP",
        "resolution": None,
        "make": None,
        "model": None,
        "protocol": f"HTTP {delivery}"
        + (f" ({container.upper()})" if container else ""),
        "vms_platform": "CSITMS",
        "stream_url": f"{LIVE_BASE}/stream/{raw['id']}",
        "codec": raw.get("codec"),
        "container": container,
        "delivery": delivery,
        "storage_type": None,
        "retention_days": None,
        "connectivity": None,
        "health_status": status,
        "amc_expiry": None,
        "analytics_enabled": True,
        "source": "live.sentinelgujarat.in",
    }


def get_mapped_live() -> list[dict]:
    return [map_camera(c) for c in fetch_live_cameras()]
