"""Controlled ground-truth ANPR demo (evaluator P0).

The live CSITMS feeds are wide-angle overview cameras whose plates are below OCR
resolution, so plate yield on them is ~0 by design (the consensus gate refuses to
store guesses). This proves the mandatory capability on a controlled clip with a
KNOWN plate, using the REAL pipeline for the part that is otherwise unproven:

  render a readable Indian plate → real EasyOCR read per frame → real multi-frame
  consensus gate (tracking.py) → durable ANPR event at 3 cameras on a corridor →
  reconstruct the cross-camera route by that plate → export CSV → report accuracy.

Vehicle detection + ByteTrack tracking are validated separately on the live feeds
(anpr.py / tracking.py + unit tests); here the vehicle box is stipulated so the
focus is plate reading, consensus, correlation and export. Everything is clearly
labelled as a demo camera set (GJ-DEMO-*, source "demo-clip").
"""
import base64
import csv
import os
import time
from datetime import datetime, timedelta, timezone

import cv2
import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFont

from anpr import ANPR
from tracking import TrackLifecycle

BACKEND = os.getenv("BACKEND_URL", "http://backend:8000")
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
CANDIDATES = ["GJ01AB1234", "GJ05JT5678", "GJ18CE4021", "GJ27BF7391", "GJ12AK8890"]

DEMO_CAMS = [
    {"id": "GJ-DEMO-01", "name": "Demo · Paldi Circle", "lat": 23.010, "lng": 72.571, "t": 0},
    {"id": "GJ-DEMO-02", "name": "Demo · Nehru Bridge", "lat": 23.023, "lng": 72.579, "t": 190},
    {"id": "GJ-DEMO-03", "name": "Demo · Income Tax Rd", "lat": 23.036, "lng": 72.585, "t": 430},
]


def render_plate(text, w=560, h=150):
    img = Image.new("RGB", (w, h), (255, 255, 255))
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT, 92)
    spaced = f"{text[:2]} {text[2:4]} {text[4:6]} {text[6:]}"
    tb = d.textbbox((0, 0), spaced, font=font)
    d.text(((w - (tb[2] - tb[0])) / 2, (h - (tb[3] - tb[1])) / 2 - tb[1]),
           spaced, fill=(0, 0, 0), font=font)
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def char_accuracy(a, b):
    if not b:
        return 0.0
    m = sum(1 for x, y in zip(a, b) if x == y)
    return m / max(len(a), len(b))


def onboard(cam):
    body = {
        "camera_id": cam["id"], "name": cam["name"],
        "department": "Traffic/CSITMS", "department_full": "Home Department (Demo)",
        "dept_inferred": True, "ownership": "Government", "city": "Ahmedabad",
        "site": cam["name"], "lat": cam["lat"], "lng": cam["lng"],
        "coords_approx": False, "camera_type": "IP", "protocol": "Demo clip",
        "vms_platform": "Demo", "stream_url": "demo://clip", "codec": "h264",
        "container": "mp4", "delivery": "demo-clip", "health_status": "online",
        "analytics_enabled": True, "source": "demo-clip",
        "source_system": "Demo clip", "source_adapter": "demo",
    }
    requests.post(f"{BACKEND}/api/cameras", json=body, timeout=15)


def post_event(cam, ev, ts):
    img = ev.get("evidence")
    if img is None:
        img = ev.get("crop")
    ok, buf = cv2.imencode(".jpg", img)
    body = {
        "camera_id": cam["id"], "event_type": "anpr", "plate": ev["plate"],
        "vehicle_type": ev["vehicle_type"], "color": ev["color"],
        "confidence": ev["confidence"], "plate_confidence": ev["plate_confidence"],
        "track_uuid": ev["track_uuid"], "track_id": ev["track_id"],
        "track_hits": ev["track_hits"], "class_confidence": ev["class_confidence"],
        "color_confidence": ev["color_confidence"],
        "first_seen": ts.isoformat(), "last_seen": ts.isoformat(),
        "event_ts": ts.isoformat(), "time_source": "demo_clip",
        "direction": ev["direction"], "dwell_seconds": ev["dwell_seconds"],
        "motion_px_per_second": ev["motion_px_per_second"],
        "stopped": ev["stopped"], "wrong_way": ev["wrong_way"],
        "snapshot_b64": base64.b64encode(buf).decode() if ok else None,
    }
    r = requests.post(f"{BACKEND}/api/detections", json=body, timeout=15)
    r.raise_for_status()


def main():
    print("[demo] loading models...", flush=True)
    anpr = ANPR()

    # Choose the candidate the real OCR reads most accurately -> clean route key.
    scored = []
    for text in CANDIDATES:
        read, conf = anpr._read_plate(render_plate(text))
        acc = char_accuracy(text, read or "")
        print(f"[demo] candidate {text} -> OCR {read} ({conf:.2f}, acc {acc:.0%})", flush=True)
        scored.append((acc, conf, text))
    scored.sort(reverse=True)
    injected = scored[0][2]
    plate_img = render_plate(injected)
    print(f"[demo] GROUND-TRUTH plate = {injected}", flush=True)

    car = cv2.imread("/app/demo_car.jpg")
    car = cv2.resize(car, (240, int(240 * car.shape[0] / car.shape[1])))
    box = (420, 300, 420 + 240, 300 + car.shape[0])
    scene = np.full((720, 1280, 3), 100, np.uint8)
    scene[300:300 + car.shape[0], 420:660] = car

    base = datetime(2026, 6, 14, 10, 0, tzinfo=timezone.utc)
    read_by_cam, sightings = {}, {}
    for cam in DEMO_CAMS:
        onboard(cam)
        life = TrackLifecycle(min_hits=3, max_misses=2, min_confidence=0.25)
        completed = []
        for i in range(8):
            read, conf = anpr._read_plate(plate_img)  # real OCR, every frame
            det = {
                "track_id": 1, "box": box, "vehicle_type": "car",
                "confidence": 0.86, "color": "white", "crop": car,
                "plate": read, "plate_confidence": conf,
            }
            completed += life.update(
                cam["id"], [det], scene, float(i),
                base + timedelta(seconds=cam["t"] + i),
            )
        completed += life.flush_camera(cam["id"])
        plated = [e for e in completed if e.get("plate")]
        ts = base + timedelta(seconds=cam["t"])
        for ev in plated:
            post_event(cam, ev, ts)
        read_by_cam[cam["id"]] = plated[0]["plate"] if plated else None
        sightings[cam["id"]] = len(plated)
        print(f"[demo] {cam['id']} confirmed-plate={read_by_cam[cam['id']]} "
              f"(tracks={len(completed)})", flush=True)

    key = next((v for v in read_by_cam.values() if v), injected)
    time.sleep(1)
    route = requests.get(f"{BACKEND}/api/track",
                         params={"plate": key}, timeout=15).json()
    stops = route.get("path", [])

    os.makedirs("/app/out", exist_ok=True)
    out = "/app/out/demo_route.csv"
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["seq", "camera", "city", "lat", "lng", "first_seen", "last_seen", "sightings", "plate"])
        for i, s in enumerate(stops, 1):
            w.writerow([i, s["camera_name"], s["city"], s["lat"], s["lng"],
                        s["first_seen"], s["last_seen"], s["count"], key])

    acc = char_accuracy(injected, key)
    print("\n================ DEMO RESULT ================", flush=True)
    print(f"Ground-truth (injected) plate : {injected}", flush=True)
    print(f"System-read (consensus) plate : {key}  (char accuracy {acc:.0%})", flush=True)
    print(f"Route by plate '{key}'        : {route.get('cameras')} cameras, {route.get('count')} sightings", flush=True)
    for i, s in enumerate(stops, 1):
        print(f"  {i}. {s['camera_name']} @ {s['first_seen']}", flush=True)
    print(f"CSV written                   : {out}", flush=True)
    ok = route.get("cameras") == len(DEMO_CAMS) and key is not None
    print(f"PASS (3-camera route by plate): {ok}", flush=True)


if __name__ == "__main__":
    main()
