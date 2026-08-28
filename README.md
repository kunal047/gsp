# Netra - Unified CCTV Integration & Intelligence Platform

Prototype for the **Gujarat Police Innovation Challenge 2026**.
Hybrid architecture: **Model 1 (Registry + GIS)** + **Model 2 (Unified Viewing & Metadata Analytics)** + **Model 3 (VMS Federation)**, with selective AI analytics.

See [PLAN.md](PLAN.md), [HLD.md](HLD.md), [SCALABILITY.md](SCALABILITY.md) for the design.

## Quick start

Copy `.env.example` to `.env`, set `DATABASE_URL`, generate a unique
`NETRA_JWT_SECRET`, and issue `BACKEND_SERVICE_TOKEN` with that same secret for
the internal gateway and analytics services. The service token should carry
`role=state_admin`, `sub=analytics-service`, and an appropriate expiry. Then run:

```bash
docker compose up --build
```

- Frontend (command center): http://localhost:5173
- Backend API + docs: http://localhost:8000/docs
- API health: http://localhost:8000/api/health

The UI opens on the login screen. Seed-user passwords come from
`SEED_ADMIN_PASSWORD`, `SEED_OFFICER_PASSWORD`, and `SEED_VIEWER_PASSWORD` in
`.env`; change all three before any shared deployment.

On first startup the backend onboards the real cameras currently published by
the government feed (`live.corp8.cloud`; 30 at last verification). **There is no synthetic fallback** -
if the live feed is unreachable it retries, then reports the real error via
`GET /api/health` (`ingest_error`) and the UI shows a red banner with a "Retry
onboarding" action. Nothing fake is ever substituted.

### Persistent database

Supabase is the primary persistent database. Copy `.env.example` to `.env` and
replace `DATABASE_URL` with the project's Postgres connection URI.
The backend accepts standard `postgresql://` URLs and uses a bounded,
health-checked SQLAlchemy connection pool.

For Supabase, enable the **PostGIS** extension before the first startup. Copy the
connection URI from **Project → Connect**: use the direct URI on an IPv6-capable
long-running host, or the session-pooler URI on an IPv4-only host. Append
`?sslmode=require`, URL-encode special characters in the password, keep the URI
only in `.env`, then rebuild the backend.

Database evolution is tracked in `supabase/migrations`; apply pending changes
with `supabase db push --linked` before rebuilding the backend.

**Evidence object storage.** Detection/alert evidence images are stored in a
**private Supabase Storage bucket** (`evidence`, S3-class object storage), not on
the container's local disk - so evidence survives redeploys and is shared across
replicas. Upload/serve go through the stdlib (`backend/app/storage.py`, no extra
dependency); the bucket is private, so images are reached only through the
backend's **authenticated proxy** `GET /api/evidence/{key}?t=<jwt>` (a token is
required because `<img>` tags can't send an Authorization header). Set
`SUPABASE_URL` + `SUPABASE_PUBLISHABLE_KEY` and `STORAGE_BACKEND=supabase`; a
scoped RLS policy grants the publishable key insert/select on just this bucket.
Without those, it falls back to the local `snapshots` volume automatically.

Visual detections are evidence-gated: the API stores a detection only after its
snapshot has been persisted to storage successfully, and the database requires a
non-empty snapshot reference. Legacy metadata-only detections are kept outside
the operational timeline in a recovery archive.

The old local PostGIS service remains available only as an explicit fallback:
set the local `DATABASE_URL` shown in `.env.example` and run
`docker compose --profile local-db up --build`. Normal startup does not create
or depend on a local database.

## Status (build slices)

- [x] **S0** Scaffold + docker-compose (PostGIS, Redis, FastAPI, React)
- [x] **S1** Camera Registry + GIS map (Model 1) - filters, popups
- [x] **S1b** Real feed ingestion - live CSITMS cameras from
      `live.corp8.cloud` via adapter (`POST /api/ingest/live`), auto on
      startup. Real fields stored verbatim; coordinates geocoded from location
      text and flagged approximate (`coords_approx`); category inferred
      (`dept_inferred`)
- [x] **S2** Stream gateway + video wall - ffmpeg gateway remuxes/transcodes
      MKV/AVI → browser MP4; wall shows all cameras with lazy-play (on-screen tiles
      stream, off-screen paused); click-to-enlarge modal. (Cams 6 & 22 return
      HTTP 500 at the source - shown as "unavailable".)
- [x] **S3** Analytics worker - YOLOv8 vehicle detection + dedicated YOLO
      license-plate detector + EasyOCR + vehicle colour, per-camera ByteTrack,
      one evidence-backed event per completed track, confidence/persistence
      gating, annotated alert evidence, and source-clock timestamps. Live
      detections panel. *Note: plate OCR yield is near-zero on
      these wide-angle overview feeds (plates ~20–120px, below OCR floor) - a
      source-camera limitation, documented; pipeline is ready for ANPR-grade
      feeds.*
- [x] **S4** Hybrid cross-camera tracking - `/api/track` matches by plate (ANPR)
      or vehicle type + colour (attribute), returns a time-ordered cross-camera
      route. Tracking view: search → route on map + movement-history timeline.
- [x] **S7** Space-time single-vehicle tracker - `/api/track/vehicle`
      reconstructs one vehicle's most-plausible trajectory from a start sighting
      using attribute match + **spatio-temporal reachability gating** (haversine
      inter-camera distance vs feasible travel time). Per-hop gap/distance/speed;
      rejects physically impossible jumps. UI: single-vehicle toggle.
- [x] **S5** Real feed-derived alerts - **congestion** (per-camera vehicle count
      over threshold) and **traffic surge** (spike vs a live EMA baseline)
      computed from the actual feeds, plus an **operator watchlist (BOLO)** that
      fires on real detections. No mock databases. Alerts view: live feed with
      kind + source badges, ACK, alert-location map, header alert badge.
      *(VAHAN/eGujCop/AFIS are real deployment integrations, documented in the
      HLD - not faked here.)*
- [x] **S6** Ops & governance - real **camera health monitor** (probes each
      stream; marks offline; raises feed-down alerts), **gap-analysis** (coverage
      %, per-district, thin-coverage, offline list), **RBAC** (role switcher;
      district-scoped cameras+stats; read-only viewers blocked from actions),
      **audit log** (track/ack/BOLO attributed to the signed-in user and verified role), and tracking
      **route de-dup** (clean per-camera path with sighting counts).
- [x] **S8** Evaluation-ready registry & evidence - searchable registry table,
      manual and CSV camera onboarding, district-scoped write enforcement,
      audited registry export, and downloadable timestamp/location movement
      reports for plate or vehicle-attribute searches.
- [x] **Model 1 asset lifecycle** - installation/service/EOL metadata,
      maintenance-state API, ageing/incomplete-metadata gap metrics and CSV export.
- [x] **Model 3 two-system federation** - typed CSITMS and RTSP source adapters,
      canonical provenance, per-system federation report. **Now demonstrated
      end-to-end with a real second system:** a local **MediaMTX** RTSP server
      (`infra/mediamtx/`) publishes a controlled Indian-plate clip on three
      corridor cameras; the analytics worker consumes them over **live RTSP**
      (`cv2.CAP_FFMPEG`, `rtsp_transport;tcp`, PTS timing) exactly as physical
      cameras. The same vehicle (**GJ01AB1234**) is read at all three, and
      `/api/track?plate=` reconstructs the cross-camera route. Federation report
      shows both systems with `demonstration_gap: null`.
- [x] **Readable-plate ANPR proof** - the controlled clip (`analytics/build_clip.py`)
      composites a real YOLO-detectable vehicle with a plate the OCR round-trips
      exactly, validating the full onboard → detect → read (multi-frame
      consensus) → cross-camera route → CSV path that the wide-angle live feeds
      can't exercise. This is the ANPR-grade complement to the live CSITMS feeds.

## Services

| Service | Tech | Port |
|---|---|---|
| db | PostgreSQL + PostGIS | (internal) |
| redis | Redis (event bus, prototype) | (internal) |
| backend | FastAPI + SQLAlchemy + GeoAlchemy2 | 8000 |
| gateway | FastAPI + ffmpeg (MKV/AVI → browser MP4) | 8081 |
| analytics | Python worker: YOLOv8 + YOLO plate + EasyOCR | - |
| frontend | React + Vite + MapLibre | 5173 |

## UI tabs

- **Map** - GIS registry (Model 1), pins by district, click for metadata
- **Registry** - search/filter inventory, manual + CSV onboarding, provenance,
  health and analytics metadata, RBAC-gated actions, CSV export
- **Video Wall** - all onboarded feeds, lazy-play, click-to-enlarge
- **Tracking** - hybrid plate/attribute search → cross-camera route + timeline
  + downloadable timestamped movement-evidence report
- **Watchlist** - searchable case registry, plate/attribute matching rules, RBAC-managed entries
- **Alerts** - real congestion/surge + operator BOLO, ACK, alert map
  - Click an alert for its retained evidence snapshot, nearby-detection timeline,
    and the current federated camera stream. Video remains at the source VMS.
  - Watchlist matches and congestion/surge alerts retain one full context frame
    only when the alert fires; the small object crop remains on the detection
    record. Feed-down alerts are metadata-only.
- **Ops** - live Model 1–3 evaluation-readiness checks, coverage, actionable
  asset lifecycle, federation proof/gap + audit log
- Header: signed-in identity/verified **RBAC role**, sign-out, and live
  **detections** panel (right)

## Key API

- Registry: `GET/POST /api/cameras`, `POST /api/cameras/bulk`, `GET /api/stats`,
  `PATCH /api/cameras/{id}/lifecycle`, `GET /api/gap-analysis`,
  `GET /api/adapters`, `POST /api/ingest/adapters`
- Reports: `GET /api/reports/cameras.csv`, `GET /api/reports/detections.csv`,
  `GET /api/reports/federation`, `GET /api/reports/readiness`
- Analytics: `POST /api/detections`, `GET /api/detections[/stats]`, `POST /api/frame`
- Tracking: `GET /api/track?plate=|vehicle_type=&color=`
- Alerts: `GET /api/alerts[/stats]`, `POST /api/alerts/{id}/ack`, `GET/POST /api/watchlist`
- Governance: `GET /api/audit`, `GET /api/health` (reports `ingest_error`)
- Authentication: `POST /api/auth/login` issues a signed bearer JWT;
  `GET /api/auth/me` returns the verified identity. RBAC scope and role come
  only from verified token claims. Legacy identity headers work only when the
  explicitly unsafe local-development flag `NETRA_DEV_AUTH=1` is set.

## Data integrity

- The automatically onboarded cameras come **only** from the live government
  feed. No synthetic fallback-a failed onboard surfaces the real error (health
  `ingest_error` + UI banner). Operator-added participant feeds are supported,
  clearly provenance-labelled, and recorded in the audit trail.
- Alerts are computed from **real feed analytics** (congestion/surge) + operator
  BOLOs. No fabricated database records.
- Derived fields are flagged: `coords_approx` (geocoded location),
  `dept_inferred` (category). ANPR plate-reads are limited by the wide-angle
  source cameras' resolution - documented, not masked.
