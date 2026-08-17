"""Hybrid ANPR + attribute pipeline.

Stage 1: YOLOv8n detects vehicles (type) and we compute a dominant colour.
Stage 2: a dedicated YOLO license-plate detector localises plates; EasyOCR reads
         them when they carry enough pixels.

On these wide-angle traffic-overview feeds plates are often too small to OCR, so
every vehicle also carries a (type + colour) descriptor that drives attribute-
based cross-camera tracking. Overlay text bands are masked out to avoid the
camera-name / timestamp watermark polluting detection.
"""
import os
import re

import cv2
import easyocr
import numpy as np
from ultralytics import YOLO

VEHICLE = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
PLATE_RE = re.compile(r"^[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{3,4}$")
ALLOW = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

PLATE_MODEL = os.getenv("PLATE_MODEL", "/app/plate.pt")
VEHICLE_CONF = float(os.getenv("VEHICLE_CONF", "0.35"))
PLATE_CONF = float(os.getenv("PLATE_CONF", "0.30"))
PLATE_IMGSZ = int(os.getenv("PLATE_IMGSZ", "1280"))
MASK_TOP = float(os.getenv("MASK_TOP", "0.06"))  # fraction of height
MASK_BOT = float(os.getenv("MASK_BOT", "0.06"))
MIN_PLATE_W = int(os.getenv("MIN_PLATE_W", "45"))  # OCR only if wide enough


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


class ANPR:
    def __init__(self):
        self.vehicle = YOLO("yolov8n.pt")
        self.plate = YOLO(PLATE_MODEL)
        self.reader = easyocr.Reader(["en"], gpu=False)

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
        best, best_c = None, 0.0
        for _, text, conf in res:
            t = re.sub(r"[^A-Z0-9]", "", text.upper())
            if len(t) < 6 or len(t) > 11:
                continue
            letters = sum(c.isalpha() for c in t)
            digits = sum(c.isdigit() for c in t)
            if letters < 2 or digits < 3:
                continue
            score = float(conf) + (0.3 if PLATE_RE.match(t) else 0.0)
            if score > best_c:
                best, best_c = t, float(conf)
        return best, best_c

    def process(self, frame):
        masked = mask_overlay(frame)

        # Stage 1 — vehicles
        vres = self.vehicle(masked, verbose=False, conf=VEHICLE_CONF)[0]
        vehicles = []
        for b in vres.boxes:
            cls = int(b.cls[0])
            if cls not in VEHICLE:
                continue
            x1, y1, x2, y2 = [int(v) for v in b.xyxy[0].tolist()]
            x1, y1 = max(0, x1), max(0, y1)
            crop = frame[y1:y2, x1:x2]
            vehicles.append(
                {
                    "box": (x1, y1, x2, y2),
                    "vehicle_type": VEHICLE[cls],
                    "confidence": round(float(b.conf[0]), 3),
                    "color": dominant_color(crop),
                    "crop": crop,
                    "plate": None,
                    "plate_confidence": None,
                }
            )

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
                    v["crop"] = plate_crop  # snapshot the plate
                    break

        return vehicles
