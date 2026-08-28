"""Find a plate rendering + size the real plate-detector fires on, in-scene."""
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from anpr import ANPR, PLATE_CONF, PLATE_IMGSZ, mask_overlay
import build_clip as bc

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"


def plate_plain(text):
    return bc.render_plate(text)


def plate_ind(text, yellow=False):
    """Realistic single-row Indian plate: optional IND blue strip + border."""
    s = f"{text[:2]} {text[2:4]} {text[4:6]} {text[6:]}"
    bg = (0, 200, 255) if yellow else (255, 255, 255)  # BGR-ish via PIL RGB below
    W0, H0 = 760, 160
    img = Image.new("RGB", (W0, H0), (255, 255, 0) if yellow else (255, 255, 255))
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT, 96)
    strip = 70
    d.rectangle([0, 0, strip, H0], fill=(0, 40, 160))            # blue IND strip
    d.text((14, 44), "IND", fill=(255, 255, 255), font=ImageFont.truetype(FONT, 34))
    tb = d.textbbox((0, 0), s, font=font)
    d.text((strip + (W0 - strip - (tb[2] - tb[0])) / 2, (H0 - (tb[3] - tb[1])) / 2 - tb[1]),
           s, fill=(0, 0, 0), font=font)
    d.rectangle([1, 1, W0 - 2, H0 - 2], outline=(0, 0, 0), width=4)
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def scene_with_plate(anpr, plate, pw):
    car = bc.load_vehicle(anpr)
    car = cv2.resize(car, (int(car.shape[1] * bc.SCALE), int(car.shape[0] * bc.SCALE)))
    bg = bc.road_bg()
    frame = bg.copy()
    ch, cw = car.shape[:2]
    x, y = (bc.W - cw) // 2, bc.H - ch - 70
    frame[y:y + ch, x:x + cw] = car
    pl = cv2.resize(plate, (pw, int(pw * plate.shape[0] / plate.shape[1])))
    ph = pl.shape[0]
    px, py = (bc.W - pw) // 2, y + ch - ph - 12
    py = min(py, bc.H - ph - 46)  # keep clear of bottom mask
    frame[py:py + ph, px:px + pw] = pl
    return frame


def detect(anpr, frame, tag):
    masked = mask_overlay(frame)
    pres = anpr.plate(masked, verbose=False, conf=PLATE_CONF, imgsz=PLATE_IMGSZ)[0]
    boxes = pres.boxes
    out = []
    for pb in boxes:
        x1, y1, x2, y2 = [int(v) for v in pb.xyxy[0].tolist()]
        crop = frame[max(0, y1):y2, max(0, x1):x2]
        read, rconf = anpr._read_plate(crop) if crop.size else (None, 0)
        out.append((round(float(pb.conf[0]), 2), read, round(rconf, 2)))
    print(f"[probe] {tag}: {len(boxes)} box(es) {out}", flush=True)


def main():
    anpr = ANPR()
    styles = {"plain": plate_plain("GJ01AB1234"),
              "ind": plate_ind("GJ01AB1234"),
              "yellow": plate_ind("GJ01AB1234", yellow=True)}
    for name, plate in styles.items():
        for pw in (300, 450, 600, 780):
            detect(anpr, scene_with_plate(anpr, plate, pw), f"{name} pw={pw}")


if __name__ == "__main__":
    main()
