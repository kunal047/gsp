"""Compatibility facade for the Government CSITMS adapter.

New integrations belong in :mod:`app.adapters`; these names remain so existing
startup, health and API code continues to work during the federation refactor.
"""

from .adapters.csitms import LIVE_BASE, CSITMSAdapter


def fetch_live_cameras() -> list[dict]:
    return CSITMSAdapter().fetch_catalog()


def map_camera(raw: dict) -> dict:
    return CSITMSAdapter().normalize(raw)


def get_mapped_live() -> list[dict]:
    return CSITMSAdapter().discover()
