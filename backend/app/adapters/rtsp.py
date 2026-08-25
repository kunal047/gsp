"""Configuration-driven adapter for an independent RTSP/ONVIF-style system."""

from __future__ import annotations

import json
import os

from .base import CameraSourceAdapter


class RTSPCatalogAdapter(CameraSourceAdapter):
    kind = "rtsp_catalog"

    def __init__(self, source_system: str, cameras: list[dict]):
        self.source_system = source_system
        self.key = "rtsp-" + "-".join(source_system.lower().split())
        self.label = f"{source_system} RTSP/ONVIF Feed"
        self.cameras = cameras

    def normalize(self, raw: dict, index: int) -> dict:
        external_id = str(raw.get("external_id") or raw.get("id") or index + 1)
        camera_id = raw.get("camera_id") or f"EXT-{self.key.upper()}-{external_id}"
        stream_url = raw.get("stream_url") or raw.get("rtsp_url")
        if not stream_url:
            raise ValueError(f"{self.key} camera {camera_id} has no stream_url")
        return {
            "camera_id": camera_id,
            "external_id": external_id,
            "source_system": self.source_system,
            "source_adapter": self.kind,
            "name": raw.get("name") or camera_id,
            "department": raw.get("department") or "Participant-provided",
            "department_full": raw.get("department_full"),
            "dept_inferred": False,
            "ownership": raw.get("ownership") or "Participant-provided",
            "city": raw.get("city") or "Demo site",
            "site": raw.get("site") or raw.get("name") or camera_id,
            "lat": raw.get("lat"),
            "lng": raw.get("lng"),
            "coords_approx": bool(raw.get("coords_approx", False)),
            "camera_type": raw.get("camera_type") or "IP",
            "resolution": raw.get("resolution"),
            "make": raw.get("make"),
            "model": raw.get("model"),
            "protocol": raw.get("protocol") or "RTSP",
            "vms_platform": raw.get("vms_platform") or self.source_system,
            "stream_url": stream_url,
            "codec": raw.get("codec") or "h264",
            "container": raw.get("container"),
            "delivery": raw.get("delivery") or "rtsp",
            "storage_type": raw.get("storage_type") or "source-managed",
            "retention_days": raw.get("retention_days"),
            "connectivity": raw.get("connectivity"),
            "health_status": raw.get("health_status") or "degraded",
            "amc_expiry": raw.get("amc_expiry"),
            "analytics_enabled": bool(raw.get("analytics_enabled", True)),
            "source": raw.get("source") or self.source_system,
        }

    def discover(self) -> list[dict]:
        return [self.normalize(raw, index) for index, raw in enumerate(self.cameras)]


def configured_rtsp_adapters() -> list[RTSPCatalogAdapter]:
    raw = os.getenv("RTSP_SOURCES_JSON", "").strip()
    if not raw:
        return []
    payload = json.loads(raw)
    if not isinstance(payload, list):
        raise ValueError("RTSP_SOURCES_JSON must be a JSON array")
    grouped: dict[str, list[dict]] = {}
    for camera in payload:
        if not isinstance(camera, dict):
            raise ValueError("each RTSP source entry must be an object")
        system = str(camera.get("source_system") or "Independent RTSP System")
        grouped.setdefault(system, []).append(camera)
    return [RTSPCatalogAdapter(system, cameras) for system, cameras in grouped.items()]
