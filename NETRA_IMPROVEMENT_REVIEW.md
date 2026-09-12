# Netra — Project Review & Improvement Scope

Reviewed 12 Sep 2026 against every `*.md` in the repo (README, PLAN, HLD, SCALABILITY, API, TECHNICAL_REFERENCE, REQUIREMENTS_TRACEABILITY, bench/BENCHMARK, submission/*) and the code they describe (`backend/`, `analytics/`, `gateway/`, `frontend/`, `docker-compose.yml`, migrations).

---

## 1. Where the project actually stands

The documentation is unusually good for a hackathon codebase: the HLD separates `[built]` from `[design]`, the benchmark reports a CPU finding that *hurts* the prototype and explains why it validates the architecture, and the "never fabricate" principle is applied consistently to cameras and alerts. Judges reward that honesty, and it is the project's strongest asset. Keep it.

What is really built: a live CSITMS adapter feeding a PostGIS registry with GIS map, registry CRUD/CSV import/export and lifecycle fields; an ffmpeg gateway and lazy video wall; a CPU analytics worker (YOLOv8n → ByteTrack → YOLO plate → EasyOCR with multi-frame consensus) posting evidence-gated events; plate/attribute cross-camera tracking with a haversine space-time gate and hop metrics; congestion/surge/watchlist/cloned-plate/feed-offline alerts with calibrated baselines; JWT auth with three roles; audit log; a MediaMTX second source proving two-system federation; a measured ingestion benchmark (820 req/s).

What the docs promise that the code does not yet do is the substance of this review. The gaps cluster into five areas, ordered by how much they affect the scored test case ("given a plate, output the route + timestamped movement history across ~50 feeds").

---

## 2. The one gap that decides the scored test: analytics coverage

This is the highest-leverage problem in the repo, and it is not mentioned in any of the docs.

`analytics/worker.py` runs **one process, one thread, round-robin over `MAX_STREAMS=6` cameras**, sleeping `SAMPLE_EVERY=2 s` between cycles. `bench/BENCHMARK.md` measures the full pipeline at **~5 s per frame on CPU**. Put together, each of the 6 active cameras is sampled roughly every 30–35 s; the other 44 of 50 event-day feeds get **no analytics at all**. A vehicle crosses a wide-angle traffic camera's field of view in 3–8 s, so even on the 6 covered cameras most passes are never observed. The multi-frame plate consensus (`PLATE_MIN_AGREEMENTS=3`) then needs three *sampled* frames of the same track — which at 30 s sampling is essentially impossible on a moving vehicle. The MediaMTX corridor demo works because the clip loops; live feeds will not.

Additional defects in the same file: the camera list is fetched **once at startup** (`get_cameras()` in `main()`), so cameras onboarded during the demo are never analysed until the container restarts; one stalled `cap.read()` blocks every other camera in the loop; and every backend call inside the loop is synchronous.

What to do, in order of payoff:

1. **Shard the worker.** Make the worker accept `CAMERA_IDS` (or a shard index `WORKER_INDEX/WORKER_COUNT`) and run N replicas in compose (`deploy.replicas` or a generated compose). Add a `GET /api/cameras/assignments?worker=i&of=n` endpoint so assignment is stable and re-read every 60 s. This alone takes coverage from 6 feeds to whatever the host can run.
2. **Cut per-frame cost ~5–10× before touching GPU.** Run the plate detector on **vehicle crops only** (currently a second full-frame pass at `imgsz=1280`, the single most expensive step); skip OCR for a track once consensus is reached; skip plate detection entirely for tracks whose vehicle box is under a pixel threshold (the doc already says <100 px plates are unreadable — don't pay to find out); add a cheap frame-difference motion gate so idle cameras cost nothing.
3. **One thread per camera with a bounded inference queue**, so capture latency and inference are decoupled and a dead stream cannot stall the others.
4. **GPU path** (`easyocr.Reader(gpu=True)`, `YOLO(...).to("cuda")`, a `Dockerfile.gpu`) for the event laptop/cloud VM. The doc's 40 cameras/GPU figure is untested; measure it with `bench/analytics_cost.py` and put the real number in BENCHMARK.md.
5. **Instrument it.** Per-camera frames/s, inference ms, OCR yield, and lag — the numbers EVALUATION_SCORECARD.md wants are not being collected anywhere today (`print` only).

---

## 3. Tracking and search: correct but not yet evidence-grade

`backend/app/routers/detections.py` is the scored output. Issues, most important first:

**No time window.** `GET /api/track` has `plate | vehicle_type | color | limit` and nothing else. The judge's question is always "this plate, this afternoon." Add `since`/`until` (and ideally a district/bbox filter). Related: `limit=300` is applied after `ORDER BY ts ASC`, so once a plate has >300 sightings the *newest* ones are silently dropped — exactly the ones an operator wants.

**Fuzzy matching is done in Python over every distinct plate in the table** (`_resolve_plate_matches` pulls `SELECT DISTINCT plate_norm` and runs Levenshtein per row). Fine at 1,000 plates, not at 1M. Use Postgres `pg_trgm` (`similarity()` + GIN index) or the `fuzzystrmatch` extension. More importantly, generic edit distance is the wrong model for ANPR error: OCR confuses specific pairs (O/0, D/0, B/8, I/1, S/5, Z/2, G/6). A **confusion-class normalisation** (map both sides to a canonical class string, store it as `plate_class` with an index) gives exact-match speed with OCR-aware tolerance, and lets the UI say *why* two plates matched.

**`/track/vehicle` loads the entire attribute pool into memory** and does an O(hops × pool) scan. Add a time window and a PostGIS `ST_DWithin` pre-filter per hop so it stays fast.

**No route confidence.** Each stop should carry a match score (plate confidence × hop plausibility) and the response a whole-route confidence, so the report can honestly say "high confidence for hops 1–3, ambiguous at hop 4." That is what an investigator (and a judge) needs to trust the output.

**Movement-history report.** The CSV exists (`/api/reports/detections.csv`). Add a one-click **PDF case report** — plate, route map image, per-stop timestamp/camera/coordinates, evidence thumbnails, query audit line, SHA-256 of each evidence object. That is the artefact the challenge literally asks for ("output report of plates/timestamps") and a PDF with thumbnails demos far better than a CSV.

**Re-ID** is the documented next increment. The cheapest credible version: an appearance embedding per vehicle crop (OSNet or a CLIP image encoder, ~2 ms on GPU), stored in a `pgvector` column, used as a tie-breaker inside the existing space-time gate. It keeps the architecture (events, not video) and directly addresses the wide-angle feeds where plates fail.

---

## 4. Security and RBAC: the story is ahead of the code

The JWT work is solid (HS256, pbkdf2, constant-time compares, no header spoofing). Around it there are real holes:

| Finding | Where | Fix |
|---|---|---|
| **Gateway streams and snapshots are unauthenticated.** Anyone who can reach `:8081` can pull any registered camera. CORS does not protect direct requests. | `gateway/app.py` `registered_stream`, `registered_snapshot`, legacy `/gateway/stream/{id}` | Require the user JWT (query param `t=` like the evidence proxy, or a short-lived signed stream token minted by the backend). Remove the legacy numeric-id endpoints. |
| **Local evidence is public.** `/snapshots` is mounted as `StaticFiles` with no auth; in local-storage mode every detection crop is world-readable. | `backend/app/main.py` | Serve local files through the same `/api/evidence/{key}` proxy; drop the static mount. |
| **JWT in query string** for evidence images ends up in proxy/browser/access logs. | `routers/evidence.py` | Mint short-lived (60 s) HMAC-signed evidence URLs from the backend instead of reusing the 12-hour session token. |
| **Service token is a `state_admin` user with a long expiry.** If the analytics container leaks it, it is a full-admin credential. | `scripts/issue_service_token.py`, `rbac.require_ingestor` | Add a `service` role that can only hit `/api/detections`, `/api/frame`, `/api/cameras` (read). Rotate via env, short TTL. |
| **District scoping is inconsistent.** `cameras`, `stats`, `gap-analysis` are scoped; `detections`, `track`, `track/vehicle`, `alerts`, `alerts/{id}/evidence`, `watchlist`, `audit` are **not** — a district officer sees every district's sightings and alerts. | `routers/detections.py`, `routers/alerts.py`, `routers/audit.py` | Centralise scoping in one `scoped_cameras(p)` helper and apply it everywhere a `camera_id` is read. Add a test that asserts every router applies it. |
| **"Tamper-evident audit"** is claimed in TECHNICAL_REFERENCE §4/§8 but `AuditLog` is a plain table. | `models.AuditLog` | Add `prev_hash` + `hash` columns (hash-chain), a `GET /api/audit/verify` endpoint, and change the doc to `[built]` only when it is. |
| **Untyped request bodies** (`payload: dict`) on `/frame`, `/frame/evidence`, `/detections/{id}/evidence`, `/watchlist`, `/alerts/baselines/.../threshold`. | routers | Pydantic models; they also give you free OpenAPI docs, which the traceability matrix says you want to publish. |
| No login rate-limit, no token revocation/refresh, no password policy, default `JWT_SECRET` fallback string in `auth.py`. | `auth.py`, `routers/auth.py` | slowapi or a Redis counter on `/auth/login`; fail startup if the secret is the default. |

---

## 5. "Stateless backend behind a load balancer" is not true yet

SCALABILITY.md and BENCHMARK.md both say horizontal scaling "multiplies linearly." The code keeps critical state in process memory: `INGEST` status dict, `cache._cache`, `_evidence_seen` (alert dedup), the dirty-baseline set flushed by a thread in `main.py`, and the health-monitor thread. Run two replicas and you get two health monitors raising duplicate feed-offline alerts, two flushers racing on `camera_baselines`, and alert dedup that only works per replica.

Move the periodic jobs (health monitor, baseline flusher, adapter re-discovery) into a **separate `scheduler` service** (same image, different entrypoint), and put dedup keys + hot baselines in **Redis** (which is already in the stack). Then the API replicas really are stateless and the benchmark's claim holds.

Also: Redis Streams is written to (`bus.publish_detection`) but **nothing consumes it**. The UI polls five endpoints every 2–4 s per browser tab. Add an SSE endpoint (`GET /api/events`) that tails the stream; it removes most polling load, makes the "event bus" real rather than decorative, and gives you a live-updating video-wall/alerts demo with no client changes beyond swapping `setInterval` for `EventSource`.

---

## 6. Data integrity: two places where the "never fabricate" rule is bent

The README says "No mock databases" and the HLD principle 7 says "never fabricate," but on every startup the backend runs `seed_assets.seed_asset_lifecycle`, which assigns each government camera a **deterministic fake vendor, model, resolution, install date, EOL and AMC expiry** ("Hikvision DS-2CD2085FWD-I", "installed 2019", etc.). It is labelled in `maintenance_notes`, but a judge looking at the registry table sees a make/model column populated with brand names for real cameras. `seed_watchlist` similarly inserts representative BOLO records on first boot.

Recommendation: make both **opt-in** (`SEED_REPRESENTATIVE_ASSETS=1`, `SEED_WATCHLIST=1`, off by default), and when enabled, badge those rows in the UI ("representative") the way `coords_approx`/`dept_inferred` already are. That keeps the demo capability and removes a credibility risk that contradicts your best differentiator.

---

## 7. Engineering hygiene that will bite during Phase 2 / a real PoC

**Schema management runs on two tracks.** The backend does `Base.metadata.create_all()` plus a hand-written `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, while `supabase/migrations/` holds four SQL migrations. Pick Alembic (generate from the models, commit the SQL), and stop calling `create_all` at startup.

**Indexes.** `detection_events` has single-column indexes only. The tracking queries need `(plate_norm, ts)`, `(vehicle_type, color, ts)`, `(camera_id, ts)`. There is no retention job for events or evidence objects — at 0.5 events/s/camera the table grows unbounded; add a nightly purge/archive by `ts` (or Timescale hypertable + retention policy, which the docs already mention).

**Tests and CI.** 19 test functions, no `.github/`, no lint, no frontend tests, no e2e. The minimum that pays for itself: pytest against a Postgres service container in GitHub Actions, `ruff`, `tsc --noEmit`, and one Playwright smoke test (login → tracking search → CSV download). A test that hits every router as `district_officer` and asserts scoping would have caught §4.

**Compose is a dev config presented as the deployment.** Source directories are bind-mounted into containers, `mediamtx:latest-ffmpeg` is unpinned, the frontend runs the Vite dev server. Add `docker-compose.prod.yml` with built images, no bind mounts, healthchecks on backend/gateway, and `restart: unless-stopped` everywhere. `@app.on_event("startup")` is deprecated in FastAPI 0.115 — move to a `lifespan` handler.

**Observability.** Replace `print` with structured logging (`structlog` or stdlib JSON), add `/metrics` (prometheus-fastapi-instrumentator) on backend and gateway, and export worker metrics via a tiny HTTP endpoint. `submission/EVALUATION_SCORECARD.md` has six "pending" rows that are only fillable once these numbers exist.

**Gateway process model.** Each browser viewer spawns its own `ffmpeg` (`subprocess.Popen` per request, no fan-out). A 30-tile wall on three operator screens is 90 ffmpeg processes pulling the same 30 sources. MediaMTX is already in the stack and does exactly this (one pull per source, HLS/WebRTC fan-out); the docs even name it as the production gateway. Route the wall through it and reserve the ffmpeg gateway for legacy MKV/AVI sources.

**Frontend.** Seven views in one 358-line `App.tsx` switch with a 715-line `api.ts`. It works, but adding react-query (dedupes the polling, cache, retries), a router (deep links to a tracking result are a real demo win: `/track?plate=GJ01AB1234`), and a `components/` split will make Phase-2 features cheap. No Gujarati/Hindi localisation — operators in a district control room will notice.

---

## 8. Documentation: consolidate and de-stale

The docs are the best part of the repo, which is why the inconsistencies stand out:

- **PLAN.md** is dated 21 Aug and still lists "17 days to registration"; §9 "open decisions" are presumably decided; §11 definition-of-done has unchecked boxes for HLD/deck/videos that now exist in `submission/`. Update or archive it.
- **Model numbering.** README/PLAN say the hybrid is Models 1+2+3; HLD §4 and §19.1 describe Model **4** as the analytics layer and Model 2 as the viewing layer. Pick one taxonomy and use it everywhere (the official problem statement's numbering).
- **Claims out of sync with code**: "tamper-evident audit" (TECH_REF) vs `[design]` (HLD); "stateless, scales linearly" (BENCHMARK) vs §5 above; "No mock databases" (README) vs §6; camera count 30 vs 31 (HLD §18 vs header); HLD version 0.2 dated 17 Aug predates features it describes.
- **Overlap**: API.md, TECHNICAL_REFERENCE §7 and README "Key API" are three partial API lists. Generate one from OpenAPI (`/openapi.json` → markdown in CI) and link to it.
- Add short **ADRs** for the decisions the judges ask about (why Redis Streams now / Redpanda later, why ffmpeg gateway vs MediaMTX, why event-driven). The `engineering:architecture` skill format is fine.

---

## 9. Feature enhancements that would move the score

Beyond fixing gaps, these are the additions that map directly to the seven evaluation areas:

1. **Time-boxed, confidence-scored route search + PDF case report** (§3) — evaluation areas 1 and 2.
2. **Sharded/GPU analytics with per-camera metrics** (§2) — area 1, and turns the scorecard's "pending" rows into numbers.
3. **Working ONVIF discovery adapter** (WS-Discovery + Profile S via `onvif-zeep`) — currently "framework-ready" only; a live discovery of a real IP camera on the venue LAN is a convincing Model 3 demo and de-risks the "unknown event-day feed format" risk in PLAN §10.
4. **Visual re-ID under the space-time gate** (§3) — the honest answer to unreadable plates on wide-angle feeds.
5. **Case management**: save a search as a case, attach alerts and evidence, export a bundle, audit who opened it. Small model (`cases`, `case_items`) but it reframes Netra from "dashboard" to "investigation platform."
6. **Department as a first-class entity** (`Department` table, per-department RBAC in addition to district; ownership/consent flags for private cameras) — the HLD §12 privacy design needs it, and the challenge is explicitly about 26 departments.
7. **GIS depth**: camera FOV cones and coverage heatmap on the map, route rendered along the road network (OSRM `route` between stops instead of straight lines), geofence search ("all sightings within 500 m of this point").
8. **Live SSE feed** (§5) for alerts/detections/health.
9. **MediaMTX-backed wall with WebRTC** — sub-second latency instead of fMP4-over-HTTP, one pull per camera.
10. **Gujarati/Hindi UI strings** and keyboard-first operator flows.

---

## 10. Suggested sequence

| Phase | Scope | Why first |
|---|---|---|
| **P0 — scored output** | Worker sharding + crop-only plate detection + camera-list refresh; `since/until` on `/track`; newest-first limit; confusion-class plate matching; PDF case report; per-camera metrics | Everything the judges actually measure |
| **P1 — trust** | Gateway + local-evidence auth; consistent district scoping with a test; service role; hash-chained audit; opt-in representative seeds; Pydantic bodies | Cheap, and each one closes a gap between a doc claim and reality |
| **P2 — scale-readiness** | Scheduler service + Redis-backed dedup/baselines; SSE from Redis Streams; Alembic; composite indexes + retention; prod compose; CI | Makes SCALABILITY.md's claims true for the pilot |
| **P3 — product** | ONVIF adapter; re-ID; cases; departments; MediaMTX wall; localisation; docs consolidation | Phase-2 / PoC differentiation |

P0 and P1 are each roughly a focused week for one engineer familiar with the stack; the sharding change in P0 is a day and is the single largest improvement available.

---

*File references use paths relative to the repo root. Line-level detail is available on request for any item above.*
