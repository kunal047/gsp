"""Netra analytics worker.

Pulls real camera streams, runs the ANPR pipeline on sampled frames, and POSTs
detections to the backend. Round-robins over an active set to bound CPU on the
default (GPU-less) deployment — the statewide design pushes this to edge/regional
GPU pools (see SCALABILITY.md).
"""
import base64
import os
import time

import cv2
import requests

from anpr import ANPR

BACKEND = os.getenv("BACKEND_URL", "http://backend:8000")
MAX_STREAMS = int(os.getenv("MAX_STREAMS", "6"))
SAMPLE_EVERY = float(os.getenv("SAMPLE_EVERY", "2.5"))
MAX_DETS = int(os.getenv("MAX_DETS_PER_FRAME", "4"))
GRAB_SKIP = int(os.getenv("GRAB_SKIP", "5"))
# These 12h files start ~evening; seek into daylight where plates are legible.
SEEK_SECONDS = int(os.getenv("SEEK_SECONDS", "39600"))  # ~11h in


def get_cameras():
    r = requests.get(
        f"{BACKEND}/api/cameras",
        params={"analytics_enabled": "true"},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def encode_crop(crop, maxw=260):
    if crop is None or crop.size == 0:
        return None
    h, w = crop.shape[:2]
    if w > maxw:
        s = maxw / w
        crop = cv2.resize(crop, (maxw, max(1, int(h * s))))
    ok, buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 70])
    return base64.b64encode(buf).decode() if ok else None


def post_detection(cam, det):
    body = {
        "camera_id": cam["camera_id"],
        "event_type": "anpr" if det["plate"] else "vehicle",
        "plate": det["plate"],
        "vehicle_type": det["vehicle_type"],
        "color": det.get("color"),
        "confidence": det["confidence"],
        "plate_confidence": det["plate_confidence"],
    }
    if det["plate"]:
        snap = encode_crop(det["crop"])
        if snap:
            body["snapshot_b64"] = snap
    try:
        requests.post(f"{BACKEND}/api/detections", json=body, timeout=15)
    except Exception as e:  # noqa: BLE001
        print(f"[worker] post failed: {e}", flush=True)


def open_cap(url):
    cap = cv2.VideoCapture(url)
    if SEEK_SECONDS > 0:
        cap.set(cv2.CAP_PROP_POS_MSEC, SEEK_SECONDS * 1000)
        ok = cap.grab()
        if not ok:  # seek past end / unsupported -> restart from beginning
            cap.release()
            cap = cv2.VideoCapture(url)
    return cap


def main():
    print("[worker] loading ANPR models (YOLOv8 + EasyOCR)...", flush=True)
    anpr = ANPR()
    print("[worker] models ready", flush=True)

    cams = []
    while not cams:
        try:
            cams = get_cameras()
        except Exception as e:  # noqa: BLE001
            print(f"[worker] waiting for backend: {e}", flush=True)
        if not cams:
            time.sleep(3)

    # Only feeds a decoder can open (skip the AVI feeds that 500 at source).
    playable = [
        c for c in cams if (c.get("container") or "").lower() in ("mp4", "mkv")
    ]
    active = playable[:MAX_STREAMS]
    print(
        f"[worker] active cameras: {[c['camera_id'] for c in active]}",
        flush=True,
    )

    caps = {c["camera_id"]: open_cap(c["stream_url"]) for c in active}

    while True:
        for c in active:
            cid = c["camera_id"]
            cap = caps.get(cid)
            if cap is None or not cap.isOpened():
                caps[cid] = open_cap(c["stream_url"])
                cap = caps[cid]
            for _ in range(GRAB_SKIP):
                cap.grab()
            ok, frame = cap.read()
            if not ok or frame is None:
                cap.release()
                caps[cid] = open_cap(c["stream_url"])
                continue
            try:
                dets = anpr.process(frame)
            except Exception as e:  # noqa: BLE001
                print(f"[worker] {cid} inference error: {e}", flush=True)
                continue
            # real per-frame vehicle count -> congestion/surge analytics
            try:
                requests.post(
                    f"{BACKEND}/api/frame",
                    json={"camera_id": cid, "vehicle_count": len(dets)},
                    timeout=10,
                )
            except Exception:  # noqa: BLE001
                pass
            dets.sort(key=lambda d: (d["plate"] is None, -d["confidence"]))
            for d in dets[:MAX_DETS]:
                post_detection(c, d)
            plates = [d["plate"] for d in dets if d["plate"]]
            print(
                f"[worker] {cid} vehicles={len(dets)} plates={plates}",
                flush=True,
            )
        time.sleep(SAMPLE_EVERY)


if __name__ == "__main__":
    main()
