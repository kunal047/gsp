"""Stable contract for departmental CCTV/VMS integrations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


REQUIRED_CAMERA_FIELDS = {"camera_id", "name", "stream_url"}


@dataclass(frozen=True)
class AdapterResult:
    adapter_key: str
    source_system: str
    cameras: list[dict]


class CameraSourceAdapter(ABC):
    """Provider discovery mapped to Netra's canonical camera schema."""

    key: str
    label: str
    kind: str
    source_system: str

    @abstractmethod
    def discover(self) -> list[dict]:
        """Return canonical camera rows for this source system."""

    def result(self) -> AdapterResult:
        cameras = self.discover()
        for index, camera in enumerate(cameras):
            missing = REQUIRED_CAMERA_FIELDS.difference(camera)
            if missing:
                raise ValueError(
                    f"adapter {self.key} camera #{index} is missing "
                    f"{', '.join(sorted(missing))}"
                )
            camera.setdefault("source_system", self.source_system)
            camera.setdefault("source_adapter", self.kind)
            camera.setdefault("external_id", camera["camera_id"])
        return AdapterResult(self.key, self.source_system, cameras)

    def describe(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "kind": self.kind,
            "source_system": self.source_system,
        }
