"""Netra Stream Gateway.

Makes heterogeneous source feeds browser-playable without touching the source
system — the Model 3 "adapter / stream gateway" component, realised with ffmpeg.

- `c=copy`  : remux only (h264-in-MKV/MP4). Cheap, no re-encode.
- `c=x264`  : transcode to H.264 (AVI / unknown codecs). Heavier; used only
              for the handful of feeds a browser cannot decode natively.

Output is fragmented MP4 streamed progressively to a <video> element. A child
ffmpeg is spawned per active viewer and killed when the client disconnects.
"""
import os
import subprocess

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

LIVE_BASE = os.getenv("LIVE_BASE", "https://live.sentinelgujarat.in")

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
