# High-Level Design (HLD) - Unified CCTV Integration & Video Analytics Platform

**Project:** Netra - Statewide CCTV Integration & Intelligence Platform
**For:** Gujarat Police Innovation Challenge 2026 &middot; **Approach:** Hybrid (Model 1 + 2 + 3, selective Model 4) &middot; **Version:** 0.2 (as-built + production design) &middot; **Date:** 2026-08-17

> **Status:** a working prototype runs against the **real** Gujarat CSITMS live feed (~30 cameras). Items marked **[built]** are implemented; the rest is production design the same interfaces scale into. As-built summary in §19.

**Open source:** [github.com/kunal047/gsp](https://github.com/kunal047/gsp)

## 1. Executive summary
- Gujarat's 26 departments run independent, heterogeneous CCTV: mixed analog/IP, many VMS vendors, dispersed up to ~1,000 km.
- Netra unifies them **without replacing any existing system** - a vendor-neutral federation layer for viewing, analytics and alerting.
- **Event-driven by necessity:** at 80k cameras, centralizing video is ~200 Gbps / ~32 PB; the events are ~0.3% of that. So video stays at edge/region; only events + on-demand streams cross the WAN.
- **Scored test case:** onboard ~50 feeds, then given a vehicle number, reconstruct its cross-camera route + timestamped movement history - an indexed event search, not a video-crunching problem.

## 2. Objectives & scope
- **In scope:** registry + GIS (M1); VMS/camera federation via adapters (M3); edge/central AI - ANPR, vehicle/person/object detection, cross-camera tracking (M4); VAHAN/SARTHI/eGujCop/AFIS/NAFIS integration; command center; ~80k scalability; consent-gated private-camera viewing.
- **Out of scope (by design):** replacing departmental VMS/storage; centralizing raw video; owning retention policy.

## 3. Design principles
- **Non-invasive federation** - departments keep their VMS, storage, AMC and control.
- **Event-driven** - extract intelligence at source; move events, not video.
- **Vendor-neutral & standards-based** - ONVIF/RTSP first; adapters for proprietary SDKs; open APIs; no lock-in.
- **Hierarchical (edge to regional to state)** - bounded WAN, regional autonomy, scale by adding regions.
- **Secure & privacy-aware** - mTLS, RBAC, segmentation, tamper-evident audit, consent-gated private cameras.
- **Prototype = production interfaces** - same APIs/contracts; only backing implementations differ.
- **Never fabricate** - cameras come only from the live feed; a failed onboard surfaces the real error; derived fields are flagged; limitations are documented.

## 4. Chosen architecture
| Model | Role in Netra | Why |
|---|---|---|
| **Model 1 - Registry & GIS** (mandatory) | System of record: metadata, location, health, ownership, connectivity, storage | Visibility + planning foundation |
| **Model 3 - Federation & Middleware** | Adapters + unified API + stream gateway + event bus | Answers heterogeneity and scale without touching departments |
| **Model 4 - Central AI** (selective) | ANPR, detection, cross-camera tracking, DB-integrated alerts | Delivers the scored analytics test case |

Operator-facing layer uses Model 2 unified viewing/search; Model 3 adapters sit behind its stream contract, so vendor differences never reach the viewer.

## 5. Logical architecture

```
┌────────────────────────────────────────────────────────────────────────────┐
│                         PRESENTATION LAYER                                    │
│   State Command Center · Regional consoles · GIS map · Video wall · Alerts    │
│   Search (plate → route) · Dashboards · Admin/Registry UI · Public-cam view   │
└───────────────▲───────────────────────────────────────────────▲──────────────┘
                │ REST / WebSocket / WebRTC-HLS                   │
┌───────────────┴───────────────────────────────────────────────┴──────────────┐
│                    FEDERATION & SERVICES LAYER (Model 3)                       │
│  API Gateway · AuthN/AuthZ (RBAC) · Camera Registry (Model 1) + PostGIS        │
│  Stream Gateway (MediaMTX) · Event Bus (MQTT edge → Redpanda core)             │
│  Analytics Orchestrator · Alert Engine · Route Reconstruction · Audit          │
│  External DB Integration: VAHAN · SARTHI · eGujCop · AFIS · NAFIS              │
└───────────────▲───────────────────────────────────────────────▲──────────────┘
                │ normalized feeds + events                       │ on-demand
┌───────────────┴───────────────────────────────────────────────┴──────────────┐
│                       INTEGRATION / ADAPTER LAYER                              │
│   ONVIF adapter · RTSP adapter · Vendor-SDK adapters (Milestone/Genetec/CP+    │
│   /Hikvision/Dahua…) · Analog-via-encoder/DVR adapter · File/HLS adapter       │
└───────────────▲───────────────────────────────────────────────────────────────┘
                │
┌───────────────┴───────────────────────────────────────────────────────────────┐
│              EDGE / SOURCE (departmental, left intact)                          │
│   IP cameras · Analog cameras + encoders/DVRs · Departmental VMS · Local/cloud  │
│   storage · Edge analytics node (Jetson/GPU) for ANPR/detection at source       │
└────────────────────────────────────────────────────────────────────────────────┘
```

Physical tiers (edge to regional to state) and sizing: §14.

## 6. Component design

### 6.1 Camera Registry & GIS (Model 1, mandatory) [built]
- System of record per camera: id, department, ownership, geo, site, type (IP/analog), make/model, protocol, stream_url, capabilities, connectivity, storage, retention, health, AMC expiry.
- Onboarding: bulk CSV/API, manual entry, ONVIF discovery.
- GIS: MapLibre + PostGIS; layers by department/type/status/coverage; gap-analysis (uncovered zones, ageing/EOL, AMC expiry).
- Health: per-camera heartbeat; RBAC search, filter, export, audit.

### 6.2 Integration / Adapter layer [built + framework-ready]
- Adapter interface: `connect → authenticate → discover → stream → status`. New vendor = new adapter, no core change.
- **[built]** Live-feed adapter onboards the real CSITMS feed over open HTTP/REST + HTTP video (no SDK); geocodes free-text location (flagged `coords_approx`), infers category (`dept_inferred`).
- **[framework-ready]** ONVIF (S/T/G), RTSP, vendor SDKs (Milestone/Genetec/CP+/Hikvision/Dahua), analog via encoder/DVR.

### 6.3 Stream gateway [built]
- ffmpeg service makes heterogeneous sources browser-playable without touching them: MP4 played direct, MKV remuxed (`-c copy`), AVI/unknown transcoded to H.264; fragmented MP4 per viewer, torn down on disconnect.
- Production: MediaMTX + ffmpeg (RTSP to WebRTC/HLS), on-demand pull, same contract.

### 6.4 Analytics engine (Model 4, selective) [built]
- **Two-stage ANPR:** YOLOv8n vehicle detect (type) → YOLO plate detector → EasyOCR (upscaled crop, Indian-plate regex + confidence gate); overlay watermark masked so it cannot be read as a plate.
- **Attributes + tracking:** dominant colour (HSV) + type; isolated per-camera ByteTrack; type/colour majority-voted; one durable event per completed track.
- **Evidence:** vehicle crop retained; watchlist evidence boxes the triggering track.
- **Time:** source player clock authoritative (OCR/file-start fallback); ingest time kept separately for throttle/audit.
- **Derived:** direction, dwell, stopped, motion; wrong-way only with a configured expected direction; road speed needs camera calibration.
- **Real finding:** on wide-angle CSITMS cameras plates are ~20-120 px (below the ~100 px OCR floor) so reads are near-zero - a source-camera limit, not a pipeline defect; ready for ANPR-grade feeds.
- **Extensible:** `VEHICLE_MODEL` + class map accepts a Gujarat model (e.g. auto_rickshaw); stock COCO lacks that class and the UI does not pretend otherwise.

### 6.5 Event bus [built]
- Redis Streams (prototype) → MQTT edge + Redpanda core (production), partitioned by region × camera-group, RF=3; identical producer/consumer interface. Sizing §14.

### 6.6 Alert engine - real feed analytics [built]
- **Congestion** - per-camera count over an adaptive threshold.
- **Traffic surge** - spike above a live per-camera EMA baseline, daypart-aware.
- **Feed-offline** - health monitor detects a down stream and alerts.
- **Watchlist (BOLO)** - operator flags a plate or type+colour; fires on real detections, throttled per camera.
- **Cloned plate** - same plate at two cameras faster than physically possible; cross-system check.

### 6.7 External DB integration (deployment)
- `IntegrationConnector` to VAHAN, SARTHI, eGujCop/CCTNS, AFIS/NAFIS (caching + rate-limit); ANPR/face match → lookup → enriched alert.
- **Real deployment integrations, not simulated** in the prototype (need authorised gov API access + ANPR-grade feeds).

### 6.8 Health monitor & gap-analysis [built]
- Probes each real stream endpoint; updates health (online/degraded/offline); raises feed-offline alerts on transition.
- Gap-analysis: coverage %, per-district online/offline, thin coverage (≤1 camera), offline list.

### 6.9 Command center [built]
- Single-pane UI: signed login &middot; GIS map &middot; video wall &middot; vehicle tracking (search to route + timeline) &middot; alerts (feed + map) &middot; ops (gap-analysis + audit) &middot; live detections &middot; verified RBAC identity.

## 7. Integration strategy (heterogeneous cameras/VMS)

| Source type | Mechanism | Status |
|---|---|---|
| Live CSITMS feed | HTTP/REST + HTTP progressive video (no SDK) | **[built]** |
| IP camera (ONVIF) | ONVIF Profile S/T/G + RTSP | [framework-ready] |
| IP camera (proprietary) | Vendor SDK adapter | [framework-ready] |
| Analog camera | Existing encoder/DVR to RTSP | [framework-ready] |
| Departmental VMS | VMS API/SDK adapter or RTSP re-stream | [framework-ready] |
| Private cameras | Viewing-only adapter, consent-gated | [framework-ready] |

Principle: normalize at the platform edge, keep departments untouched. Live integration uses open standards only (HTTP/REST + streaming), zero vendor-SDK dependency.

## 8. Geographic dispersion & connectivity
- Edge analytics at source; event-only backhaul (~1.6 Gbps peak vs ~200 Gbps of video).
- GSWAN where available; SD-WAN/VPN elsewhere; store-and-forward at the edge for flaky links.
- Video pulled on demand (never a persistent central pull); regional storage keeps recent footage local.
- Low-bandwidth: adaptive bitrate, keyframe/thumbnail-first, event-triggered clips.

## 9. Video analytics approach
- **Pipeline [built]:** frame sample → overlay-mask → YOLOv8 vehicle (+colour) → per-camera ByteTrack → YOLO plate → EasyOCR → track persistence + majority vote → one `detection_event` → publish to bus + index.
- **Single-vehicle tracking, in priority order:**
  1. **Plate match (exact) [built]** - `GET /api/track?plate=` orders sightings into a cross-camera route; exact wherever plates resolve, tolerant to OCR error (fuzzy/partial).
  2. **Attribute + spatio-temporal gating [built]** - `GET /api/track/vehicle` follows only physically reachable next-camera sightings (elapsed time ≥ distance ÷ max speed); returns one trajectory with per-hop gap/distance/speed and a rejected-infeasible count. Verified: a yellow car reconstructs to a 3-hop Ahmedabad path and refuses the 330 km jump.
  3. **Visual re-ID [roadmap]** - appearance embedding matched across cameras under the same space-time gate.
- **Other analytics [roadmap]:** person/face, intrusion/loitering/crowd, anomaly, camera-tamper.

## 10. Data model (key entities)
- `camera` &middot; `department` &middot; `site` &middot; `stream_session`
- `detection_event {id, camera_id, type, plate?, object_class?, confidence, geo, ts, snapshot_ref}`
- `vehicle_track {plate, [{camera_id, geo, ts, confidence} ...]}` (materialized from events)
- `watchlist_item` &middot; `alert {id, rule, event_ref, db_match, severity, status, ts}`
- `user` &middot; `role` &middot; `permission` &middot; `audit_log`

## 11. APIs (OpenAPI-documented, RBAC-scoped) [built]
- **Registry:** `GET/POST /api/cameras`, `/cameras/bulk`, `/stats`, `/gap-analysis`, `/ingest/live`, `/ingest/retry`
- **Analytics:** `POST /api/detections`, `GET /api/detections[/stats]`, `POST /api/frame`
- **Tracking:** `GET /api/track` (plate or type+colour), `GET /api/track/vehicle`
- **Alerts:** `GET /api/alerts[/stats]`, `POST /api/alerts/{id}/ack`, `GET/POST/DELETE /api/watchlist`, `GET/PUT /api/alerts/baselines`
- **Governance:** `GET /api/audit`, `GET /api/health` (reports `ingest_error`)
- **Auth/RBAC:** password login issues an HS256 JWT; user/role/district-scope come from verified claims; SSO/OIDC-ready; spoofable identity headers disabled outside local dev.
- **Deployment connectors:** `IntegrationConnector` for VAHAN/SARTHI/eGujCop/AFIS/NAFIS (real, not faked).

## 12. Security, privacy, RBAC & audit
- **[built] RBAC:** state_admin (all), district_officer (district-scoped cameras + stats), viewer (read-only; mutations return 403). SSO/OIDC-ready.
- **[built] Audit:** append-only, per audited action (track, alert ack, BOLO), attributed to user + role + time.
- **[built] Data-minimization:** events + small snapshots stored, not the video (stays at source).
- **[design]** mTLS on feeds/events/APIs; per-department segmentation; consent-gated private cameras; encryption at rest; hash-chained tamper-evident audit.

## 13. Deployment architecture
- Three tiers: **Edge (site) → Regional (district/range) → State Core (SDC + DR)**; Kubernetes per region; stateless services behind load balancers; autonomy on WAN loss. Detail in §14.

## 14. Scalability to ~80,000 cameras
- **Thesis, forced by arithmetic:** centralizing video would be ~200 Gbps / ~32 PB; events are ~0.3% of that. So video stays at edge/region; only events + on-demand streams cross the WAN. This one decision answers heterogeneity, dispersion and scale together.

### 14.1 Capacity model
| Dimension | Centralized (naive) | Netra (event-driven) |
|---|---|---|
| Video bandwidth | ~200 Gbps into one core | kept regional; ~1.6 Gbps peak events cross the WAN |
| Storage (15 d) | ~32 PB central | ~13-19 PB tiered, regional (H.265 + event-based) |
| Event store (30 d) | not applicable | ~100 TB indexed (~0.3% of video) |
| Analytics compute | ~2,000 central GPUs | ~600-1,000 edge/regional accelerators |
| Event bus load | not applicable | ~40k/s avg, ~150-200k/s peak = ~5-10% of a modest cluster |

### 14.2 Topology & storage
- **Edge (per site):** camera + NVR/VMS untouched + edge analytics node (Jetson/GPU); ANPR at source; MQTT event publish; local buffer.
- **Regional (per district/range, ~6 ranges / 33 districts):** federation gateway, tiered hot/warm storage, GPU pool, MQTT + Redpanda; keeps video local, forwards filtered events.
- **State core (SDC Gandhinagar + DR):** global registry + PostGIS, event store + search index, cross-region route reconstruction, external DB integration; sees events/metadata/on-demand streams, never bulk video.
- **Storage tiers:** hot 0-48 h (NVMe, regional) → warm 2-15 d (HDD/object, regional) → cold >15 d (erasure-coded, regional/DR); events & metadata 30-90 d+ (indexed, state core).

### 14.3 Measured on the prototype
- 50-feed ingestion benchmark: **15 to 820 req/s (~55x)** after an in-process camera cache + background-batched persistence; **~164 feeds at 5 fps, 0 errors** (3.3x the target). Full ANPR on CPU ~5 s/frame - hence edge/regional GPU pools (~40 cameras/GPU), not a central CPU farm. Ingestion scales linearly with replicas.

### 14.4 Rollout & cost
- **Phases:** pilot (2-3 districts, ~2,000 cameras, one hub) → range expansion (tune GPU/bandwidth) → statewide (replicate template, DB integrations, DR drills) → consent-gated private cameras.
- **Indicative envelope** (existing estate reused; replace with RFP pricing): capital **₹360-840 crore**, operating **₹55-140 crore/year**; pilot **₹10-18 crore capital** + **₹2-4 crore/year**. Full model: [SCALABILITY.md](SCALABILITY.md).

## 15. Department onboarding intake (integration feasibility)
| Item | Why |
|---|---|
| Camera inventory (count, IP/analog, make/model) | Adapter selection, sizing |
| VMS platform + version + API/SDK availability | Federation method |
| Protocols (ONVIF/RTSP/proprietary) | Adapter selection |
| Network, bandwidth, GSWAN/connectivity | Edge vs central, backhaul |
| Storage type + retention | Tiering, on-demand pull |
| Existing analytics/encoders | Reuse vs add edge node |
| Access/security policy, credentials | mTLS, RBAC, segmentation |
| AMC vendor + expiry | Coexistence, upgrade path |
| Site locations (geo) | Registry/GIS, gap analysis |

## 16. Cost-benefit (high level)
- **Reuse-first:** no camera/VMS replacement; reuse encoders, storage, GSWAN.
- **Event-driven:** ~1.6 Gbps vs ~200 Gbps - orders-of-magnitude lower WAN/storage cost.
- **Selective/edge analytics:** ~600-1,000 accelerators vs ~2,000 central - ~50% compute capex saved.
- **Open/vendor-neutral:** no lock-in; new cameras/departments onboard via adapters, not re-procurement.

## 17. Test-case walkthrough (scored)
1. Onboard the provided stream URLs via the live adapter → they appear on the GIS map and video wall.
2. Analytics runs vehicle/plate/colour detection → emits indexed events.
3. Judges give a vehicle number → `GET /api/track?plate=` → time-ordered cross-camera route + movement timeline + map path (exact on ANPR-grade feeds).
4. If plates are unreadable, attribute + spatio-temporal gating (§9) narrows to the single-vehicle trajectory.
5. Congestion/surge/feed-offline and BOLO alerts fire from real analytics; the audit log records every query/action.

## 18. Assumptions & open items
- Blended stream 2.5 Mbps; frame-sampled analytics; per-GPU camera density to be re-measured on ANPR-grade feeds.
- **[measured]** Live CSITMS feed is HTTP/1.1 progressive MP4/MKV/AVI, 31 cameras, 12-h files, wide-angle overview (plates ~20-120 px).
- **To add:** regional-hub reference BOM; ER + sequence diagrams; single-vehicle visual re-ID.
- Real DB access (VAHAN etc.) is a deployment-time gov integration, not simulated.

## 19. As-built summary

**Runs with one command (`docker compose up`) against the real feed.**

| Service | Tech | Role |
|---|---|---|
| backend | FastAPI + SQLAlchemy + GeoAlchemy2 + PostGIS | registry, ingest, tracking, alerts, RBAC, audit, health |
| gateway | FastAPI + ffmpeg | MKV/AVI to browser-playable MP4 |
| analytics | YOLOv8 + YOLO plate detector + EasyOCR + ByteTrack | detections, colour, ANPR, per-frame counts |
| frontend | React + Vite + MapLibre | Map / Video Wall / Tracking / Alerts / Ops + detections |
| db / redis | PostgreSQL+PostGIS / Redis Streams | store + event bus |

### 19.1 Four-model coverage
| Model | Status | What's built |
|---|---|---|
| **1 - Registry & GIS** (mandatory) | Feature-complete | registry, GIS, onboarding, health, lifecycle, gaps, RBAC, export + audit |
| **2 - Unified Viewing & Analytics** | Code-complete | gateway, video wall, tracked evidence, indexing, search, alerts, ANPR consensus |
| **3 - VMS Federation** | Code-complete | CSITMS + RTSP adapters, provenance, gateway, event bus, correlation report |
| **4 - Central VMS & AI** | Partial | AI analytics + tracking + integration-readiness + RBAC built; tiered storage/DR/GPU-pool is design |

### 19.2 Architecture-principles compliance
| Principle | Realisation |
|---|---|
| Open, vendor-neutral, no lock-in | 100% open-source; live integration over HTTP/REST + standard streaming, no vendor SDK |
| Modular, technology-agnostic | services behind stable contracts; ANPR model, bus, storage, auth all swappable |
| Standards-based | REST/OpenAPI, PostGIS (OGC), ONVIF/RTSP/HLS-ready, Kafka-API/MQTT |
| Heterogeneous multi-vendor | adapter layer + ffmpeg gateway normalise mixed protocols/containers/codecs |
| Upgrade/expand without redesign | proven in-build: swapped camera source and added analytics + alert types without touching core contracts |
| Secure | RBAC + audit built; mTLS/segmentation/encryption designed |
| Scalable | event-driven, hierarchical edge to regional to state (§14) |

### 19.3 Limitations
- **ANPR reads** are near-zero on the current wide-angle cameras (plates below OCR resolution) - a source-camera limit; pipeline ready for ANPR-grade feeds.
- **Single-vehicle tracking** without a plate uses space-time gating (§9); visual re-ID is the next increment.
- **Coordinates** are geocoded/approximate (source API has no lat/lng), flagged `coords_approx`.
- **Scale/DR/storage** is design, appropriate for Phase-1.

---

*Open source - full code, infrastructure and documentation: [github.com/kunal047/gsp](https://github.com/kunal047/gsp)*
