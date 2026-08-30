import os
import time

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from . import auth, crud, health_monitor, integrations, models, seed_assets
from .db import Base, SessionLocal, engine
from .routers import alerts, audit, auth as auth_router, cameras, detections, evidence, reports
from .rbac import principal, require_actor

app = FastAPI(title="Netra - CCTV Integration Platform API", version="0.1.0")

allowed_origins = [
    origin.strip()
    for origin in os.getenv(
        "NETRA_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(cameras.router, dependencies=[Depends(principal)])
app.include_router(detections.router, dependencies=[Depends(principal)])
app.include_router(evidence.router)
app.include_router(alerts.router, dependencies=[Depends(principal)])
app.include_router(audit.router, dependencies=[Depends(principal)])
app.include_router(reports.router, dependencies=[Depends(principal)])

SNAP_DIR = os.getenv("SNAPSHOT_DIR", "/snapshots")
os.makedirs(SNAP_DIR, exist_ok=True)
app.mount("/snapshots", StaticFiles(directory=SNAP_DIR), name="snapshots")
SERVERLESS = os.getenv("NETRA_SERVERLESS") == "1" or bool(os.getenv("VERCEL"))

# Ingest status is surfaced (never masked). There is NO synthetic fallback:
# if the live government feed is unreachable, the registry stays empty and the
# real error is reported via /api/health so the failure is visible, not hidden.
INGEST = {"cameras": 0, "error": None, "source": None, "adapters": []}


def init_db():
    attempts = int(os.getenv("DB_STARTUP_ATTEMPTS", "15"))
    delay = float(os.getenv("DB_STARTUP_DELAY_SECONDS", "2"))
    for attempt in range(1, attempts + 1):
        try:
            with engine.begin() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
            Base.metadata.create_all(bind=engine)
            return
        except Exception:  # noqa: BLE001
            if attempt == attempts:
                raise
            print(f"[startup] database unavailable ({attempt}/{attempts}); retrying", flush=True)
            time.sleep(delay)


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
                print(f"[ingest] FAILED - {message}")

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


def seed_users():
    db = SessionLocal()
    try:
        auth.seed_users(db)
    finally:
        db.close()


def load_baselines():
    db = SessionLocal()
    try:
        loaded = integrations.load_baselines(db)
        print(f"[alerts] hydrated {loaded} persisted camera baseline(s)")
    finally:
        db.close()


def start_baseline_flusher():
    """Periodically persist dirty baselines off the hot ingest path."""
    import threading
    import time as _t

    interval = int(os.getenv("BASELINE_FLUSH_SECONDS", "5"))

    def loop():
        while True:
            _t.sleep(interval)
            db = SessionLocal()
            try:
                integrations.flush_dirty(db)
            except Exception as exc:  # noqa: BLE001
                print(f"[alerts] baseline flusher error: {exc}")
            finally:
                db.close()

    threading.Thread(target=loop, daemon=True).start()


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
    seed_users()
    load_baselines()
    refresh_registry_state()
    if not SERVERLESS:
        ingest_cameras()
        db = SessionLocal()
        try:
            filled = seed_assets.seed_asset_lifecycle(db)
            print(f"[assets] seeded representative lifecycle for {filled} camera(s)")
        finally:
            db.close()
    if INGEST["cameras"] > 0 and not SERVERLESS:
        health_monitor.start()
    if not SERVERLESS:
        start_baseline_flusher()


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
def ingest_retry(_=Depends(require_actor)):
    """Manually re-attempt live onboarding (e.g. after a network blip)."""
    ingest_cameras()
    return health()
