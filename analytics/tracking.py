"""Per-camera track lifecycle and evidence generation.

ByteTrack assigns IDs frame-to-frame. This module turns those transient
observations into one durable event per completed track and derives only
camera-plane motion metrics that are defensible without road calibration.
"""
from __future__ import annotations

import math
import os
import re
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import cv2
import numpy as np

# Plate reads are only trusted when the SAME normalised plate is read across
# several frames of one track (single-crop OCR is noise). Random misreads rarely
# repeat the same string, so consensus + a real confidence floor + a valid
# Indian-plate format removes false positives - no plate is stored otherwise.
PLATE_MIN_AGREEMENTS = int(os.getenv("PLATE_MIN_AGREEMENTS", "3"))
PLATE_MIN_OCR_CONFIDENCE = float(os.getenv("PLATE_MIN_OCR_CONFIDENCE", "0.5"))
# Bound how long a single track may stay open. A track alive beyond this (a
# wedged/loitering vehicle, or a looping test feed where the subject never
# leaves) is checkpointed into an event and re-formed, so evidence is emitted
# instead of accumulating forever. Measured on the PTS media clock.
MAX_TRACK_SECONDS = float(os.getenv("MAX_TRACK_SECONDS", "20"))
PLATE_FORMAT_RE = re.compile(r"^[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{3,4}$")


def consensus_plate(votes: Counter, best_conf: dict):
    """Return (plate, confidence, agreements) only if a plate is corroborated
    by >= PLATE_MIN_AGREEMENTS frames, clears the OCR-confidence floor, and
    matches the Indian plate format; otherwise (None, 0.0, agreements)."""
    if not votes:
        return None, 0.0, 0
    plate, agreements = votes.most_common(1)[0]
    conf = float(best_conf.get(plate, 0.0))
    if (
        agreements >= PLATE_MIN_AGREEMENTS
        and conf >= PLATE_MIN_OCR_CONFIDENCE
        and PLATE_FORMAT_RE.match(plate)
    ):
        return plate, conf, agreements
    return None, 0.0, agreements


def _copy_image(image):
    return image.copy() if image is not None and image.size else None


def annotated_context(frame, box, label, margin=0.55):
    """Return a contextual crop with the matched object explicitly marked."""
    if frame is None or frame.size == 0:
        return None
    height, width = frame.shape[:2]
    x1, y1, x2, y2 = [int(value) for value in box]
    bw, bh = max(1, x2 - x1), max(1, y2 - y1)
    mx, my = int(bw * margin), int(bh * margin)
    cx1, cy1 = max(0, x1 - mx), max(0, y1 - my)
    cx2, cy2 = min(width, x2 + mx), min(height, y2 + my)
    context = frame[cy1:cy2, cx1:cx2].copy()
    if context.size == 0:
        return None

    rx1, ry1, rx2, ry2 = x1 - cx1, y1 - cy1, x2 - cx1, y2 - cy1
    thickness = max(2, round(max(context.shape[:2]) / 280))
    cv2.rectangle(context, (rx1, ry1), (rx2, ry2), (32, 68, 255), thickness)
    font_scale = max(0.45, min(0.9, context.shape[1] / 700))
    (tw, th), _ = cv2.getTextSize(
        label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness
    )
    label_y = max(th + 8, ry1)
    cv2.rectangle(
        context,
        (rx1, label_y - th - 8),
        (min(context.shape[1] - 1, rx1 + tw + 10), label_y + 4),
        (32, 68, 255),
        -1,
    )
    cv2.putText(
        context,
        label,
        (rx1 + 5, label_y - 3),
        cv2.FONT_HERSHEY_SIMPLEX,
        font_scale,
        (255, 255, 255),
        thickness,
        cv2.LINE_AA,
    )
    return context


@dataclass
class TrackState:
    camera_id: str
    tracker_id: int
    track_uuid: str
    first_seen: datetime
    last_seen: datetime
    first_media_seconds: float
    last_media_seconds: float
    frame_width: int
    frame_height: int
    hits: int = 0
    misses: int = 0
    confidence_sum: float = 0.0
    type_votes: Counter = field(default_factory=Counter)
    color_votes: Counter = field(default_factory=Counter)
    observations: list[tuple[float, float, float]] = field(default_factory=list)
    best_confidence: float = -1.0
    best_crop: Optional[np.ndarray] = None
    best_evidence: Optional[np.ndarray] = None
    best_box: Optional[tuple[int, int, int, int]] = None
    plate_votes: Counter = field(default_factory=Counter)
    plate_best_conf: dict = field(default_factory=dict)

    def observe(self, detection, frame, media_seconds, event_time):
        self.hits += 1
        self.misses = 0
        self.last_seen = event_time
        self.last_media_seconds = media_seconds
        confidence = float(detection.get("confidence") or 0.0)
        self.confidence_sum += confidence
        vehicle_type = detection.get("vehicle_type")
        color = detection.get("color")
        if vehicle_type:
            self.type_votes[vehicle_type] += 1
        if color:
            self.color_votes[color] += 1

        x1, y1, x2, y2 = detection["box"]
        self.observations.append(
            (media_seconds, (x1 + x2) / 2.0, (y1 + y2) / 2.0)
        )
        # Accumulate every per-frame plate read; the durable plate is decided by
        # cross-frame consensus at finish(), not by a single best crop.
        plate = detection.get("plate")
        plate_confidence = float(detection.get("plate_confidence") or 0.0)
        if plate:
            self.plate_votes[plate] += 1
            if plate_confidence > self.plate_best_conf.get(plate, 0.0):
                self.plate_best_conf[plate] = plate_confidence

        if confidence >= self.best_confidence:
            self.best_confidence = confidence
            self.best_box = (x1, y1, x2, y2)
            self.best_crop = _copy_image(detection.get("crop"))
            label = f"track {self.tracker_id} · {vehicle_type or 'vehicle'} {confidence:.2f}"
            self.best_evidence = annotated_context(frame, self.best_box, label)

    def finish(self, expected_direction=None):
        vehicle_type, type_hits = (
            self.type_votes.most_common(1)[0] if self.type_votes else (None, 0)
        )
        color, color_hits = (
            self.color_votes.most_common(1)[0] if self.color_votes else (None, 0)
        )
        class_confidence = type_hits / self.hits if self.hits else 0.0
        color_confidence = color_hits / self.hits if self.hits else 0.0
        mean_confidence = self.confidence_sum / self.hits if self.hits else 0.0
        duration = max(0.0, self.last_media_seconds - self.first_media_seconds)

        direction = None
        motion_px_per_second = 0.0
        displacement_ratio = 0.0
        if len(self.observations) >= 2:
            _, start_x, start_y = self.observations[0]
            _, end_x, end_y = self.observations[-1]
            dx, dy = end_x - start_x, end_y - start_y
            if abs(dx) >= abs(dy):
                direction = "right" if dx >= 0 else "left"
            else:
                direction = "down" if dy >= 0 else "up"
            distance = 0.0
            for previous, current in zip(self.observations, self.observations[1:]):
                distance += math.hypot(current[1] - previous[1], current[2] - previous[2])
            motion_px_per_second = distance / duration if duration > 0 else 0.0
            diagonal = math.hypot(self.frame_width, self.frame_height)
            displacement_ratio = math.hypot(dx, dy) / diagonal if diagonal else 0.0

        stopped = duration >= 5.0 and displacement_ratio <= 0.025
        wrong_way = None
        if expected_direction and direction:
            opposite = {"left": "right", "right": "left", "up": "down", "down": "up"}
            wrong_way = direction == opposite.get(expected_direction)

        plate, plate_conf, plate_agreements = consensus_plate(
            self.plate_votes, self.plate_best_conf
        )

        return {
            "track_uuid": self.track_uuid,
            "track_id": self.tracker_id,
            "track_hits": self.hits,
            "vehicle_type": vehicle_type,
            "class_confidence": round(class_confidence, 3),
            "color": color,
            "color_confidence": round(color_confidence, 3),
            "confidence": round(mean_confidence, 3),
            "plate": plate,
            "plate_confidence": round(plate_conf, 3) if plate else None,
            "plate_agreements": plate_agreements if plate else 0,
            "crop": self.best_crop,
            "evidence": self.best_evidence,
            "box": self.best_box,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "event_ts": self.first_seen,
            "direction": direction,
            "dwell_seconds": round(duration, 2),
            "motion_px_per_second": round(motion_px_per_second, 2),
            "stopped": stopped,
            "wrong_way": wrong_way,
        }


class TrackLifecycle:
    """Aggregate isolated per-camera ByteTrack observations into events."""

    def __init__(self, min_hits=3, max_misses=3, min_confidence=0.45, expected=None):
        self.min_hits = min_hits
        self.max_misses = max_misses
        self.min_confidence = min_confidence
        self.expected = expected or {}
        self.session_id = uuid.uuid4().hex[:12]
        self.states: dict[tuple[str, int], TrackState] = {}

    def update(self, camera_id, detections, frame, media_seconds, event_time=None):
        event_time = event_time or datetime.now(timezone.utc)
        height, width = frame.shape[:2]
        observed = set()
        for detection in detections:
            tracker_id = int(detection["track_id"])
            key = (camera_id, tracker_id)
            observed.add(key)
            state = self.states.get(key)
            if state is None:
                state = TrackState(
                    camera_id=camera_id,
                    tracker_id=tracker_id,
                    track_uuid=f"{camera_id}:{self.session_id}:{tracker_id}:{uuid.uuid4().hex[:8]}",
                    first_seen=event_time,
                    last_seen=event_time,
                    first_media_seconds=media_seconds,
                    last_media_seconds=media_seconds,
                    frame_width=width,
                    frame_height=height,
                )
                self.states[key] = state
            state.observe(detection, frame, media_seconds, event_time)

        completed = []
        for key, state in list(self.states.items()):
            if key[0] != camera_id:
                continue
            if key in observed:
                # Checkpoint a track that has stayed open too long, then drop its
                # state so the next observation starts a fresh track/event. Age is
                # measured on the wall clock (first_seen -> last_seen): live RTSP
                # often doesn't report PTS, so the media clock creeps unreliably.
                age = (state.last_seen - state.first_seen).total_seconds()
                if MAX_TRACK_SECONDS and age >= MAX_TRACK_SECONDS:
                    event = self._complete(key, state)
                    if event:
                        completed.append(event)
                continue
            state.misses += 1
            if state.misses >= self.max_misses:
                event = self._complete(key, state)
                if event:
                    completed.append(event)
        return completed

    def flush_camera(self, camera_id):
        completed = []
        for key, state in list(self.states.items()):
            if key[0] != camera_id:
                continue
            event = self._complete(key, state)
            if event:
                completed.append(event)
        return completed

    def _complete(self, key, state):
        self.states.pop(key, None)
        mean_confidence = state.confidence_sum / state.hits if state.hits else 0.0
        if (
            state.hits < self.min_hits
            or mean_confidence < self.min_confidence
            or state.best_crop is None
        ):
            return None
        return state.finish(self.expected.get(state.camera_id))
