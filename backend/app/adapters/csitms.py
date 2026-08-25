"""Adapter for the Government-provided Gujarat CSITMS source system."""

import json
import os
import urllib.request

from ..geocode import geocode
from .base import CameraSourceAdapter


LIVE_BASE = os.getenv("LIVE_BASE", "https://live.corp8.cloud")


def _department(location: str):
    loc = (location or "").lower()
    if "panchayat" in loc:
        return "Panchayat", "Panchayat / Rural Development", True
    if "vidhyalaya" in loc or "school" in loc:
        return "Education", "Education Department", True
    return "Traffic/CSITMS", "Home Department (Traffic / CSITMS)", True


class CSITMSAdapter(CameraSourceAdapter):
    key = "gujarat-csitms"
    label = "Gujarat CSITMS Government Feed"
    kind = "csitms_api"
    source_system = "Gujarat CSITMS"

    def __init__(self, base_url: str = LIVE_BASE):
        self.base_url = base_url.rstrip("/")

    def _absolute_url(self, url):
        if not url:
            return None
        return f"{self.base_url}{url}" if url.startswith("/") else url

    def fetch_catalog(self) -> list[dict]:
        request = urllib.request.Request(
            f"{self.base_url}/api/ingest", headers={"User-Agent": "netra/0.2"}
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.load(response)
        return data.get("cameras", []) if isinstance(data, dict) else data

    def normalize(self, raw: dict) -> dict:
        provider_id = int(raw["id"])
        number = raw.get("number") or provider_id
        location = raw.get("location") or raw.get("name") or f"Camera {number}"
        district, lat, lng = geocode(location, number)
        department, department_full, inferred = _department(location)
        width, height = raw.get("width") or 0, raw.get("height") or 0
        hls_url = self._absolute_url(raw.get("hls_live_url"))
        return {
            "camera_id": f"GJ-CSITMS-{provider_id:03d}",
            "external_id": str(provider_id),
            "source_system": self.source_system,
            "source_adapter": self.kind,
            "name": raw.get("name") or location,
            "department": department,
            "department_full": department_full,
            "dept_inferred": inferred,
            "ownership": "Government",
            "city": district,
            "site": location,
            "lat": lat,
            "lng": lng,
            "coords_approx": True,
            "camera_type": "IP",
            "resolution": f"{width}x{height}" if width and height else None,
            "make": None,
            "model": None,
            "protocol": "RTSP · WebRTC · HLS (live)",
            "vms_platform": "CSITMS",
            "stream_url": hls_url or f"{self.base_url}/stream/{provider_id}",
            "codec": raw.get("codec") or None,
            "container": None,
            "delivery": "hls",
            "storage_type": None,
            "retention_days": None,
            "connectivity": None,
            "health_status": "online" if raw.get("live") else "offline",
            "amc_expiry": None,
            "analytics_enabled": True,
            "source": self.base_url,
        }

    def discover(self) -> list[dict]:
        return [self.normalize(camera) for camera in self.fetch_catalog()]
