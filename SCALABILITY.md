# Statewide Scalability Design — ~80,000 Cameras

> Deliverable for evaluation area #35 (statewide scalability plan). Feeds directly into the HLD.
> All figures use stated assumptions; ranges given where inputs vary. Round numbers are deliberate — the point is the order of magnitude, which drives the architecture.

## 1. Capacity model (why the architecture is what it is)

**Assumptions:** blended stream ≈ **2.5 Mbps** (mix of 2 MP @ 2 Mbps H.265, 4 MP @ 4–6 Mbps, and low-bitrate analog-encoded). 80,000 cameras.

### 1.1 Video bandwidth — the reason you cannot centralize
| Metric | Value |
|---|---|
| Per camera | 2.5 Mbps |
| **Aggregate if all video centralized** | **80,000 × 2.5 Mbps = ~200 Gbps** |

200 Gbps of sustained ingest into one core is infeasible and pointless. **→ Video stays at edge/regional. Only events + on-demand streams cross the WAN.** This is the architectural thesis, forced by arithmetic.

### 1.2 Video storage (kept regionally, tiered)
| Metric | Value |
|---|---|
| Per camera/day | 2.5 Mbps ≈ 27 GB/day |
| All cameras/day | ~2.16 PB/day |
| **15-day retention** | **~32 PB** (before codec savings) |
| With H.265 + motion/event-based recording | 40–60% less → ~13–19 PB |

→ **Distributed regional storage**, tiered hot/warm/cold. Never a single central store.

### 1.3 Analytics compute (GPUs)
**Assumptions:** analytics at **5 fps** sampling (not 25–30); full ANPR pipeline (plate detect + OCR + vehicle detect) ≈ **~40 cameras per modern GPU** (L4/A10-class); lighter motion/object-only ≈ 80–120/GPU.

| Scenario | GPU estimate |
|---|---|
| Worst case: continuous ANPR on **all** 80k | 80,000 / 40 ≈ **~2,000 GPUs** |
| Realistic: ANPR on ~30–40% (public/traffic domain), rest motion-triggered + edge accelerators (Jetson Orin at camera clusters) | **~600–1,000 accelerators**, regionally distributed |

→ **Edge + regional inference**, selective/motion-triggered analytics, frame sampling, ROI. Not central GPU farm.

### 1.4 Event bus — the punchline
**Assumptions:** avg **0.5 events/sec/camera** (bursty; ANPR/detection only fire on activity), payload ~1 KB.
| Metric | Value |
|---|---|
| Avg event rate | 80,000 × 0.5 = **~40,000 events/sec** |
| Peak | ~150,000–200,000 events/sec |
| Peak throughput | ~200k/s × 1 KB = **~200 MB/s (~1.6 Gbps)** |
| Event log/day (avg) | ~3.4 TB/day |
| **30-day event retention** | **~100 TB** |

**Compare:** events ≈ **100 TB** vs video ≈ **32 PB** → events are **~0.3%** of the data. A modern Kafka/Redpanda broker sustains 100s of MB/s–GB/s each; a **6–12 node core cluster handles millions/sec** — our 40k–200k/s is comfortable headroom. **The bus is never the bottleneck; that's exactly why the system is event-driven.**

## 2. Messaging tier at scale (the Kafka-alternative decision, sized)

Two-tier, matched to the 1,000 km dispersion:

- **Edge → Regional: MQTT** (EMQX/Mosquitto cluster per region). Lightweight, tolerant of thin/flaky links, ideal for pushing *events* (never video) from edge analytics nodes. Directly answers "geographical dispersion" + "low-bandwidth strategy."
- **Regional core + State core: Redpanda** (Kafka API, single binary, no ZooKeeper/JVM — far simpler gov ops) *or* NATS JetStream (lightest). RF=3, partitioned by `region × camera-group`.
- **Bridge:** MQTT → Redpanda connector at each regional hub aggregates/filters before anything crosses to the state core.
- **Prototype uses Redis Streams** (identical producer/consumer interface) so hackathon code is unchanged; HLD shows the MQTT+Redpanda production topology.

**Sizing:** per-region Redpanda 3-node (RF3) handles that region's slice; state core 6–12 nodes for cross-region correlation + forensic event log (30–90 day retention for replay). All well within single-cluster limits.

## 3. Hierarchical topology (edge → regional → state)

```
TIER 0 — EDGE (per site / camera cluster)
  Existing camera + NVR/VMS (untouched)  +  Edge analytics node (Jetson/GPU)
  → ANPR/detection at source · MQTT event publish · local buffer for flaky links

TIER 1 — REGIONAL (per district/police range — ~6 ranges / 33 districts)
  Regional VMS federation gateway (adapters) · Regional storage (hot+warm, tiered)
  Regional GPU analytics pool · MQTT broker + Redpanda cluster · regional command view
  → keeps video local; publishes filtered/aggregated events upward

TIER 2 — STATE CORE (State Data Center, Gandhinagar + DR site)
  Global camera Registry + PostGIS · Global event store + search index (ES/Timescale)
  Cross-region correlation & vehicle route reconstruction · State Command Center
  External DB integration: VAHAN · SARTHI · eGujCop · AFIS · NAFIS
  → sees events + metadata + on-demand streams, never bulk video
```

Why hierarchical: bounds WAN traffic (events only), keeps video/storage/compute near the source, lets regions run degraded-independent if the WAN drops, and scales by adding regions — not by growing one core.

## 4. Cross-camera vehicle tracking at 80k scale (the test case, scaled)

1. Edge/regional analytics emits `{plate, camera_id, geo, ts, confidence}` on every ANPR hit → MQTT → Redpanda.
2. A stateful stream processor (Kafka Streams / Flink, or a consumer group) maintains per-plate timelines and writes to an **indexed event store** (Elasticsearch or TimescaleDB + PostGIS).
3. **Route query = an indexed search over events**, not video: given a plate, pull ordered `(geo, ts)` across all regions → reconstruct route + timestamped movement history in ms.
4. Fuzzy plate matching (OCR confidence + Levenshtein) + optional visual re-ID as corroboration.

At scale this is a search problem over ~100 TB of tiny events — fast and horizontally shardable — **not** a 32 PB video problem.

## 5. Storage tiers (retention-driven)
| Tier | Window | Media | Location |
|---|---|---|---|
| Hot | 0–48 h | NVMe | Regional |
| Warm | 2–15 d | HDD / object store | Regional |
| Cold / archive | >15 d (policy-based) | Erasure-coded object / archive | Regional or state DR |
| **Events & metadata** | 30–90 d+ | Indexed store | State core (retained far longer than video — cheap) |

## 6. HA / DR / security at scale
- Redpanda RF=3; PostGIS + event store replicated to DR site; regional autonomy on WAN loss.
- Horizontal scaling: add regions/brokers/GPU pools; stateless services behind load balancers; Kubernetes per region.
- Health/monitoring: per-camera heartbeat, Prometheus/Grafana, gap-analysis (Model 1).
- Security: mTLS on all feeds/events, network segmentation per department, RBAC, tamper-evident audit log, encryption at rest.

## 7. Phased statewide rollout
1. **Pilot** — 2–3 districts, ~2,000 cameras, one regional hub. Validate onboarding, ANPR, cross-camera tracking, HA.
2. **Range expansion** — scale to a full police range; tune GPU/bandwidth ratios against real load.
3. **Statewide** — replicate the regional template across all ranges/districts; connect DB integrations; DR cutover drills.
4. **Private-camera onboarding** — societies/malls (viewing-only, consent-gated) where permitted.

## 8. Headline numbers (for the deck)
- **~200 Gbps** video if centralized → **so we don't**; events are **~1.6 Gbps** peak.
- Video **~32 PB** @ 15 days vs events **~100 TB** @ 30 days → events are **~0.3%** of the data.
- **~600–1,000** distributed accelerators (realistic) vs 2,000 (naive central).
- Core event bus runs at **~5–10%** of a modest cluster's capacity → massive headroom.
