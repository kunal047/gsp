# Netra Registry and Federation API

The interactive OpenAPI specification is available at
`http://localhost:8000/docs`. Requests may include `X-User`, `X-Role` and
`X-Scope`; write operations require `state_admin` or an in-scope
`district_officer`.

## Model 1 — registry and asset lifecycle

- `GET /api/cameras` — filter by department, status, type, city, analytics flag,
  source system or free-text query.
- `POST /api/cameras` — manually onboard one camera.
- `POST /api/cameras/bulk` — onboard a validated JSON/CSV-derived batch.
- `PATCH /api/cameras/{camera_id}/lifecycle` — update installation, service,
  maintenance, end-of-life and notes fields.
- `GET /api/stats` — registry totals grouped by department, status, type, city
  and source system.
- `GET /api/gap-analysis` — coverage, offline feeds, thin districts,
  maintenance due, EOL assets and metadata completeness.
- `GET /api/reports/cameras.csv` — audited, spreadsheet-safe registry export.

## Model 2 — viewing and searchable analytics

- `GET /gateway/camera/{camera_id}/snapshot` — codec-independent JPEG from a
  backend-registered source URL.
- `GET /gateway/camera/{camera_id}/stream?c=copy|x264` — on-demand fragmented
  MP4 relay/remux/transcode; the gateway never accepts arbitrary URLs.
- `GET /api/detections` and `/api/detections/stats` — evidence-backed tracked
  events only.
- `GET /api/track` and `/api/track/vehicle` — plate or attribute movement
  history and space-time-gated route reconstruction.
- `GET /api/reports/detections.csv` — timestamped movement-evidence export.

## Model 3 — adapters and federation

- `GET /api/adapters` — configured source adapters and persisted coverage.
- `POST /api/ingest/adapters` — discover all configured systems independently;
  one unreachable system does not hide healthy systems.
- `GET /api/reports/federation` — per-system cameras, online feeds, analytics
  coverage and events. `federated=true` only when at least two non-manual,
  adapter-backed source systems exist.

Configure independent RTSP/ONVIF-style sources with `RTSP_SOURCES_JSON`; see
`.env.example`. Source credentials remain server-side and are never exposed as
gateway query parameters.
