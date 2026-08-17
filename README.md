# Netra — Unified CCTV Integration & Intelligence Platform

Prototype for the **Gujarat Police Innovation Challenge 2026**.
Hybrid architecture: **Model 1 (Registry + GIS)** + **Model 3 (VMS Federation)** + selective **Model 4 (AI Analytics)**.

See [PLAN.md](PLAN.md), [HLD.md](HLD.md), [SCALABILITY.md](SCALABILITY.md) for the design.

## Quick start

```bash
docker compose up --build
```

- Frontend (command center): http://localhost:5173
- Backend API + docs: http://localhost:8000/docs
- API health: http://localhost:8000/api/health

On first startup the backend onboards the **31 real cameras** from the live
government feed (`live.sentinelgujarat.in`). **There is no synthetic fallback** —
if the live feed is unreachable it retries, then reports the real error via
`GET /api/health` (`ingest_error`) and the UI shows a red banner with a "Retry
onboarding" action. Nothing fake is ever substituted.

## Status (build slices)

- [x] **S0** Scaffold + docker-compose (PostGIS, Redis, FastAPI, React)
- [x] **S1** Camera Registry + GIS map (Model 1) — filters, popups
- [x] **S1b** Real feed ingestion — 31 live CSITMS cameras from
      `live.sentinelgujarat.in` via adapter (`POST /api/ingest/live`), auto on
      startup. Real fields stored verbatim; coordinates geocoded from location
      text and flagged approximate (`coords_approx`); category inferred
      (`dept_inferred`)
- [x] **S2** Stream gateway + video wall — ffmpeg gateway remuxes/transcodes
      MKV/AVI → browser MP4; wall shows all 31 with lazy-play (on-screen tiles
      stream, off-screen paused); click-to-enlarge modal. (Cams 6 & 22 return
      HTTP 500 at the source — shown as "unavailable".)
- [x] **S3** Analytics worker — YOLOv8 vehicle detection + dedicated YOLO
      license-plate detector + EasyOCR + vehicle colour, overlay masking, and
      daytime seek. Live detections panel. *Note: plate OCR yield is near-zero on
      these wide-angle overview feeds (plates ~20–120px, below OCR floor) — a
      source-camera limitation, documented; pipeline is ready for ANPR-grade
      feeds.*
- [x] **S4** Hybrid cross-camera tracking — `/api/track` matches by plate (ANPR)
      or vehicle type + colour (attribute), returns a time-ordered cross-camera
      route. Tracking view: search → route on map + movement-history timeline.
- [x] **S7** Space-time single-vehicle tracker — `/api/track/vehicle`
      reconstructs one vehicle's most-plausible trajectory from a start sighting
      using attribute match + **spatio-temporal reachability gating** (haversine
      inter-camera distance vs feasible travel time). Per-hop gap/distance/speed;
      rejects physically impossible jumps. UI: single-vehicle toggle.
- [x] **S5** Real feed-derived alerts — **congestion** (per-camera vehicle count
      over threshold) and **traffic surge** (spike vs a live EMA baseline)
      computed from the actual feeds, plus an **operator watchlist (BOLO)** that
      fires on real detections. No mock databases. Alerts view: live feed with
      kind + source badges, ACK, alert-location map, header alert badge.
      *(VAHAN/eGujCop/AFIS are real deployment integrations, documented in the
      HLD — not faked here.)*
- [x] **S6** Ops & governance — real **camera health monitor** (probes each
      stream; marks offline; raises feed-down alerts), **gap-analysis** (coverage
      %, per-district, thin-coverage, offline list), **RBAC** (role switcher;
      district-scoped cameras+stats; read-only viewers blocked from actions),
      **audit log** (track/ack/BOLO attributed to user+role), and tracking
      **route de-dup** (clean per-camera path with sighting counts).

## Services

| Service | Tech | Port |
|---|---|---|
| db | PostgreSQL + PostGIS | (internal) |
| redis | Redis (event bus, prototype) | (internal) |
| backend | FastAPI + SQLAlchemy + GeoAlchemy2 | 8000 |
| gateway | FastAPI + ffmpeg (MKV/AVI → browser MP4) | 8081 |
| analytics | Python worker: YOLOv8 + YOLO plate + EasyOCR | — |
| frontend | React + Vite + MapLibre | 5173 |

## UI tabs

- **Map** — GIS registry (Model 1), pins by district, click for metadata
- **Video Wall** — all 31 live feeds, lazy-play, click-to-enlarge
- **Tracking** — hybrid plate/attribute search → cross-camera route + timeline
- **Alerts** — real congestion/surge + operator BOLO, ACK, alert map
- **Ops** — coverage & gap-analysis + audit log
- Header: **role switcher** (RBAC) · live **detections** panel (right)

## Key API

- Registry: `GET/POST /api/cameras`, `POST /api/cameras/bulk`, `GET /api/stats`,
  `GET /api/gap-analysis`, `POST /api/ingest/retry`
- Analytics: `POST /api/detections`, `GET /api/detections[/stats]`, `POST /api/frame`
- Tracking: `GET /api/track?plate=|vehicle_type=&color=`
- Alerts: `GET /api/alerts[/stats]`, `POST /api/alerts/{id}/ack`, `GET/POST /api/watchlist`
- Governance: `GET /api/audit`, `GET /api/health` (reports `ingest_error`)
- RBAC via `X-User` / `X-Role` / `X-Scope` request headers

## Data integrity

- Cameras come **only** from the live government feed. No synthetic fallback —
  a failed onboard surfaces the real error (health `ingest_error` + UI banner).
- Alerts are computed from **real feed analytics** (congestion/surge) + operator
  BOLOs. No fabricated database records.
- Derived fields are flagged: `coords_approx` (geocoded location),
  `dept_inferred` (category). ANPR plate-reads are limited by the wide-angle
  source cameras' resolution — documented, not masked.
