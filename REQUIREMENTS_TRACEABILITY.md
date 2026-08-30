# Official Requirements → Netra Execution Plan

Audit of the Gujarat CCTV Hackathon 2026 problem statement on 21 Aug 2026.
This file separates working evidence from roadmap claims.

| Official requirement | Working evidence in this repository | Status / next action |
|---|---|---|
| Open, modular, vendor-neutral integration | Live-feed adapter, normalized camera schema, HTTP/RTSP/HLS/ONVIF metadata, ffmpeg gateway | Working; publish adapter interface/API examples |
| Mandatory Model 1 registry + GIS | Map plus Registry workspace; search/filter; manual and CSV onboarding; health, provenance and analytics fields | Working |
| Role-based search, actions, export and audit | Signed JWT identity, state/district/viewer principals; district scoping; actor-gated camera writes; audited CSV exports | Working prototype; integrate department SSO/OIDC for deployment |
| Bulk and manual camera onboarding | `POST /api/cameras`, `/bulk`, Registry form and CSV import | Working |
| Health, maintenance and coverage gaps | Stream health monitor, offline alerts, Ops gap report | Working; add maintenance tickets/AMC workflow |
| Search designated registration number | Exact/normalized ANPR tracking endpoint and Tracking UI | Working when source imagery yields a readable plate |
| Complete route and timestamp/location history | GIS route, ordered timeline, CSV movement-evidence export | Working |
| Representative watchlist + continuous alerts | Track-persistence/confidence-gated matching, explicitly boxed context evidence, source-clock event time, live alert UI | Working; validate thresholds per camera/model |
| Own-feed 2–3 minute demonstration | Independent RTSP onboarding and guided runbook exist | Record the final genuine-road video |
| Government-feed analytics output report | CSV contains detection, plate, timestamp, camera, district, coordinates and evidence path | Working; improve ANPR yield on wide-angle feeds |
| ~50 heterogeneous feeds on event day | 30 live government feeds normalize/play; ingestion benchmark exceeds the 250 frame-summary/s target | Execute the final supplied-feed timed rehearsal |
| 80,000-camera architecture, sizing, HA/DR, costs | `SCALABILITY.md` includes bandwidth, storage, GPUs, tiering, HA/DR, rollout and cost envelope | Documented; validate assumptions during discovery |
| Submission artefacts | README, HLD, scalability, API document, deck and traceability matrix | Export/verify PDFs, record two timed videos, host and issue evaluator credentials |

## Execution order from here

1. Record genuine multi-camera ANPR-grade road footage so judges can see
   onboarding → analytics → route without depending on remote stream conditions.
2. Raise ANPR evidence quality: plate ROI diagnostics, confidence calibration,
   Indian-plate benchmark set, and camera suitability labels.
3. Run a 50-feed rehearsal and capture latency, throughput, failure recovery and
   per-stage timings as evaluation evidence.
4. Integrate department OIDC/SSO, signed audit records, secrets management and
   a least-privilege deployment profile.
5. Produce the timed videos, HLD/API appendix, deck, hosted demo and credentials.
