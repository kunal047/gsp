"""Netra analytics worker.

Pulls real camera streams, runs the ANPR pipeline on sampled frames, and POSTs
detections to the backend. Round-robins over an active set to bound CPU on the
default (GPU-less) deployment - the statewide design pushes this to edge/regional
GPU pools (see SCALABILITY.md).
"""
import base64
import json
import os
import time
from datetime import datetime, timedelta, timezone

# Force RTSP over TCP (provider integration guide requirement) before ffmpeg
# initialises. Harmless on the HLS path we use here, where RTSP:8554 and
# WebRTC:8889 are firewalled and HLS is the sanctioned fallback.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

import cv2  # noqa: E402
import requests  # noqa: E402

from anpr import ANPR  # noqa: E402
from tracking import TrackLifecycle  # noqa: E402

BACKEND = os.getenv("BACKEND_URL", "http://backend:8000")
# Service token for every backend registry read and analytics write.
BACKEND_TOKEN = os.getenv("BACKEND_TOKEN", "")
AUTH_HEADERS = {"Authorization": f"Bearer {BACKEND_TOKEN}"} if BACKEND_TOKEN else {}
MAX_STREAMS = int(os.getenv("MAX_STREAMS", "6"))
SAMPLE_EVERY = float(os.getenv("SAMPLE_EVERY", "2.5"))
GRAB_SKIP = int(os.getenv("GRAB_SKIP", "5"))
# Preserve the source's synchronized timeline by default. A shared seek can be
# configured for recorded-file testing, but must never differ per camera.
SEEK_SECONDS = int(os.getenv("SEEK_SECONDS", "0"))
TRACK_MIN_HITS = int(os.getenv("TRACK_MIN_HITS", "3"))
TRACK_MAX_MISSES = int(os.getenv("TRACK_MAX_MISSES", "3"))
TRACK_MIN_CONFIDENCE = float(os.getenv("TRACK_MIN_CONFIDENCE", "0.45"))
TIMESTAMP_RETRY_FRAMES = int(os.getenv("TIMESTAMP_RETRY_FRAMES", "12"))
# Reconnect backoff + loop/scene-cut detection (provider guide requirements).
RECONNECT_BASE = float(os.getenv("RECONNECT_BASE_SECONDS", "2"))
RECONNECT_MAX = float(os.getenv("RECONNECT_MAX_SECONDS", "30"))
LOOP_JUMP_SECONDS = float(os.getenv("LOOP_JUMP_SECONDS", "5"))


def _expected_directions():
    raw = os.getenv("CAMERA_EXPECTED_DIRECTIONS_JSON") or "{}"
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        print("[worker] invalid CAMERA_EXPECTED_DIRECTIONS_JSON; ignoring", flush=True)
        return {}


def get_cameras():
    r = requests.get(
        f"{BACKEND}/api/cameras",
        params={"analytics_enabled": "true"},
        headers=AUTH_HEADERS,
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


def post_detection(cam, det, time_source):
    box = det.get("box") or (None, None, None, None)
    body = {
        "camera_id": cam["camera_id"],
        "event_type": "anpr" if det["plate"] else "vehicle",
        "plate": det["plate"],
        "vehicle_type": det["vehicle_type"],
        "color": det.get("color"),
        "confidence": det["confidence"],
        "plate_confidence": det["plate_confidence"],
        "track_uuid": det["track_uuid"],
        "track_id": det["track_id"],
        "track_hits": det["track_hits"],
        "class_confidence": det["class_confidence"],
        "color_confidence": det["color_confidence"],
        "first_seen": det["first_seen"].isoformat(),
        "last_seen": det["last_seen"].isoformat(),
        "event_ts": det["event_ts"].isoformat(),
        "time_source": time_source,
        "direction": det["direction"],
        "dwell_seconds": det["dwell_seconds"],
        "motion_px_per_second": det["motion_px_per_second"],
        "stopped": det["stopped"],
        "wrong_way": det["wrong_way"],
        "bbox_x1": box[0],
        "bbox_y1": box[1],
        "bbox_x2": box[2],
        "bbox_y2": box[3],
    }
    # A visual detection is only operational evidence when its crop exists.
    # Skip it before the API call if encoding fails; the backend independently
    # enforces the same invariant.
    snap = encode_crop(det["crop"])
    if not snap:
        return
    body["snapshot_b64"] = snap
    try:
        response = requests.post(
            f"{BACKEND}/api/detections", json=body, headers=AUTH_HEADERS, timeout=15
        )
        response.raise_for_status()
        result = response.json()
        alert_ids = result.get("alert_ids") or []
        if alert_ids:
            context = encode_crop(det.get("evidence"), maxw=960)
            if context:
                evidence_response = requests.post(
                    f"{BACKEND}/api/detections/{result['id']}/evidence",
                    json={
                        "camera_id": cam["camera_id"],
                        "alert_ids": alert_ids,
                        "snapshot_b64": context,
                    },
                    headers=AUTH_HEADERS,
                    timeout=15,
                )
                evidence_response.raise_for_status()
    except Exception as e:  # noqa: BLE001
        print(f"[worker] post failed: {e}", flush=True)


def get_source_state(cam):
    source = (cam.get("source") or "").rstrip("/")
    provider_id = cam["camera_id"].split("-")[-1].lstrip("0") or "0"
    if not source:
        return {}
    try:
        response = requests.get(
            f"{source}/api/cameras/{provider_id}/state",
            headers={"User-Agent": "netra/0.1"},
            timeout=15,
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:  # noqa: BLE001
        print(f"[worker] {cam['camera_id']} source clock unavailable: {exc}", flush=True)
        return {}


def open_cap(url, seek_seconds=0):
    # Explicit FFmpeg backend for both RTSP (rtsp_transport;tcp already forced via
    # OPENCV_FFMPEG_CAPTURE_OPTIONS) and HLS. Live RTSP is never seekable.
    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    if url.startswith("rtsp://"):
        return cap
    if seek_seconds > 0:
        cap.set(cv2.CAP_PROP_POS_MSEC, seek_seconds * 1000)
        ok = cap.grab()
        if not ok:  # seek past end / unsupported -> restart from beginning
            cap.release()
            cap = cv2.VideoCapture(url)
    return cap


def main():
    print("[worker] loading ANPR models (YOLOv8 + EasyOCR)...", flush=True)
    anpr = ANPR()
    lifecycle = TrackLifecycle(
        min_hits=TRACK_MIN_HITS,
        max_misses=TRACK_MAX_MISSES,
        min_confidence=TRACK_MIN_CONFIDENCE,
        expected=_expected_directions(),
    )
    print("[worker] models ready", flush=True)

    cams = []
    while not cams:
        try:
            cams = get_cameras()
        except Exception as e:  # noqa: BLE001
            print(f"[worker] waiting for backend: {e}", flush=True)
        if not cams:
            time.sleep(3)

    # HLS (ffmpeg) decodes every codec the catalogue offers (H.264 and H.265),
    # so we no longer gate on container; just skip cameras the catalogue reports
    # as not live.
    playable = [c for c in cams if c.get("health_status") != "offline"]
    # Independent RTSP feeds (and analytics-flagged cameras) take priority in the
    # active set so the controlled ANPR source is always analysed.
    playable.sort(
        key=lambda c: (
            not str(c.get("stream_url") or "").startswith("rtsp://"),
            not c.get("analytics_enabled"),
        )
    )
    active = playable[:MAX_STREAMS]
    print(
        f"[worker] active cameras: {[c['camera_id'] for c in active]}",
        flush=True,
    )

    source_states = {}

    def resolve_media(cam):
        """Fetch the source clock and choose the LIVE HLS URL. The progressive
        /stream/{id} MP4 is a ~1.3 GB non-faststart file the provider no longer
        serves for playback; the media server exposes a synchronized HLS live
        edge instead. Returns (url, seek_seconds)."""
        cid = cam["camera_id"]
        # Independent RTSP system (local MediaMTX or a whitelisted provider RTSP):
        # consume the catalogue's rtsp:// URL directly as a live camera - no state
        # API, no seek. Event timing falls back to the PTS-anchored clock.
        stream_url = cam.get("stream_url") or ""
        if stream_url.startswith("rtsp://"):
            source_states[cid] = {}
            return stream_url, 0.0
        state = get_source_state(cam)
        base = (cam.get("source") or "").rstrip("/")
        hls = state.get("hls_live_url")
        if hls and base:
            # Live edge: our media clock starts at 0 and maps to the provider's
            # wall_time, so pin slot_offset to 0 and never seek a live stream.
            state["slot_offset"] = 0.0
            source_states[cid] = state
            return base + hls, 0.0
        source_states[cid] = state
        seek = (
            float(SEEK_SECONDS)
            if SEEK_SECONDS > 0
            else float(state.get("slot_offset") or 0.0)
        )
        return cam["stream_url"], seek

    caps = {}
    for c in active:
        url, seek = resolve_media(c)
        caps[c["camera_id"]] = open_cap(url, seek)
    media_positions = {}
    timestamp_anchors = {}
    timestamp_attempts = {}
    reconnect_delay = {}  # cid -> current backoff seconds
    next_retry_at = {}  # cid -> monotonic time before which we don't retry

    def schedule_reconnect(cid):
        delay = min(reconnect_delay.get(cid, RECONNECT_BASE), RECONNECT_MAX)
        next_retry_at[cid] = time.monotonic() + delay
        reconnect_delay[cid] = min(delay * 2, RECONNECT_MAX)

    def reset_camera_state(cid):
        media_positions.pop(cid, None)
        timestamp_anchors.pop(cid, None)
        timestamp_attempts.pop(cid, None)
    configured_start = os.getenv("FOOTAGE_START_ISO")
    configured_start_dt = (
        datetime.fromisoformat(configured_start) if configured_start else None
    )

    def media_position(cid, cap):
        # Timing is PTS-driven (CAP_PROP_POS_MSEC), never arrival time. A large
        # backward PTS jump means the looping recording cut to its start.
        reported = max(0.0, cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0)
        previous = media_positions.get(cid, reported)
        looped = reported + LOOP_JUMP_SECONDS < previous
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        if reported > previous or looped:
            current = reported
        else:
            current = previous + (GRAB_SKIP + 1) / max(1.0, fps)
        media_positions[cid] = current
        return current, looped

    def event_clock(cid, frame, media_seconds):
        source_state = source_states.get(cid) or {}
        wall_time = source_state.get("wall_time")
        slot_offset = source_state.get("slot_offset")
        if wall_time and slot_offset is not None:
            try:
                wall_dt = datetime.fromisoformat(wall_time)
                return (
                    wall_dt + timedelta(seconds=media_seconds - float(slot_offset)),
                    "source_clock",
                )
            except (TypeError, ValueError):
                pass
        attempts = timestamp_attempts.get(cid, 0) + 1
        timestamp_attempts[cid] = attempts
        if cid not in timestamp_anchors and (
            attempts == 1 or attempts % TIMESTAMP_RETRY_FRAMES == 0
        ):
            burned_in = anpr.read_footage_timestamp(frame)
            if burned_in:
                timestamp_anchors[cid] = (burned_in, media_seconds)
                print(
                    f"[worker] {cid} footage clock anchored at {burned_in.isoformat()}",
                    flush=True,
                )
        anchor = timestamp_anchors.get(cid)
        if anchor:
            return anchor[0] + timedelta(seconds=media_seconds - anchor[1]), "burned_in"
        if configured_start_dt:
            return configured_start_dt + timedelta(seconds=media_seconds), "stream_position"
        return datetime.now(timezone.utc), "ingest"

    def post_completed(cam, events, source):
        for event in events:
            post_detection(cam, event, source)

    while True:
        for c in active:
            cid = c["camera_id"]
            cap = caps.get(cid)
            if cap is None or not cap.isOpened():
                # exponential backoff - never reconnect in a tight loop
                if time.monotonic() < next_retry_at.get(cid, 0.0):
                    continue
                url, seek = resolve_media(c)
                cap = open_cap(url, seek)
                caps[cid] = cap
                if not cap.isOpened():
                    schedule_reconnect(cid)
                    continue
            for _ in range(GRAB_SKIP):
                cap.grab()
            ok, frame = cap.read()
            if not ok or frame is None:
                # Feeds are supervised and may restart; expect brief drops.
                post_completed(c, lifecycle.flush_camera(cid), "stream_position")
                anpr.reset_tracker(cid)
                cap.release()
                caps[cid] = None
                reset_camera_state(cid)
                schedule_reconnect(cid)
                continue
            # successful read -> clear backoff
            reconnect_delay[cid] = RECONNECT_BASE
            next_retry_at.pop(cid, None)
            try:
                dets = anpr.process(frame, cid)
            except Exception as e:  # noqa: BLE001
                print(f"[worker] {cid} inference error: {e}", flush=True)
                continue
            media_seconds, looped = media_position(cid, cap)
            if looped:
                # Scene discontinuity at the loop point: recover long-lived
                # state (track ids) from a hard cut rather than bridging it.
                post_completed(c, lifecycle.flush_camera(cid), "source_clock")
                anpr.reset_tracker(cid)
                timestamp_anchors.pop(cid, None)
                print(f"[worker] {cid} scene discontinuity - trackers reset", flush=True)
                continue
            event_time, time_source = event_clock(cid, frame, media_seconds)
            completed = lifecycle.update(
                cid, dets, frame, media_seconds, event_time=event_time
            )
            # real per-frame vehicle count -> congestion/surge analytics
            try:
                frame_result = requests.post(
                    f"{BACKEND}/api/frame",
                    json={
                        "camera_id": cid,
                        "vehicle_count": len(dets),
                        "event_ts": event_time.isoformat(),
                        "time_source": time_source,
                    },
                    headers=AUTH_HEADERS,
                    timeout=10,
                )
                frame_result.raise_for_status()
                frame_result = frame_result.json()
                alert_ids = frame_result.get("alert_ids") or []
                if alert_ids:
                    # Retain a full frame only for an actual traffic alert.
                    frame_snap = encode_crop(frame, maxw=960)
                    if frame_snap:
                        requests.post(
                            f"{BACKEND}/api/frame/evidence",
                            json={
                                "camera_id": cid,
                                "alert_ids": alert_ids,
                                "snapshot_b64": frame_snap,
                            },
                            headers=AUTH_HEADERS,
                            timeout=15,
                        )
            except Exception:  # noqa: BLE001
                pass
            post_completed(c, completed, time_source)
            plates = [d["plate"] for d in dets if d["plate"]]
            print(
                f"[worker] {cid} active_tracks={len(dets)} "
                f"completed={len(completed)} plates={plates}",
                flush=True,
            )
        time.sleep(SAMPLE_EVERY)


if __name__ == "__main__":
    main()
