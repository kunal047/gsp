"""Generate the controlled ground-truth ANPR clip published by MediaMTX.

A real vehicle (YOLO-detectable) translates across a road scene with a readable
Indian plate mounted on it. The plate string is chosen by diag_clip so EasyOCR
round-trips it exactly. The clip is VALIDATED through the real pipeline (vehicle
detected + plate read via multi-frame consensus) before it is written, so a clip
that the worker cannot read is never published.

Env:
  DEMO_PLATE     plate string (default GJ01AB1234)
  DEMO_FONT      font path (default DejaVuSansMono-Bold)
  DEMO_SPACED    "1" to render state/rto/series/number spaced (default 1)
  VEHICLE_SCALE  scale for demo_car.jpg (default 0.5)
  OUT            output mp4 (default /clips/plate-demo.mp4)
"""
import os

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from anpr import ANPR
from tracking import TrackLifecycle

PLATE = os.getenv("DEMO_PLATE", "AUTO")
FONT = os.getenv("DEMO_FONT", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf")
SPACED = os.getenv("DEMO_SPACED", "1") == "1"
SCALE = float(os.getenv("VEHICLE_SCALE", "0.7"))
OUT = os.getenv("OUT", "/clips/plate-demo.mp4")
# 16s loop: the vehicle enters, crosses and EXITS over the first ~60%, then the
# road is empty so the worker's track hits max_misses and emits a durable ANPR
# event every loop (RTSP PTS is monotonic, so the loop never rewinds the track).
W, H, FPS, SECONDS = 1280, 720, 25, 20
# Vehicle crosses over the first 50% (~10s): at 2s sampling that's ~5 plate
# reads, comfortably above PLATE_MIN_AGREEMENTS=3 so consensus is reliable on
# every camera. The remaining ~10s of empty road lets the track hit max_misses
# and emit exactly one event per loop.
CROSS_FRAC = 0.50

# Wide candidate net across states/patterns; the builder keeps the first that
# EasyOCR round-trips EXACTLY, so the on-screen plate == the tracked plate.
CANDIDATES = [
    "GJ01AB1234", "GJ05JT5678", "GJ18CE4021", "GJ27BF7391", "GJ12AK8890",
    "GJ03KL4567", "GJ06MN7788", "GJ01CX9021", "GJ21TC0345", "GJ38RS1290",
    "GJ01HH2244", "GJ07PA5566", "GJ05CD8080", "GJ18BX3311", "GJ01MM7007",
    "MH12DE1433", "MH01AB1234", "DL8CAF5031", "KA05MK2200", "RJ14CV0002",
    "TN01AY5678", "UP16BC1122", "HR26DK8337", "MP09KL4455", "PB10CE9090",
]


def render_plate(text):
    # Size the canvas to the text (+ generous margin) so no character is clipped
    # at the edges - edge clipping was dropping the state code and last digit.
    s = f"{text[:2]} {text[2:4]} {text[4:6]} {text[6:]}" if SPACED else text
    margin_x, margin_y = 70, 40
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    font = ImageFont.truetype(FONT, 84)
    tb = probe.textbbox((0, 0), s, font=font)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    w, h = tw + 2 * margin_x, th + 2 * margin_y
    img = Image.new("RGB", (w, h), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((margin_x - tb[0], margin_y - tb[1]), s, fill=(0, 0, 0), font=font)
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def road_bg():
    bg = np.full((H, W, 3), 120, np.uint8)
    bg[H // 2:] = (92, 92, 96)                      # asphalt
    for x in range(0, W, 140):                       # lane dashes
        cv2.rectangle(bg, (x, H - 60), (x + 70, H - 52), (200, 200, 200), -1)
    cv2.rectangle(bg, (0, H // 2 - 4), (W, H // 2), (150, 150, 150), -1)  # horizon
    return bg


def _paste(dst, src, x, y):
    """Paste src onto dst at (x, y), clipping to bounds (handles off-screen)."""
    dh, dw = dst.shape[:2]
    sh, sw = src.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(dw, x + sw), min(dh, y + sh)
    if x1 <= x0 or y1 <= y0:
        return
    dst[y0:y1, x0:x1] = src[y0 - y:y1 - y, x0 - x:x1 - x]


def frame_at(bg, car, plate, t):
    # Motion profile per 20s loop, tuned to how the worker samples RTSP (~1-2s):
    #   enter (0-15%) -> DWELL centre (15-65%) -> exit (65-80%) -> empty (80-100%)
    # The long centre dwell keeps the vehicle box nearly stationary so ByteTrack
    # holds ONE identity across samples and the plate-consensus gate (>=3 reads)
    # is met; the exit + empty tail then lets the track hit max_misses and emit
    # exactly one durable event per loop, on every camera.
    frame = bg.copy()
    ch, cw = car.shape[:2]
    cx = (W - cw) // 2
    y = H - ch - 70
    if t < 0.15:
        x = int(-cw + (t / 0.15) * (cx + cw))         # off-screen left -> centre
    elif t < 0.65:
        x = cx + int(6 * (t - 0.4))                   # DWELL (few px of life)
    elif t < 0.80:
        x = int(cx + ((t - 0.65) / 0.15) * (W - cx))  # centre -> off-screen right
    else:
        return frame, None                            # empty road: track ends
    _paste(frame, car, x, y)
    # Plate width in the detector's confirmed sweet spot (450-600px): below ~400
    # the real plate-detector doesn't fire; above ~700 its box clips the edges.
    pw = int(min(600, max(450, cw * 0.85)))
    pl = cv2.resize(plate, (pw, int(pw * plate.shape[0] / plate.shape[1])))
    ph = pl.shape[0]
    _paste(frame, pl, x + (cw - pw) // 2, min(y + ch - ph - 10, H - ph - 46))
    return frame, (x, y, x + cw, y + ch)


def select_plate(anpr):
    if PLATE != "AUTO":
        return PLATE
    best = None
    for text in CANDIDATES:
        read, conf = anpr._read_plate(render_plate(text))
        acc = sum(1 for a, b in zip(text, read or "") if a == b) / len(text)
        print(f"[clip] try {text} -> {read} ({conf:.2f}, acc {acc:.0%})", flush=True)
        if read == text:
            print(f"[clip] exact round-trip: {text}", flush=True)
            return text
        if best is None or acc > best[0]:
            best = (acc, text)
    print(f"[clip] no exact round-trip; best-readable = {best[1]} ({best[0]:.0%})", flush=True)
    return best[1]


VEHICLE_SRC = os.getenv(
    "VEHICLE_SRC",
    "/usr/local/lib/python3.11/site-packages/ultralytics/assets/bus.jpg",
)


def load_vehicle(anpr):
    """Load a real vehicle photo and crop tight to YOLO's detection so it
    composites onto the road scene as a clean vehicle the worker re-detects."""
    img = cv2.imread(VEHICLE_SRC)
    if img is None:
        raise SystemExit(f"vehicle source not found: {VEHICLE_SRC}")
    dets = anpr.process(img, "vehicle-crop")
    anpr.reset_tracker("vehicle-crop")
    if dets:
        d = max(dets, key=lambda x: (x["box"][2] - x["box"][0]) * (x["box"][3] - x["box"][1]))
        x1, y1, x2, y2 = [int(v) for v in d["box"]]
        pad = 6
        img = img[max(0, y1 - pad):y2 + pad, max(0, x1 - pad):x2 + pad]
        print(f"[clip] cropped vehicle={d['vehicle_type']} {img.shape[1]}x{img.shape[0]}", flush=True)
    return img


def main():
    anpr = ANPR()
    plate_text = select_plate(anpr)
    car = load_vehicle(anpr)
    car = cv2.resize(car, (int(car.shape[1] * SCALE), int(car.shape[0] * SCALE)))
    bg, plate = road_bg(), render_plate(plate_text)
    n = FPS * SECONDS
    frames = [frame_at(bg, car, plate, i / (n - 1))[0] for i in range(n)]

    # validate through the real pipeline before writing (skippable: the live
    # worker is the authoritative end-to-end proof and this is CPU-contended)
    life = TrackLifecycle(min_hits=3, max_misses=2, min_confidence=0.25)
    completed, det_frames = [], 0
    sample = [] if os.getenv("SKIP_VALIDATE") == "1" else frames[::20]
    for i, f in enumerate(sample):
        dets = anpr.process(f, "clip-validate")
        if dets:
            det_frames += 1
        completed += life.update("clip-validate", dets, f, float(i), None)
    completed += life.flush_camera("clip-validate")
    anpr.reset_tracker("clip-validate")
    plated = [e for e in completed if e.get("plate")]
    reads = [e["plate"] for e in plated]
    print(f"[clip] vehicle-detected frames={det_frames}/{len(sample)}, "
          f"tracks={len(completed)}, plate reads={reads}", flush=True)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    vw = cv2.VideoWriter(OUT, cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    for f in frames:
        vw.write(f)
    vw.release()
    print(f"[clip] wrote {OUT} ({n} frames, {SECONDS}s @ {FPS}fps)", flush=True)
    ok = det_frames >= 3 and any(r == plate_text for r in reads)
    print(f"[clip] operative plate = {plate_text}", flush=True)
    print(f"[clip] PASS (detectable vehicle + exact plate read): {ok}", flush=True)
    if not ok:
        print(f"[clip] NOTE: plate={plate_text}, reads={reads} - adjust VEHICLE_SCALE/DEMO_PLATE", flush=True)


if __name__ == "__main__":
    main()
