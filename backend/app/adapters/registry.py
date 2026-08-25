"""Runtime catalogue for all configured source-system adapters."""

from __future__ import annotations

from .base import AdapterResult, CameraSourceAdapter
from .csitms import CSITMSAdapter
from .rtsp import configured_rtsp_adapters


def configured_adapters() -> list[CameraSourceAdapter]:
    return [CSITMSAdapter(), *configured_rtsp_adapters()]


def adapter_catalog() -> list[dict]:
    return [adapter.describe() for adapter in configured_adapters()]


def discover_all() -> list[AdapterResult]:
    return [adapter.result() for adapter in configured_adapters()]
