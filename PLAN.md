# Gujarat Police Innovation Challenge 2026 - Master Plan

> **Project codename:** Sentinel (working name: **"Netra"** - unified CCTV intelligence platform)
> **Owner:** Kunal
> **Last updated:** 2026-08-21
> **Source of truth:** https://sentinel.gujarat.gov.in (`/`, `/about`, `/phases`, `/problems`, `/schedule`, `/faqs`)

---

## 1. The challenge in one paragraph

Gujarat Police runs a real-deployment innovation challenge (₹37 L pool, partners NFSU + DA-IICT) to unify 26 departments' fragmented CCTV systems into one secure, scalable, interoperable video-management + analytics platform. The scored, on-the-day test is concrete: onboard ~50 simulated-live camera feeds, and - **given a vehicle number on the day** - track that vehicle across cameras and output its **complete route + timestamped, location-wise movement history**. Demos must be **real working software** (mock-ups/animations are explicitly rejected).

## 2. Hard constraints & dates (non-negotiable)

| Date | Milestone |
|---|---|
| 4 Aug 2026 | Registration opened |
| **7 Sep 2026** | **Last date to apply** |
| **10–11 Sep 2026** | Hackathon event @ i-Hub Gujarat |
| 11 Sep 2026 | Results & prizes |

**As of 21 Aug 2026: 17 days to registration deadline and 20 days to the event.**

### Rules that shape everything
- **Model 1 (Registry + GIS) is COMPULSORY** and must be combined with ≥1 other model.
- **Demos must be actual working software** - no mock-ups/animations/concept videos (FAQ #32).
- Government-feed demo must show **real ANPR/detection output** = report of plates + timestamps (FAQ #31/#33).
- Two competition categories (see §9). Top 3 per category in Phase 1 → 6 finalists → Phase 2.

## 3. Win condition (what we optimize for)

The 7 official evaluation areas (FAQ #36), in priority order for our effort:

1. **Successful test case** - onboarding + cross-camera vehicle tracking on the govt feed. ← the crux
2. **Video analytics output** - quality of ANPR / detection / route report.
3. **Working platform** - maturity of demonstrated software.
4. **Solution architecture** - HLD technical soundness.
5. **Scalability & PoC readiness** - ~80,000-camera plan.
6. **Solution presentation** - clarity + model justification.
7. **Submission completeness.**

> Design principle: **build the vehicle-tracking vertical slice end-to-end first**; everything else (extra analytics, polish, bonus features) layers on top.

## 4. Chosen architecture: Hybrid = Models 1 + 2 + 3, selective AI

- **Model 1 (mandatory):** Centralised CCTV Registry & GIS map - camera metadata, health, gap analysis.
- **Model 2:** Unified viewing and metadata analytics - browser-safe streams,
  video wall, indexed detections, ANPR/search and evidence-backed alerts.
- **Model 3 (federation/middleware):** Adapter/connector layer + unified API/stream gateway + event bus. This is the "no rip-replace, vendor-neutral" thesis and earns the *innovative hybrid* bonus (#38).
- **Selective AI:** ANPR, vehicle detection and cross-camera tracking run
  centrally in the sandbox, with an edge-ready statewide design.

**Why this combo wins:** compulsory Model 1 satisfied; Model 3 answers heterogeneity + scalability without touching departments' infra; Model 4 analytics delivers the scored test case. The hybrid framing is explicitly rewarded.

### Reference data flow
```
Dept cameras / 50 sim-live stream URLs
        │  (RTSP / ONVIF / HLS / vendor SDK)
        ▼
[Feed Adapters]  ── normalize ──►  [Stream Gateway (MediaMTX)]  ──► browser (HLS/WebRTC video wall)
        │                                   │
        ▼                                   ▼
[Camera Registry + PostGIS]        [Analytics Workers (YOLO + ANPR + tracker)]
        │                                   │  detections (plate, vehicle, ts, cam)
        ▼                                   ▼
[GIS Map / Command Center] ◄──── [Event Bus (Redis Streams → Kafka in prod)]
        ▲                                   │
        │                                   ▼
[Alerts] ◄── [DB Integration: mock VAHAN/SARTHI/eGujCop/AFIS/NAFIS] ◄── plate/face match
        │
        ▼
[Cross-camera Vehicle Route Reconstruction]  → route + timestamped movement history (THE output)
```

## 5. Technology stack (recommended)

| Layer | Choice | Rationale |
|---|---|---|
| Analytics/CV | **Python + FastAPI**, YOLOv8/v11 (Ultralytics), ANPR (plate-detector + PaddleOCR/EasyOCR) | Real ANPR is mandatory; Python CV ecosystem is strongest |
| Backend/federation | **Python FastAPI** (one language) + WebSockets | Unified with analytics; async streaming ok |
| Stream gateway | **MediaMTX** (RTSP→WebRTC/HLS) + ffmpeg | Pragmatic: ingest RTSP, republish browser-playable |
| Frontend | **React + Vite + TS + Tailwind**, MapLibre/Leaflet, hls.js | Fast, great-looking command center |
| DB | **PostgreSQL + PostGIS** (+ TimescaleDB optional) | Matches suggested stack; geospatial route queries |
| Event bus | **Redis Streams** (proto) → **MQTT edge + Redpanda core** (prod design) | Thin-link edge ingest + Kafka-API core, no ZooKeeper/JVM; see SCALABILITY.md |
| Packaging | **docker-compose** | Modular, one-command demo, easy to swap feeds |

> All "prod-scale" choices (MQTT+Redpanda, Kubernetes, S3/Ceph, GPU edge) live in the HLD; the running prototype uses the lighter equivalents but the *interfaces* are identical. Statewide sizing for ~80,000 cameras is worked out in [SCALABILITY.md](SCALABILITY.md).

## 6. Prototype scope - vertical slices (build order)

- **S0. Scaffold** - monorepo, docker-compose, docs skeleton, seed data.
- **S1. Registry + GIS (Model 1)** - camera CRUD + bulk import, PostGIS, MapLibre map color-coded by dept + health. *Mandatory deliverable.*
- **S2. Stream gateway + video wall** - ingest sample RTSP/video files, multi-camera grid in browser.
- **S3. ANPR + detection service** - real plate detection + OCR + vehicle detection on sample video; write detection events.
- **S4. Cross-camera vehicle tracking** ← **core win condition** - plate query → ordered route + timestamped movement history rendered on map + as report.
- **S5. DB integration + alerts** - mock VAHAN/eGujCop/AFIS services; hit → real-time alert in command center.
- **S6. Security & ops** - dept RBAC, audit log, camera health monitoring, gap-analysis report.
- **S7. Govt-feed swap + dry run** - replace sample URLs with the 50 sandbox stream URLs; run the actual test case.

Bonus (if time, #38): re-ID cross-camera matching, edge/bandwidth optimization, face detection, operational dashboards, integration-ready public APIs.

## 7. Document deliverables (required for submission)

1. **Solution Presentation (PPT/PDF)** - chosen model + justification, overview, key features, screenshots.
2. **High-Level Design (HLD)** - architecture diagrams; heterogeneous camera/VMS integration (IP/analog/multi-vendor/protocols); dispersed-site handling (bandwidth, edge vs central); analytics approach (ANPR + cross-camera tracking); **~80,000-camera scalability plan** (central/regional/edge compute, GPU sizing, bandwidth/low-bw strategy, hot/warm/cold storage, HA/DR, phased rollout); dept-level integration details.
3. **Two demo videos** - (a) own feed (2–3 min): onboarding + live/recorded view + ANPR; (b) govt feed: onboarding + viewing + analytics output, **plus an output report of plates/timestamps**.
4. **Optional (do it - earns points):** hosted URL + test creds, GitHub repo with source.

## 8. Work breakdown & sequencing (calendar)

| Window | Focus |
|---|---|
| **Completed by Aug 21** | Registry/GIS, government-feed adapter, video wall, analytics, tracking, watchlist alerts, health/RBAC/audit, registry onboarding and CSV evidence exports |
| **Aug 22 → Aug 28** | Improve ANPR yield; add own-feed upload/recorded-video demo path; harden alert evidence quality |
| **Aug 29 → Sep 4** | Load test, API documentation, HLD/deck, complete cost model, security hardening |
| **Sep 5 → Sep 7** | Finalize submission, hosted demo and credentials; **register by 7 Sep** |
| **Sep 8 → Sep 9** | Full timed rehearsal, fault-injection run, record both 2–3 minute demo videos |
| **Sep 10–11** | Event: onboard supplied feeds, execute designated-vehicle test, export report, present |

## 9. Open decisions (need Kunal's input)

1. **Category** - Cat 1 (student/DPIIT startup) or Cat 2 (company/enterprise)? Affects positioning & prize bracket. *Default assumption: Cat 1 unless told otherwise.*
2. **Team** - solo or team? Affects how much bonus scope is realistic.
3. **Compute** - is a GPU available (local/cloud) for real-time ANPR? *Fallback: frame-sampled ANPR on CPU for the demo; note GPU in scalability plan.*
4. **ANPR model** - Indian-plate-tuned model vs generic + fine-tune. *Default: start with a pretrained plate detector + OCR, evaluate on sample frames, fine-tune only if accuracy is weak.*
5. **Naming/branding** - keep "Netra" or pick another. Cosmetic.

## 10. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Real-time ANPR too slow on CPU | Frame-sample (e.g. 1–2 fps) + ROI; GPU for finale; async worker pool |
| Govt stream format unknown until registration | Adapter abstraction; support RTSP/HLS/ONVIF/file; test on samples now |
| Cross-camera ID hard without re-ID | Anchor on ANPR plate match first (reliable); add visual re-ID as bonus |
| Indian plate OCR accuracy | Fuzzy plate matching + confidence thresholds; fine-tune on sample frames |
| Tight timeline | Vertical-slice discipline: S1→S4 must work before polish/bonus |
| Demo fragility on the day | docker-compose one-command bring-up; pre-recorded backup video |

## 11. Definition of done (Phase 1 submission)

- [ ] Registered before 7 Sep; event access confirmed.
- [x] Running platform: onboard feeds → view → analytics → search → route+timeline.
- [x] Mandatory Model 1 registry + GIS with manual/CSV onboarding and export.
- [x] Downloadable detection/movement report with plate, timestamp and location.
- [ ] HLD doc complete (incl. 80k-camera scalability).
- [ ] Solution deck complete.
- [ ] Two demo videos recorded.
- [ ] GitHub repo + optional hosted URL.
