# Netra — Fix Plan and Alternatives

Companion to `NETRA_IMPROVEMENT_REVIEW.md`. That file says *what* is wrong; this one says *how* I would fix it, and where a different approach beats patching the current one.

The requirement, reduced to one sentence: **onboard ~50 live feeds and, given a registration number on the day, return that vehicle's complete route with a timestamped, location-wise movement history — from real working software.** Everything below is judged against that.

---

## Part 1 — Fix the current architecture (evolutionary path)

### 1.1 Analytics coverage: from 6 feeds to all of them

The root problem is one synchronous loop doing decode → detect → plate → OCR → HTTP for six cameras. Four changes, each independently shippable:

**(a) Lease-based camera assignment instead of a static `MAX_STREAMS` slice.**
Workers claim cameras through Redis with a TTL, so any number of worker replicas self-balance and a newly onboarded camera is picked up within one lease period. No new backend endpoint is needed — Redis is already in the stack.

```python
# analytics/assign.py
LEASE = 30  # seconds

def claim_cameras(r, worker_id, wanted, all_ids):
    mine = []
    for cid in all_ids:
        key = f"netra:lease:{cid}"
        # take it if free, or refresh it if it is already mine
        if r.set(key, worker_id, nx=True, ex=LEASE) or r.get(key) == worker_id:
            r.expire(key, LEASE)
            mine.append(cid)
        if len(mine) >= wanted:
            break
    return mine
```

The worker re-runs `get_cameras()` + `claim_cameras()` every 20 s, opens/closes captures on the diff, and `docker compose up --scale analytics=8` gives eight workers. `MAX_STREAMS` becomes "per worker," which is what it should have meant.

**(b) Decouple capture from inference.**
One capture thread per camera writes the *latest* decoded frame into a single-slot mailbox (drop stale frames; never queue them). One inference loop drains the mailboxes. A stalled `cap.read()` now blocks only its own thread, and inference always sees the freshest frame, which matters for the multi-frame plate consensus.

```python
class Mailbox:
    def __init__(self): self.frame, self.pts, self.lock = None, None, threading.Lock()
    def put(self, frame, pts):
        with self.lock: self.frame, self.pts = frame, pts
    def take(self):
        with self.lock:
            f, p = self.frame, self.pts; self.frame = None; return f, p
```

**(c) Cut the per-frame cost, in this order (each is a one-line-ish change with a large effect):**

1. *Motion gate.* Downscale to 320 px grey, `cv2.absdiff` against the previous frame, skip inference if the changed-pixel fraction is below a threshold. Idle cameras drop to near-zero cost.
2. *Plate detector on vehicle crops, not the full frame.* Today `self.plate(masked, imgsz=1280)` is a second full-frame pass and the most expensive step. Instead, collect vehicle boxes with width ≥ `MIN_VEHICLE_W` (say 120 px — below that the plate can't reach the 45 px OCR floor anyway), crop them, and call `self.plate(list_of_crops, imgsz=320)` once as a batch.
3. *OCR once per track.* Keep a per-track OCR budget: read until consensus (3 agreements) or until N attempts; then stop reading that track. Today every frame re-runs OCR on every visible plate.
4. *Vehicle detector at `imgsz=640`* (default) — check it is not inheriting 1280.

Together these typically move a wide-angle traffic frame from ~5 s to well under 1 s on the same CPU. Re-measure with `bench/analytics_cost.py` and put the numbers in BENCHMARK.md.

**(d) GPU path.** `Dockerfile.gpu` (`nvidia/cuda` base, `torch` with CUDA, `easyocr.Reader(gpu=True)`), `deploy.resources.reservations.devices` in compose. Batch frames from several cameras into one `self.vehicle([f1, f2, ...])` call — Ultralytics batches natively and that is where GPU throughput comes from.

### 1.2 Tracking output: make it evidence-grade

**Time window and correct limiting** — add `since`/`until` to `/track` and `/track/vehicle`; order by `ts DESC` for the limit, then reverse for display.

**OCR-confusion-aware plate matching in the database.** Add a `plate_class` column populated on ingest by collapsing OCR-confusable characters to a class token, and index it. Exact match on `plate_class` gives O(log n) lookups that tolerate the misreads ANPR actually produces, and the UI can explain the match ("read as GJ01AB1Z34, matched GJ01AB1234 — Z/2").

```python
CONFUSION = str.maketrans({"O":"0","D":"0","Q":"0","B":"8","I":"1","L":"1",
                           "S":"5","Z":"2","G":"6","T":"7","A":"4"})
def plate_class(norm: str) -> str: return norm.translate(CONFUSION)
```

Keep `pg_trgm` similarity as the second tier for partial recalls ("I only remember AB1234"), replacing the Python Levenshtein scan. Migration: `CREATE EXTENSION pg_trgm; CREATE INDEX ... USING gin (plate_norm gin_trgm_ops);`.

**Route reconstruction as a shortest-path problem rather than a greedy walk.** Build a DAG of candidate sightings ordered by time; edge weight = `-log(plate_or_appearance_score) + travel_time_penalty` where the penalty is `|dt − expected_dt|` and infinite if `dt < dist / MAX_SPEED`. Run Viterbi/Dijkstra from the earliest confident sighting. It returns the globally most plausible route, not the locally best next hop, and naturally yields a per-hop and whole-route confidence. Use OSRM `table` (or a cached inter-camera travel-time matrix — 50 cameras is a 2,500-cell table computed once) so `expected_dt` reflects roads, not straight lines.

**PDF case report** (`/api/reports/case/{query_id}.pdf`, reportlab): plate, query time and operator, static route map (MapLibre → PNG via a headless render, or a Static Maps tile stitch), a table of stops with camera, district, coordinates, first/last seen, hop distance/speed/confidence, evidence thumbnails, and SHA-256 of each evidence object. This is the artefact the challenge asks for.

### 1.3 Backend: make "stateless" true

Split `main.py`'s background threads into `backend/app/scheduler.py` with its own compose service (`command: python -m app.scheduler`). Move `_evidence_seen`, the dirty-baseline set and `INGEST` status to Redis. Add `GET /api/events` as an SSE endpoint that `XREAD`s the `detections` stream (and a new `alerts` stream) so the UI stops polling. The API service is then a pure request handler; the benchmark's linear-scaling claim becomes true.

### 1.4 Security, in one sitting

Gateway: accept `?t=<jwt>` on stream/snapshot, verify with the same HMAC secret (share `auth.verify_token`), delete the legacy numeric endpoints. Backend: remove the `/snapshots` static mount and serve local files via the evidence proxy; short-lived evidence URLs (`/api/evidence/{key}?exp=…&sig=…`); a `service` role for the worker; a `scoped_cameras(principal)` helper applied in every router plus one parametrised test that hits every GET as `district_officer` and asserts no out-of-district `camera_id` in the response; Pydantic bodies everywhere; hash-chain on `audit_log`.

---

## Part 2 — Alternative approaches

These are not refinements; they change *how* the requirement is met. I would seriously consider the first one for the scored test.

### 2.1 Record-then-search (forensic ANPR) instead of live-sample-everything

The scored test hands you the plate **on the day**. Nothing requires the sightings to have been extracted before the plate is known. So instead of trying to run full ANPR on 50 live feeds in real time (a GPU-fleet problem), do this:

1. **Record every feed continuously, cheaply.** `ffmpeg -i <src> -c copy -f segment -segment_time 60 cam{id}/%Y%m%d-%H%M.ts` — no decoding, ~2.5 Mbps per camera, 50 feeds ≈ 125 Mbps ≈ 56 GB/hour on a laptop SSD. Segments are indexed in Postgres by `(camera_id, start_ts, end_ts)`.
2. **Keep the live path, but make it light.** Run vehicle detection + colour + tracking at low resolution on every feed (cheap — this is where motion-gating and `imgsz=416` make 50 feeds feasible on CPU), so the map, video wall, congestion/surge alerts, attribute search and the *live detections* panel all keep working. Skip plate detection/OCR on the live path entirely, or run it only on cameras flagged ANPR-grade.
3. **When the plate arrives, search on demand.** Fan the recorded segments out to N parallel ANPR workers (same `anpr.py`, no changes), prioritised by any live attribute hits and by time proximity, and stream results into the same `detection_events` table. Every frame of every camera can be examined for *that one plate*, at whatever frame rate the plate needs — a 30-minute window across 50 cameras is ~1,500 camera-minutes; at 5 fps and 0.2 s/frame on GPU that is under 10 minutes wall-clock on one GPU, and it parallelises linearly.
4. **Route reconstruction and the report are unchanged** — they read from `detection_events`.

Why this is better for the test: there is no sampling gap, so a vehicle that crossed a camera *cannot* be missed for lack of compute; OCR gets every frame of the pass rather than one, which is exactly what multi-frame consensus wants; and the demo has a compelling shape — "here is the plate… searching 50 feeds… route appears stop by stop." It also matches how real forensic ANPR works and how police actually investigate.

Why it still fits the HLD: recording at the edge/regional tier *is* the design ("video stays near its source, regional hot storage 0–48 h"). The state-core thesis (events, not video) is untouched; what changes is that the *regional* tier can re-scan its own hot storage on demand. That is an honest strengthening of SCALABILITY.md, not a contradiction of it.

The cost is an hour of engineering for the recorder service, a `segments` table, and a `search_jobs` queue (Redis list; workers `BLPOP`). I would do this **and** the Part 1.1 optimisations — they are complementary, not either/or.

### 2.2 Decode with ffmpeg, infer from a frame bus

Fifty `cv2.VideoCapture` loops in Python are a poor way to decode 50 H.264/H.265 streams. Alternative: one `ffmpeg` per camera emits low-fps JPEGs (`-vf fps=5,scale=640:-1 -f image2pipe`) that a tiny sidecar pushes into a Redis stream per camera with the PTS. Inference workers are pure consumers — no OpenCV capture code, no reconnect logic (MediaMTX/ffmpeg handle it), trivially horizontally scaled, and the "event bus" becomes load-bearing at the frame level too. This is the shape of Frigate/DeepStream without the framework.

### 2.3 Replace the OCR engine and plate detector

EasyOCR is a general scene-text model and is the slow, error-prone part of the chain. A purpose-built plate OCR (`fast-plate-ocr` — a small ONNX CRNN, ~1–3 ms per plate on CPU — or PaddleOCR's rec model) is typically 20–50× faster and more accurate on plates. Pair it with a plate detector fine-tuned on Indian plates (several open datasets exist; a YOLOv8n fine-tune is a two-hour job on Colab). Keep the multi-frame consensus and Indian-format regex as they are. This is the single change that most improves the "video analytics output" score, and it is a drop-in inside `anpr._read_plate`.

### 2.4 Whole-pipeline GPU (DeepStream / hardware decode)

For the 80,000-camera answer rather than the demo: NVIDIA DeepStream (or a hand-rolled PyAV + NVDEC + TensorRT pipeline) decodes and infers on the GPU, and one T4/L4 handles ~30–50 streams at 5–10 fps end to end. It is a bigger engineering lift and vendor-specific, so I would present it as the regional-tier reference implementation in the HLD and keep the Python worker as the portable one.

### 2.5 MediaMTX as the real gateway

Already in the stack for the second-system demo. Point *all* sources at it (RTSP/HLS pull on demand), have the video wall play WebRTC/HLS from it, and let the analytics workers consume its RTSP re-publish. One decode per source regardless of viewers, sub-second wall latency, and the per-viewer ffmpeg gateway shrinks to a legacy-container shim. The docs already say this is the production design; doing it in the prototype removes a whole class of "50 ffmpeg processes" failure modes on demo day.

---

## Part 3 — What I would actually do, in order

1. **Record-then-search** (2.1) plus the **motion gate and crop-only plate detection** (1.1c). This makes the scored test robust to compute on day one.
2. **Plate OCR swap** (2.3) and **confusion-class matching** (1.2). This raises the quality of every plate read and every match.
3. **Lease-based worker sharding + mailbox capture** (1.1a–b), **scheduler service + SSE** (1.3). This makes the live path scale and the UI feel live.
4. **Security pass** (1.4) — a day, and it closes every doc-vs-code gap in that area.
5. **Viterbi route reconstruction with a travel-time matrix + PDF case report** (1.2). This is what the judges hold in their hands.
6. MediaMTX-as-gateway (2.5), ONVIF adapter, re-ID, cases/departments — Phase 2.

Items 1, 2 and 4 are each a focused day or two. I can start on any of them directly in the repo.
