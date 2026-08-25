"""Hybrid ANPR + attribute pipeline.

Stage 1: YOLOv8n detects vehicles (type) and we compute a dominant colour.
Stage 2: a dedicated YOLO license-plate detector localises plates; EasyOCR reads
         them when they carry enough pixels.

On these wide-angle traffic-overview feeds plates are often too small to OCR, so
every vehicle also carries a (type + colour) descriptor that drives attribute-
based cross-camera tracking. Overlay text bands are masked out to avoid the
camera-name / timestamp watermark polluting detection.
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone

import cv2
import easyocr
import numpy as np
from ultralytics import YOLO
from ultralytics.trackers.byte_tracker import BYTETracker
from ultralytics.utils import IterableSimpleNamespace, yaml_load
from ultralytics.utils.checks import check_yaml

DEFAULT_VEHICLE_CLASSES = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
PLATE_RE = re.compile(r"^[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{3,4}$")
ALLOW = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

PLATE_MODEL = os.getenv("PLATE_MODEL", "/app/plate.pt")
VEHICLE_MODEL = os.getenv("VEHICLE_MODEL", "yolov8n.pt")
VEHICLE_CONF = float(os.getenv("VEHICLE_CONF", "0.35"))
PLATE_CONF = float(os.getenv("PLATE_CONF", "0.30"))
PLATE_IMGSZ = int(os.getenv("PLATE_IMGSZ", "1280"))
MASK_TOP = float(os.getenv("MASK_TOP", "0.06"))  # fraction of height
MASK_BOT = float(os.getenv("MASK_BOT", "0.06"))
MIN_PLATE_W = int(os.getenv("MIN_PLATE_W", "45"))  # OCR only if wide enough
TRACKER_CONFIG = os.getenv("TRACKER_CONFIG", "bytetrack.yaml")
IST = timezone(timedelta(hours=5, minutes=30))
TIMESTAMP_RE = re.compile(
    r"(?P<day>\d{1,2})[-/.](?P<month>\d{1,2})[-/.](?P<year>20\d{2})"
    r"\D{0,5}(?P<hour>\d{1,2}):(?P<minute>\d{2})(?::(?P<second>\d{2}))?"
)


def _vehicle_classes():
    """Allow a fine-tuned model (including auto-rickshaw) without code changes."""
    raw = os.getenv("VEHICLE_CLASS_MAP_JSON")
    if not raw:
        return DEFAULT_VEHICLE_CLASSES
    parsed = json.loads(raw)
    return {int(key): str(value) for key, value in parsed.items()}


def mask_overlay(frame):
    """Black out the top/bottom bands where the timestamp / camera-name
    watermark is burned in, so it can't be detected or OCR'd as a plate."""
    h = frame.shape[0]
    f = frame.copy()
    t = int(h * MASK_TOP)
    b = int(h * MASK_BOT)
    if t:
        f[:t, :] = 0
    if b:
        f[h - b:, :] = 0
    return f


COLOR_NAMES = {
    "red": [(0, 10), (170, 180)],
    "orange": [(11, 22)],
    "yellow": [(23, 33)],
    "green": [(34, 85)],
    "blue": [(86, 128)],
    "purple": [(129, 160)],
}


def dominant_color(crop):
    if crop is None or crop.size == 0:
        return None
    h, w = crop.shape[:2]
    c = crop[h // 4 : 3 * h // 4, w // 4 : 3 * w // 4]
    if c.size == 0:
        c = crop
    hsv = cv2.cvtColor(c, cv2.COLOR_BGR2HSV)
    H, S, V = hsv[..., 0].ravel(), hsv[..., 1].ravel(), hsv[..., 2].ravel()
    v_mean = float(V.mean())
    s_mean = float(S.mean())
    if v_mean < 55:
        return "black"
    if s_mean < 45 and v_mean > 165:
        return "white"
    if s_mean < 55:
        return "silver/grey"
    sat = S > 60
    if sat.sum() < 10:
        return "silver/grey"
    hue = int(np.median(H[sat]))
    for name, ranges in COLOR_NAMES.items():
        for lo, hi in ranges:
            if lo <= hue <= hi:
                return name
    return "other"


def parse_bytetrack_rows(tracked, frame, vehicle_classes):
    """Parse Ultralytics ByteTrack's xyxy,id,score,class,index contract."""
    vehicles = []
    for row in tracked:
        if len(row) < 7:
            continue
        x1, y1, x2, y2 = [int(value) for value in row[:4]]
        track_id, confidence, cls = int(row[4]), float(row[5]), int(row[6])
        if cls not in vehicle_classes:
            continue
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(frame.shape[1], x2), min(frame.shape[0], y2)
        if x2 <= x1 or y2 <= y1:
            continue
        crop = frame[y1:y2, x1:x2]
        vehicles.append(
            {
                "box": (x1, y1, x2, y2),
                "track_id": track_id,
                "vehicle_type": vehicle_classes[cls],
                "confidence": round(confidence, 3),
                "color": dominant_color(crop),
                "crop": crop,
                "plate": None,
                "plate_confidence": None,
            }
        )
    return vehicles


class ANPR:
    def __init__(self):
        self.vehicle_classes = _vehicle_classes()
        self.vehicle = YOLO(VEHICLE_MODEL)
        self.plate = YOLO(PLATE_MODEL)
        self.reader = easyocr.Reader(["en"], gpu=False)
        tracker_path = check_yaml(TRACKER_CONFIG)
        self.tracker_args = IterableSimpleNamespace(**yaml_load(tracker_path))
        self.trackers = {}

    def _tracker(self, camera_id):
        tracker = self.trackers.get(camera_id)
        if tracker is None:
            tracker = BYTETracker(args=self.tracker_args, frame_rate=30)
            self.trackers[camera_id] = tracker
        return tracker

    def reset_tracker(self, camera_id):
        self.trackers.pop(camera_id, None)

    def read_footage_timestamp(self, frame):
        """Read the source's burned-in timestamp without treating it as a plate."""
        if frame is None or frame.size == 0:
            return None
        height = frame.shape[0]
        band = max(1, int(height * max(MASK_TOP, MASK_BOT, 0.10)))
        overlay = np.vstack((frame[:band, :], frame[-band:, :]))
        overlay = cv2.resize(overlay, None, fx=2.0, fy=2.0)
        try:
            results = self.reader.readtext(
                overlay,
                allowlist="0123456789-/:. ",
                detail=0,
                paragraph=False,
            )
        except Exception:
            return None
        text = " ".join(results)
        match = TIMESTAMP_RE.search(text)
        if not match:
            return None
        values = {key: int(value or 0) for key, value in match.groupdict().items()}
        try:
            return datetime(
                values["year"],
                values["month"],
                values["day"],
                values["hour"],
                values["minute"],
                values["second"],
                tzinfo=IST,
            )
        except ValueError:
            return None

    def _read_plate(self, crop):
        if crop is None or crop.size == 0:
            return None, 0.0
        h, w = crop.shape[:2]
        if w < MIN_PLATE_W:
            return None, 0.0
        up = cv2.resize(crop, (w * 3, h * 3))
        try:
            res = self.reader.readtext(up, allowlist=ALLOW, detail=1)
        except Exception:
            return None, 0.0
        candidates = [(text, float(conf)) for _, text, conf in res]
        # Indian plates are printed in spaced groups (GJ 01 AB 1234), so EasyOCR
        # often returns several tokens; also try their left-to-right join.
        if len(res) >= 2:
            ordered = sorted(res, key=lambda r: r[0][0][0])
            candidates.append(
                ("".join(t for _, t, _ in ordered),
                 min(float(c) for _, _, c in ordered))
            )
        best, best_score, best_conf = None, 0.0, 0.0
        for text, conf in candidates:
            t = re.sub(r"[^A-Z0-9]", "", text.upper())
            if len(t) < 6 or len(t) > 11:
                continue
            letters = sum(c.isalpha() for c in t)
            digits = sum(c.isdigit() for c in t)
            if letters < 2 or digits < 3:
                continue
            score = conf + (0.3 if PLATE_RE.match(t) else 0.0)
            if score > best_score:
                best, best_score, best_conf = t, score, conf
        return best, best_conf

    def process(self, frame, camera_id):
        masked = mask_overlay(frame)

        # Stage 1 — vehicles, with independent ByteTrack state per camera.
        vres = self.vehicle(masked, verbose=False, conf=VEHICLE_CONF)[0]
        try:
            tracked = self._tracker(camera_id).update(vres.boxes, masked)
        except (IndexError, ValueError):
            # ByteTrack can wedge on certain detection/box shapes (observed on
            # some H.265 frames). Discard the corrupted tracker state and let it
            # rebuild from the next frame rather than failing every frame.
            self.reset_tracker(camera_id)
            return []
        vehicles = parse_bytetrack_rows(tracked, frame, self.vehicle_classes)

        # Stage 2 — plates, associated to the vehicle that contains them
        pres = self.plate(
            masked, verbose=False, conf=PLATE_CONF, imgsz=PLATE_IMGSZ
        )[0]
        for pb in pres.boxes:
            px1, py1, px2, py2 = [int(v) for v in pb.xyxy[0].tolist()]
            cx, cy = (px1 + px2) // 2, (py1 + py2) // 2
            plate_crop = frame[max(0, py1):py2, max(0, px1):px2]
            plate, pconf = self._read_plate(plate_crop)
            if not plate:
                continue
            for v in vehicles:
                x1, y1, x2, y2 = v["box"]
                if x1 <= cx <= x2 and y1 <= cy <= y2:
                    v["plate"] = plate
                    v["plate_confidence"] = round(pconf, 3)
                    # Keep the whole vehicle crop as evidence. The plate crop is
                    # only an OCR input; replacing the evidence with it makes
                    # attribute matches impossible to verify visually.
                    break

        return vehicles
