import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from . import crud, health_monitor, integrations, models
from .db import Base, SessionLocal, engine
from .routers import alerts, audit, cameras, detections

app = FastAPI(title="Netra — CCTV Integration Platform API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(cameras.router)
app.include_router(detections.router)
app.include_router(alerts.router)
app.include_router(audit.router)

SNAP_DIR = os.getenv("SNAPSHOT_DIR", "/snapshots")
os.makedirs(SNAP_DIR, exist_ok=True)
app.mount("/snapshots", StaticFiles(directory=SNAP_DIR), name="snapshots")

# Ingest status is surfaced (never masked). There is NO synthetic fallback:
# if the live government feed is unreachable, the registry stays empty and the
# real error is reported via /api/health so the failure is visible, not hidden.
INGEST = {"cameras": 0, "error": None, "source": None}


def init_db():
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
    Base.metadata.create_all(bind=engine)


def ingest_cameras():
    import time as _t

    from .live_ingest import LIVE_BASE, get_mapped_live

    db = SessionLocal()
    try:
        existing = db.query(models.Camera).count()
        if existing > 0:
            INGEST["cameras"] = existing
            INGEST["source"] = "live.sentinelgujarat.in"
            print(f"[ingest] skipped (existing={existing})")
            return
        last_err = None
        for attempt in range(1, 6):
            try:
                rows = get_mapped_live()
                result = crud.upsert_missing(db, rows)
                INGEST["cameras"] = result.inserted
                INGEST["error"] = None
                INGEST["source"] = LIVE_BASE
                print(f"[ingest] onboarded {result.inserted} LIVE cameras")
                return
            except Exception as e:  # noqa: BLE001
                last_err = e
                print(f"[ingest] attempt {attempt} failed: {e}")
                _t.sleep(3)
        # No fallback: fail loudly, keep the real error visible.
        INGEST["error"] = f"Live feed unreachable: {last_err}"
        INGEST["cameras"] = 0
        print(f"[ingest] FAILED — {INGEST['error']}")
    finally:
        db.close()


def seed_watchlist():
    db = SessionLocal()
    try:
        integrations.seed_watchlist(db)
    finally:
        db.close()


@app.on_event("startup")
def on_startup():
    init_db()
    ingest_cameras()
    seed_watchlist()
    if INGEST["cameras"] > 0:
        health_monitor.start()


@app.get("/api/health")
def health():
    return {
        "status": "ok" if INGEST["cameras"] > 0 else "degraded",
        "service": "netra-api",
        "camera_source": INGEST["source"],
        "cameras": INGEST["cameras"],
        "ingest_error": INGEST["error"],
    }


@app.post("/api/ingest/retry")
def ingest_retry():
    """Manually re-attempt live onboarding (e.g. after a network blip)."""
    ingest_cameras()
    return health()
