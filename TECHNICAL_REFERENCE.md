# Netra - Technical Reference (v0.1)

नेत्र · CCTV Integration & Intelligence Platform
Gujarat Police Innovation Challenge 2026

A federation layer that unifies independent camera systems into one registry, one
viewing surface, and one real-time analytics stream - **without replacing the
systems already deployed**.

> This is the at-a-glance technical reference. For the full design rationale,
> deployment topology and scale analysis, see [HLD.md](HLD.md); for the endpoint
> contract see [API.md](API.md) and [SCALABILITY.md](SCALABILITY.md).

**Stack:** FastAPI (Python) · Postgres + PostGIS · Redis Streams ·
YOLOv8 / EasyOCR / ByteTrack · React + Vite + MapLibre · Docker Compose

---

## 1. System overview

Independent camera sources are pulled in through per-system adapters, normalised
into one canonical registry, and analysed live by a CPU-only computer-vision
worker. The backend is the single source of truth; the console reads only from it.

```
 Sources            Ingestion             Platform core                 Clients
 --------           ---------             -------------                 -------
 Gujarat CSITMS  →  Adapters          →   FastAPI backend           →   Ops console
 (HLS/HTTP)         (discover →            (registry · alerts ·          (React +
 Independent RTSP   canonical schema)      tracking · auth)              Vite +
 (via MediaMTX)     Analytics worker       Postgres + PostGIS            MapLibre)
 Manual / CSV       (detect, track)        Redis Streams (event bus)
                                           Object storage (evidence)
```

The analytics worker posts per-track detections and per-frame vehicle counts back
to the backend over an authenticated **service token**; the gateway service
transcodes source streams for browser playback. **No component talks to the
database except the backend.**

---

## 2. Components

| Service     | Role                                                                                          | Tech |
|-------------|-----------------------------------------------------------------------------------------------|------|
| `backend`   | Owns registry, alert engine, tracking, auth/RBAC and all reads. Only writer to Postgres.      | FastAPI, SQLAlchemy, GeoAlchemy2 |
| `analytics` | Pulls active streams, runs vehicle + plate detection and tracking, emits tracks/frame counts. | OpenCV, Ultralytics YOLO, EasyOCR, ByteTrack |
| `db`        | Canonical registry and event store; PostGIS `geography` backs GIS queries.                    | postgis/postgis:16-3.4 |
| `gateway`   | ffmpeg gateway that adapts source streams (RTSP/HLS) for browser playback.                    | ffmpeg |
| `mediamtx`  | Stands up the independent second system - local RTSP paths for cross-origin federation.       | bluenviron/mediamtx |
| `frontend`  | Operations console: registry map, viewing, detections, tracking, calibration, audit.          | React 18, Vite, MapLibre GL |

---

## 3. Federation model

Every integration implements `CameraSourceAdapter`: a `discover()` method returns
rows the base class validates against `REQUIRED_CAMERA_FIELDS`
(`camera_id`, `name`, `stream_url`) and stamps with provenance -
`source_system`, `source_adapter`, `external_id`.

`source_system` identifies the independent domain and stays stable even if the
endpoint URL changes, so a camera is never double-counted or orphaned when a feed
moves.

| adapter    | source_system            | kind             | Role |
|------------|--------------------------|------------------|------|
| `csitms`   | Gujarat CSITMS           | `csitms_api`     | Government control-room catalogue; discovered from its API, not hard-coded. |
| `rtsp`     | Independent RTSP System  | `rtsp_catalogue` | Self-standing RTSP/ONVIF deployment - proof that federation spans separate origins. |
| `registry` | Manual / CSV             | `manual`         | Operator-onboarded cameras and bulk CSV import. |

Adapters run at startup and on demand via `POST /api/ingest/retry`. A failing
source is surfaced through `/api/health` with its real error - the registry is
never backfilled with synthetic cameras to hide an outage.

---

## 4. Data model (core tables)

| table              | Holds                | Notable columns |
|--------------------|----------------------|-----------------|
| `cameras`          | Canonical registry   | `geom` (PostGIS), `source_system`, `external_id`, `health_status`, lifecycle (`installed_at`, `next_service_at`, `eol_at`, `amc_expiry`) |
| `detection_events` | Every completed track| `event_type` anpr·vehicle, `plate_norm`, `vehicle_type`/`color`, `track_uuid`/`track_hits`, `snapshot`, `first_seen`/`last_seen` |
| `alerts`           | Operational alerts   | `kind` congestion·surge·watchlist·cloned_plate·feed_offline, `reason`, `severity`, `acknowledged`, `snapshot` |
| `watchlist`        | Representative BOLO   | `kind` plate·attribute·person, `plate_norm`, `min_confidence`, `min_track_hits`, `case_ref` |
| `camera_baselines` | Alert calibration    | `ema`, `sample_count`, `peak`, `congestion_threshold` override, `buckets` (per-daypart JSON) |
| `users`            | Operators            | `password_hash` (pbkdf2), `role`, `scope` (district) |
| `audit_log`        | Tamper-evident trail | `user`, `role`, `action`, `detail`, `ts` |

---

## 5. Analytics pipeline

The worker keeps up to `MAX_STREAMS` feeds active, sampling each every
`SAMPLE_EVERY` seconds. RTSP is forced over TCP (`rtsp_transport=tcp`) through
OpenCV's FFmpeg backend; CSITMS HLS is consumed directly.

1. **Capture** - `cv2.VideoCapture(url, CAP_FFMPEG)` grabs frames from the active
   set, prioritising live RTSP origins.
2. **Vehicle detection + tracking** - YOLOv8n localises vehicles and classifies
   type; ByteTrack (a per-camera `TrackLifecycle`) assigns stable track IDs; a
   dominant-colour pass adds attributes.
3. **ANPR** - a dedicated YOLO plate detector localises plates within vehicle
   crops; EasyOCR reads them; GJ-format validation and multi-frame agreement
   reject garbage before a plate is trusted.
4. **Emit** - a completed track is posted to `POST /api/detections` with a base64
   JPEG crop; per-frame vehicle counts go to `POST /api/frame` for
   congestion/surge; a full context frame is selectively retained only when a
   match fires.

CPU-only by design. The benchmark confirmed inference cost is the bottleneck at
scale - the honest finding that justifies GPU or edge inference in deployment.

---

## 6. Alert engine

Calibrated, feed-derived, throttled - no external/mock databases.

- **Congestion** - per-camera adaptive threshold: once warmed,
  `max(floor, baseline × factor)`, so a busy junction doesn't alert at its normal
  load and a quiet lane still trips at the floor.
- **Surge** - a spike above the learned EMA baseline, judged against the **current
  daypart's** baseline (night / morning / afternoon / evening) so a normal rush
  hour isn't a false spike. Baselines persist across restarts.
- **Watchlist** - operator BOLO by plate or by attribute (type + colour), gated on
  detector, class and colour confidence plus a minimum track-hit count.
- **Cloned plate** - real-time federation check: the same plate read at two
  cameras faster than physically possible raises a high-severity alert,
  cross-system aware, throttled per plate.
- **Governance** - every alert carries a decodable evidence frame; identical
  frames are deduplicated; repeat alerts on one camera are time-throttled.

---

## 7. API surface

| Method | Path                              | Purpose |
|--------|-----------------------------------|---------|
| POST   | `/api/auth/login`                 | Password → signed JWT |
| GET    | `/api/cameras`                    | Registry, district-scoped by role |
| GET    | `/api/gap-analysis`               | Coverage, offline feeds, lifecycle completeness |
| GET    | `/api/adapters`                   | Configured source systems & status |
| POST   | `/api/detections`                 | Worker track → event *(service token)* |
| POST   | `/api/frame`                      | Per-frame count → congestion/surge *(service token)* |
| GET    | `/api/track`                      | Cross-camera route by plate (fuzzy) or attribute |
| GET    | `/api/track/vehicle`              | Single-vehicle trajectory, spatio-temporal gate |
| GET    | `/api/alerts`                     | Operational alerts feed |
| GET    | `/api/alerts/baselines`           | Per-camera calibration state |
| GET    | `/api/evidence/{key}`             | Authenticated evidence-frame proxy |
| GET    | `/api/reports/readiness`          | Live Model 1-3 evaluation |
| GET    | `/api/health`                     | Ingest status & real source errors |

---

## 8. Security & governance

- **Identity from a signed token.** Roles and district scope come from verified
  HS256 JWTs; a client cannot self-assign a role via headers. The worker
  authenticates with a separate service token that alone may write detections.
- **Evidence is access-controlled.** Frames live in a private object-storage
  bucket, served only through the authenticated `/api/evidence` proxy - never a
  public URL.
- **No mock data.** Detections and alerts derive from real analytics on live
  feeds; an unreachable source fails loud through `/api/health` rather than being
  masked.
- **Representative data is labelled.** Watchlists and asset-lifecycle metadata
  that can't be queried from this environment are clearly marked as
  representative - never presented as live government records.
- **Every privileged action is audited.** Track queries, alert acks and BOLO
  changes are recorded with the acting user and role.
