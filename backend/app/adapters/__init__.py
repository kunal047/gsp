"""Camera-source adapters and the federation registry.

Every external CCTV/VMS system is isolated behind the same contract. The
backend and UI consume only normalized camera dictionaries; provider-specific
APIs never leak into downstream services.
"""

from .base import AdapterResult, CameraSourceAdapter
from .registry import adapter_catalog, configured_adapters, discover_all

__all__ = [
    "AdapterResult",
    "CameraSourceAdapter",
    "adapter_catalog",
    "configured_adapters",
    "discover_all",
]
