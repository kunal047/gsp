import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from . import crud, health_monitor, integrations, models
from .db import Base, SessionLocal, engine
from .routers import alerts, audit, cameras, detections, reports

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
app.include_router(reports.router)

SNAP_DIR = os.getenv("SNAPSHOT_DIR", "/snapshots")
os.makedirs(SNAP_DIR, exist_ok=True)
app.mount("/snapshots", StaticFiles(directory=SNAP_DIR), name="snapshots")
SERVERLESS = os.getenv("NETRA_SERVERLESS") == "1" or bool(os.getenv("VERCEL"))

# Ingest status is surfaced (never masked). There is NO synthetic fallback:
# if the live government feed is unreachable, the registry stays empty and the
# real error is reported via /api/health so the failure is visible, not hidden.
INGEST = {"cameras": 0, "error": None, "source": None, "adapters": []}


def init_db():
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
    Base.metadata.create_all(bind=engine)


def ingest_cameras():
    import time as _t

    from .adapters import configured_adapters
    from .live_ingest import LIVE_BASE

    db = SessionLocal()
    try:
        legacy_base = "https://live.sentinelgujarat.in"
        legacy_rows = (
            db.query(models.Camera)
            .filter(models.Camera.stream_url.like(f"{legacy_base}/%"))
            .all()
        )
        for camera in legacy_rows:
            camera.stream_url = camera.stream_url.replace(legacy_base, LIVE_BASE, 1)
            camera.source = LIVE_BASE
        if legacy_rows:
            db.commit()

        statuses = []
        errors = []
        for adapter in configured_adapters():
            last_error = None
            for attempt in range(1, 4):
                try:
                    result = adapter.result()
                    persisted = crud.upsert_missing(db, result.cameras)
                    statuses.append({
                        **adapter.describe(),
                        "discovered": len(result.cameras),
                        "inserted": persisted.inserted,
                        "status": "ready",
                    })
                    print(
                        f"[ingest] {adapter.key}: {len(result.cameras)} discovered, "
                        f"{persisted.inserted} inserted"
                    )
                    last_error = None
                    break
                except Exception as error:  # noqa: BLE001
                    last_error = error
                    if attempt < 3:
                        _t.sleep(2)
            if last_error is not None:
                message = f"{adapter.key}: {last_error}"
                errors.append(message)
                statuses.append({
                    **adapter.describe(),
                    "discovered": 0,
                    "inserted": 0,
                    "status": "unreachable",
                    "error": str(last_error),
                })
                print(f"[ingest] FAILED — {message}")

        INGEST["cameras"] = db.query(models.Camera).count()
        INGEST["adapters"] = statuses
        INGEST["source"] = ", ".join(
            status["source_system"] for status in statuses
            if status["status"] == "ready"
        ) or None
        INGEST["error"] = "; ".join(errors) or None
    finally:
        db.close()


def seed_watchlist():
    db = SessionLocal()
    try:
        integrations.seed_watchlist(db)
    finally:
        db.close()


def refresh_registry_state():
    """Hydrate process-local health state from the shared registry."""
    db = SessionLocal()
    try:
        existing = db.query(models.Camera).count()
        INGEST["cameras"] = existing
        if existing:
            systems = [
                row[0]
                for row in db.query(models.Camera.source_system).distinct().all()
                if row[0]
            ]
            INGEST["source"] = ", ".join(systems) or "Supabase camera registry"
        elif SERVERLESS:
            INGEST["error"] = "No cameras onboarded yet; use Retry onboarding when the source is reachable."
    finally:
        db.close()


@app.on_event("startup")
def on_startup():
    init_db()
    seed_watchlist()
    refresh_registry_state()
    if not SERVERLESS:
        ingest_cameras()
    if INGEST["cameras"] > 0 and not SERVERLESS:
        health_monitor.start()


@app.get("/api/health")
def health():
    refresh_registry_state()
    return {
        "status": "ok" if INGEST["cameras"] > 0 else "degraded",
        "service": "netra-api",
        "camera_source": INGEST["source"],
        "cameras": INGEST["cameras"],
        "ingest_error": INGEST["error"],
        "adapters": INGEST["adapters"],
    }


@app.post("/api/ingest/retry")
def ingest_retry():
    """Manually re-attempt live onboarding (e.g. after a network blip)."""
    ingest_cameras()
    return health()
