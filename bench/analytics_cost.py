"""Measure the real analytics per-feed cost (runs inside the analytics container).

Times the full ANPR pipeline (YOLOv8 vehicle + YOLO plate detector + EasyOCR)
on a representative frame, then derives how many feeds one worker sustains at the
SCALABILITY.md sampling rate. This is CPU (this host); the doc's per-GPU numbers
follow from the measured per-frame cost times a GPU speed-up.
"""
import os
import statistics
import time

import cv2

from anpr import ANPR

FPS = float(os.getenv("BENCH_FPS", "5"))          # sampling rate per feed
ITERS = int(os.getenv("BENCH_ITERS", "40"))
CLIP = os.getenv("BENCH_CLIP", "/clips/plate-demo.mp4")


def load_frame():
    cap = cv2.VideoCapture(CLIP)
    cap.set(cv2.CAP_PROP_POS_FRAMES, 120)             # a frame with vehicle + plate
    ok, frame = cap.read()
    cap.release()
    if not ok:
        import numpy as np
        frame = (np.random.rand(720, 1280, 3) * 255).astype("uint8")
    return frame


def main():
    print("[cost] loading ANPR models...", flush=True)
    anpr = ANPR()
    frame = load_frame()

    # warm-up (model graph / allocator)
    for _ in range(3):
        anpr.process(frame, "cost-warmup")
    anpr.reset_tracker("cost-warmup")

    times = []
    for i in range(ITERS):
        t0 = time.perf_counter()
        anpr.process(frame, "cost")
        times.append((time.perf_counter() - t0) * 1000)
    anpr.reset_tracker("cost")

    times.sort()
    mean = statistics.mean(times)
    p95 = times[min(len(times) - 1, int(len(times) * 0.95))]
    fps_cpu = 1000.0 / mean
    feeds_per_worker = fps_cpu / FPS

    print("\n[cost] === ANALYTICS PER-FEED COST (CPU, this host) ===", flush=True)
    print(f"[cost] full ANPR pipeline per frame: mean {mean:.0f}ms  p95 {p95:.0f}ms", flush=True)
    print(f"[cost] one CPU worker: {fps_cpu:.1f} frames/s -> "
          f"{feeds_per_worker:.1f} feeds @ {FPS}fps sampling", flush=True)
    for label, mult in [("CPU (measured)", 1), ("GPU ~10x (L4/A10 class)", 10),
                        ("GPU ~15x", 15)]:
        print(f"[cost]   {label:26s}: ~{feeds_per_worker * mult:5.0f} feeds/worker", flush=True)

    import json
    out = {
        "per_frame_ms_mean": round(mean, 1), "per_frame_ms_p95": round(p95, 1),
        "cpu_frames_per_sec": round(fps_cpu, 1), "sampling_fps": FPS,
        "feeds_per_worker_cpu": round(feeds_per_worker, 1),
        "feeds_per_worker_gpu_10x": round(feeds_per_worker * 10),
        "iterations": ITERS,
    }
    with open("/clips/bench_analytics.json", "w") as f:
        json.dump(out, f, indent=2)
    print("[cost] wrote /clips/bench_analytics.json", flush=True)


if __name__ == "__main__":
    main()
