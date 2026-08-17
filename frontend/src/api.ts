const API_BASE =
  (import.meta as any).env?.VITE_API_BASE || "http://localhost:8000";
const GATEWAY_BASE =
  (import.meta as any).env?.VITE_GATEWAY_BASE || "http://localhost:8081";

// --- RBAC principal (set by the role switcher; sent on every request) ---
export interface Principal {
  user: string;
  role: string; // state_admin | district_officer | viewer
  scope: string; // district for district_officer
}
let _principal: Principal = { user: "control_room", role: "state_admin", scope: "" };
export function setPrincipal(p: Principal) {
  _principal = p;
}
export function getPrincipal(): Principal {
  return _principal;
}
function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  return {
    "X-User": _principal.user,
    "X-Role": _principal.role,
    "X-Scope": _principal.scope,
    ...extra,
  };
}
async function apiGet(path: string) {
  const res = await fetch(`${API_BASE}${path}`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`GET ${path} failed (${res.status})`);
  return res.json();
}
async function apiPost(path: string, body?: any) {
  return fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: authHeaders(body ? { "Content-Type": "application/json" } : {}),
    body: body ? JSON.stringify(body) : undefined,
  });
}

// Browsers can play MP4/WebM (h264) directly. Other containers (MKV/AVI) are
// routed through the ffmpeg stream gateway: MKV(h264) is remuxed (copy), AVI /
// unknown codecs are transcoded to H.264.
export function streamSrc(cam: {
  stream_url: string;
  container: string;
  camera_id: string;
}): string {
  const c = (cam.container || "").toLowerCase();
  if (c === "mp4" || c === "webm") return cam.stream_url;
  const id = cam.camera_id.split("-").pop();
  const mode = c === "mkv" ? "copy" : "x264";
  return `${GATEWAY_BASE}/gateway/stream/${id}?c=${mode}`;
}

export interface Camera {
  id: number;
  camera_id: string;
  name: string;
  department: string;
  department_full: string;
  city: string;
  site: string;
  lat: number;
  lng: number;
  camera_type: string;
  resolution: string;
  make: string;
  model: string;
  protocol: string;
  vms_platform: string;
  stream_url: string;
  storage_type: string;
  retention_days: number;
  connectivity: string;
  health_status: string;
  amc_expiry: string;
  analytics_enabled: boolean;
  coords_approx: boolean;
  codec: string;
  container: string;
  delivery: string;
  source: string;
  dept_inferred: boolean;
}

export interface Stats {
  total: number;
  by_department: Record<string, number>;
  by_status: Record<string, number>;
  by_type: Record<string, number>;
  by_city: Record<string, number>;
  analytics_enabled: number;
}

export async function fetchCameras(
  params: Record<string, string> = {}
): Promise<Camera[]> {
  const qs = new URLSearchParams(params).toString();
  return apiGet(`/api/cameras${qs ? "?" + qs : ""}`);
}

export async function fetchStats(): Promise<Stats> {
  return apiGet(`/api/stats`);
}

export interface GapAnalysis {
  total: number;
  online: number;
  offline: number;
  coverage_pct: number;
  thin_coverage: string[];
  districts: {
    city: string;
    total: number;
    online: number;
    degraded: number;
    offline: number;
  }[];
  offline_cameras: { camera_id: string; name: string; city: string; site: string }[];
}
export async function fetchGapAnalysis(): Promise<GapAnalysis> {
  return apiGet(`/api/gap-analysis`);
}

export interface AuditEntry {
  id: number;
  user: string;
  role: string;
  action: string;
  detail: string;
  ts: string;
}
export async function fetchAudit(): Promise<AuditEntry[]> {
  return apiGet(`/api/audit?limit=80`);
}

export interface Health {
  status: string;
  camera_source: string | null;
  cameras: number;
  ingest_error: string | null;
}

export async function fetchHealth(): Promise<Health> {
  return apiGet(`/api/health`);
}

export async function retryIngest(): Promise<Health> {
  const res = await apiPost(`/api/ingest/retry`);
  if (!res.ok) throw new Error("retry failed");
  return res.json();
}

export interface Detection {
  id: number;
  camera_id: string;
  camera_name: string;
  city: string;
  event_type: string; // anpr | vehicle
  plate: string | null;
  plate_norm: string | null;
  vehicle_type: string | null;
  confidence: number;
  plate_confidence: number | null;
  snapshot: string | null;
  lat: number | null;
  lng: number | null;
  ts: string | null;
}

export interface DetStats {
  total: number;
  anpr: number;
  unique_plates: number;
  active_cameras: number;
}

export function snapshotUrl(path: string | null): string | null {
  return path ? `${API_BASE}${path}` : null;
}

export async function fetchDetections(
  params: Record<string, string> = {}
): Promise<Detection[]> {
  const qs = new URLSearchParams(params).toString();
  return apiGet(`/api/detections${qs ? "?" + qs : ""}`);
}

export async function fetchDetectionStats(): Promise<DetStats> {
  return apiGet(`/api/detections/stats`);
}

export interface RoutePoint {
  id: number;
  camera_id: string;
  camera_name: string;
  city: string;
  lat: number;
  lng: number;
  ts: string;
  plate: string | null;
  vehicle_type: string | null;
  color: string | null;
  snapshot: string | null;
}

export interface PathStop {
  camera_id: string;
  camera_name: string;
  city: string;
  lat: number;
  lng: number;
  first_seen: string;
  last_seen: string;
  count: number;
  snapshot: string | null;
}

export interface TrackResult {
  mode: string;
  query: Record<string, string | null>;
  count: number;
  cameras: number;
  route: RoutePoint[];
  path: PathStop[];
}

export async function fetchTrack(
  params: Record<string, string>
): Promise<TrackResult> {
  const qs = new URLSearchParams(params).toString();
  return apiGet(`/api/track?${qs}`);
}

export interface VehicleStop {
  id: number;
  camera_id: string;
  camera_name: string;
  city: string;
  lat: number;
  lng: number;
  ts: string;
  snapshot: string | null;
  gap_s: number | null;
  dist_km: number | null;
  speed_kmh: number | null;
}

export interface SingleVehicleResult {
  mode: string;
  vehicle_type: string;
  color: string;
  start_id: number;
  hops: number;
  rejected_infeasible: number;
  path: VehicleStop[];
}

export async function fetchTrackVehicle(
  vehicle_type: string,
  color: string
): Promise<SingleVehicleResult> {
  const qs = new URLSearchParams({ vehicle_type, color }).toString();
  return apiGet(`/api/track/vehicle?${qs}`);
}

export interface Alert {
  id: number;
  kind: string; // congestion | surge | watchlist | feed_offline
  watchlist_category: string | null;
  case_ref: string | null;
  matched_on: string | null;
  camera_id: string;
  camera_name: string;
  city: string;
  lat: number | null;
  lng: number | null;
  plate: string | null;
  vehicle_type: string | null;
  color: string | null;
  vehicle_count: number | null;
  reason: string;
  source: string;
  severity: string;
  snapshot: string | null;
  acknowledged: boolean;
  ts: string;
}

export interface WatchItem {
  id: number;
  kind: string;
  plate_norm: string | null;
  vehicle_type: string | null;
  color: string | null;
  reason: string;
  source: string;
  severity: string;
  active: boolean;
}

export async function fetchAlerts(
  params: Record<string, string> = {}
): Promise<Alert[]> {
  const qs = new URLSearchParams(params).toString();
  return apiGet(`/api/alerts${qs ? "?" + qs : ""}`);
}

export async function fetchAlertStats(): Promise<{
  total: number;
  unacknowledged: number;
}> {
  return apiGet(`/api/alerts/stats`);
}

export async function ackAlert(id: number): Promise<boolean> {
  const res = await apiPost(`/api/alerts/${id}/ack`);
  return res.ok; // false if forbidden (viewer role)
}

export async function fetchWatchlist(): Promise<WatchItem[]> {
  return apiGet(`/api/watchlist`);
}

export async function addWatch(item: Record<string, string>): Promise<boolean> {
  const res = await apiPost(`/api/watchlist`, item);
  return res.ok;
}
