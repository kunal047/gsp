"""One-shot diagnostic: find a (font, plate-string) that EasyOCR round-trips
exactly, and confirm YOLO detects the demo vehicle reliably. Informs the clip."""
import glob
import os

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from anpr import ANPR

CANDIDATES = [
    "GJ01AB1234", "GJ05JT5678", "GJ18CE4021", "GJ27BF7391", "GJ12AK8890",
    "GJ03KL4567", "GJ06MN7788", "GJ01CX9021", "GJ21TC0345", "GJ38RS1290",
    "MH12DE1433", "DL8CAF5031", "KA05MK2200", "GJ01HH2244", "GJ07PA5566",
]
FONTS = sorted(set(
    glob.glob("/usr/share/fonts/**/*Mono*Bold*.ttf", recursive=True)
    + glob.glob("/usr/share/fonts/**/*Sans*Bold*.ttf", recursive=True)
    + glob.glob("/usr/share/fonts/**/DejaVu*.ttf", recursive=True)
))[:6]


def render(text, font_path, size=110, spaced=True):
    s = f"{text[:2]} {text[2:4]} {text[4:6]} {text[6:]}" if spaced else text
    w, h = 640, 180
    img = Image.new("RGB", (w, h), (255, 255, 255))
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(font_path, size)
    tb = d.textbbox((0, 0), s, font=font)
    d.text(((w - (tb[2] - tb[0])) / 2, (h - (tb[3] - tb[1])) / 2 - tb[1]),
           s, fill=(0, 0, 0), font=font)
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def main():
    anpr = ANPR()
    print(f"[diag] fonts: {[os.path.basename(f) for f in FONTS]}", flush=True)

    exact = []
    for font in FONTS:
        for spaced in (False, True):
            hits = []
            for text in CANDIDATES:
                read, conf = anpr._read_plate(render(text, font, spaced=spaced))
                if read == text:
                    hits.append((text, round(conf, 2)))
            tag = "spaced" if spaced else "solid"
            print(f"[diag] {os.path.basename(font):28s} {tag:6s} exact={hits}", flush=True)
            for text, conf in hits:
                exact.append((font, spaced, text, conf))

    print("\n[diag] === YOLO vehicle detection on demo_car.jpg ===", flush=True)
    car = cv2.imread("/app/demo_car.jpg")
    if car is not None:
        for scale, place in [(1.0, "full"), (0.5, "half"), (0.35, "third")]:
            frame = np.full((720, 1280, 3), 110, np.uint8)
            frame[520:] = (90, 90, 92)
            c = cv2.resize(car, (int(car.shape[1] * scale), int(car.shape[0] * scale)))
            ch, cw = c.shape[:2]
            x, y = (1280 - cw) // 2, min(300, 720 - ch)
            frame[y:y + ch, x:x + cw] = c
            dets = anpr.process(frame, f"diag-{place}")
            anpr.reset_tracker(f"diag-{place}")
            print(f"[diag] car {place:6s} ({cw}x{ch}) -> {len(dets)} vehicle(s): "
                  f"{[(d['vehicle_type'], round(d['confidence'],2)) for d in dets]}", flush=True)

    if exact:
        f, sp, t, c = exact[0]
        print(f"\n[diag] BEST: plate={t} font={os.path.basename(f)} spaced={sp} conf={c}", flush=True)
    else:
        print("\n[diag] NO exact round-trip; will use closest + report accuracy", flush=True)


if __name__ == "__main__":
    main()
