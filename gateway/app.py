"""Netra Stream Gateway.

Makes heterogeneous source feeds browser-playable without touching the source
system - the Model 3 "adapter / stream gateway" component, realised with ffmpeg.

- `c=copy`  : remux only (h264-in-MKV/MP4). Cheap, no re-encode.
- `c=x264`  : transcode to H.264 (AVI / unknown codecs). Heavier; used only
              for the handful of feeds a browser cannot decode natively.

Output is fragmented MP4 streamed progressively to a <video> element. A child
ffmpeg is spawned per active viewer and killed when the client disconnects.
"""
import os
import subprocess
import threading
import time
import json
import urllib.parse
import urllib.request

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse

LIVE_BASE = os.getenv("LIVE_BASE", "https://live.corp8.cloud")
BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000").rstrip("/")
SNAPSHOT_TTL = float(os.getenv("SNAPSHOT_TTL", "6"))

app = FastAPI(title="Netra Stream Gateway")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FRAG = "frag_keyframe+empty_moov+default_base_moof"


def _ffmpeg_cmd(src: str, mode: str):
    base = ["ffmpeg", "-loglevel", "error", "-fflags", "+genpts", "-i", src, "-an"]
    if mode == "copy":
        vid = ["-c:v", "copy"]
    else:
        vid = ["-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
               "-pix_fmt", "yuv420p", "-g", "50"]
    return base + vid + ["-movflags", FRAG, "-f", "mp4", "pipe:1"]


@app.get("/health")
def health():
    return {"status": "ok", "service": "netra-gateway"}


# --- Snapshot wall: one refreshed JPEG per camera, so all cameras can be
# viewed at once without decoding N live 1080p streams in the browser. ffmpeg
# decodes any codec (incl. H.265), and a short TTL cache bounds the load.
_snap_cache: dict[object, tuple[float, bytes]] = {}
_snap_locks: dict[object, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(cam_id: object) -> threading.Lock:
    with _locks_guard:
        lk = _snap_locks.get(cam_id)
        if lk is None:
            lk = threading.Lock()
            _snap_locks[cam_id] = lk
        return lk


def _grab_snapshot(cam_id: int):
    hls = f"{LIVE_BASE}/live/stream/{cam_id}/index.m3u8"
    cmd = [
        "ffmpeg", "-loglevel", "error", "-rw_timeout", "15000000",
        "-i", hls, "-frames:v", "1", "-q:v", "6",
        "-f", "image2", "-c:v", "mjpeg", "pipe:1",
    ]
    try:
        out = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=25
        ).stdout
        return out or None
    except Exception:
        return None


def _jpeg(data: bytes) -> Response:
    return Response(
        content=data,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-cache"},
    )


def _registered_source(camera_id: str) -> str:
    """Resolve only backend-registered feeds; never accept arbitrary URLs."""
    encoded = urllib.parse.quote(camera_id, safe="")
    headers = {"User-Agent": "netra-gateway"}
    token = os.getenv("BACKEND_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"{BACKEND_URL}/api/cameras/{encoded}",
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            camera = json.load(response)
    except Exception as error:
        raise HTTPException(status_code=404, detail="registered camera unavailable") from error
    source = camera.get("stream_url")
    if not source:
        raise HTTPException(status_code=409, detail="camera has no stream URL")
    return source


def _grab_source_snapshot(source: str):
    cmd = [
        "ffmpeg", "-loglevel", "error", "-rw_timeout", "15000000",
        "-i", source, "-frames:v", "1", "-q:v", "6",
        "-f", "image2", "-c:v", "mjpeg", "pipe:1",
    ]
    try:
        output = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=25
        ).stdout
        return output or None
    except Exception:
        return None


@app.get("/gateway/camera/{camera_id}/snapshot")
def registered_snapshot(camera_id: str):
    key = f"registered:{camera_id}"
    cached = _snap_cache.get(key)
    if cached and time.time() - cached[0] < SNAPSHOT_TTL:
        return _jpeg(cached[1])
    with _lock_for(key):
        cached = _snap_cache.get(key)
        if cached and time.time() - cached[0] < SNAPSHOT_TTL:
            return _jpeg(cached[1])
        data = _grab_source_snapshot(_registered_source(camera_id))
        if not data:
            if cached:
                return _jpeg(cached[1])
            raise HTTPException(status_code=503, detail="snapshot unavailable")
        _snap_cache[key] = (time.time(), data)
        return _jpeg(data)


@app.get("/gateway/camera/{camera_id}/stream")
def registered_stream(camera_id: str, c: str = "copy"):
    mode = "copy" if c == "copy" else "x264"
    proc = subprocess.Popen(
        _ffmpeg_cmd(_registered_source(camera_id), mode),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=0,
    )

    def generate():
        try:
            while True:
                chunk = proc.stdout.read(65536)
                if not chunk:
                    break
                yield chunk
        finally:
            proc.kill()
            proc.wait()

    return StreamingResponse(generate(), media_type="video/mp4")


@app.get("/gateway/snapshot/{cam_id}")
def gateway_snapshot(cam_id: int):
    cached = _snap_cache.get(cam_id)
    if cached and time.time() - cached[0] < SNAPSHOT_TTL:
        return _jpeg(cached[1])
    with _lock_for(cam_id):
        cached = _snap_cache.get(cam_id)
        if cached and time.time() - cached[0] < SNAPSHOT_TTL:
            return _jpeg(cached[1])
        data = _grab_snapshot(cam_id)
        if not data:
            if cached:  # serve last good frame on a transient failure
                return _jpeg(cached[1])
            raise HTTPException(status_code=503, detail="snapshot unavailable")
        _snap_cache[cam_id] = (time.time(), data)
        return _jpeg(data)


@app.get("/gateway/stream/{cam_id}")
def gateway_stream(cam_id: int, c: str = "copy"):
    mode = "copy" if c == "copy" else "x264"
    src = f"{LIVE_BASE}/stream/{cam_id}"
    proc = subprocess.Popen(
        _ffmpeg_cmd(src, mode),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=0,
    )

    def gen():
        try:
            while True:
                chunk = proc.stdout.read(65536)
                if not chunk:
                    break
                yield chunk
        finally:
            proc.kill()
            proc.wait()

    return StreamingResponse(gen(), media_type="video/mp4")
