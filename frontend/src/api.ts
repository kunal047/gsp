const env = (import.meta as any).env || {};
const API_BASE = env.VITE_API_BASE || (env.PROD ? "/server" : "http://localhost:8000");
const GATEWAY_BASE = env.VITE_GATEWAY_BASE || (env.PROD ? "/gateway" : "http://localhost:8081");

// --- Auth: identity + role come from a signed JWT (no spoofable headers) ---
export interface Principal {
  user: string;
  role: string; // state_admin | district_officer | viewer
  scope: string; // district for district_officer
}
export interface Session extends Principal {
  token: string;
  full_name?: string;
}

const SESSION_KEY = "netra-session";

function loadSession(): Session | null {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}
let _session: Session | null = loadSession();

export function getSession(): Session | null {
  return _session;
}
export function isAuthenticated(): boolean {
  return !!_session?.token;
}
export function getPrincipal(): Principal {
  return {
    user: _session?.user || "",
    role: _session?.role || "viewer",
    scope: _session?.scope || "",
  };
}
export async function login(username: string, password: string): Promise<Session> {
  const res = await fetch(`${API_BASE}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `login failed (${res.status})`);
  }
  const data = await res.json();
  _session = {
    token: data.access_token,
    user: data.user,
    role: data.role,
    scope: data.scope || "",
    full_name: data.full_name,
  };
  try {
    localStorage.setItem(SESSION_KEY, JSON.stringify(_session));
  } catch {
    /* storage unavailable - session stays in memory for this tab */
  }
  return _session;
}
export function logout() {
  _session = null;
  try {
    localStorage.removeItem(SESSION_KEY);
  } catch {
    /* ignore */
  }
}
function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const headers: Record<string, string> = { ...extra };
  if (_session?.token) headers["Authorization"] = `Bearer ${_session.token}`;
  return headers;
}
function handleUnauthorized(status: number) {
  if (status === 401) {
    logout();
    window.dispatchEvent(new Event("netra-unauthorized"));
  }
}
async function apiGet(path: string) {
  const res = await fetch(`${API_BASE}${path}`, { headers: authHeaders() });
  if (!res.ok) {
    handleUnauthorized(res.status);
    throw new Error(`GET ${path} failed (${res.status})`);
  }
  return res.json();
}
async function apiPost(path: string, body?: any) {
  return fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: authHeaders(body ? { "Content-Type": "application/json" } : {}),
    body: body ? JSON.stringify(body) : undefined,
  });
}
async function apiPatch(path: string, body: any) {
  return fetch(`${API_BASE}${path}`, {
    method: "PATCH",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
  });
}
async function apiDelete(path: string) {
  return fetch(`${API_BASE}${path}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
}

async function downloadApi(path: string, fallbackName: string): Promise<void> {
  const res = await fetch(`${API_BASE}${path}`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`Export failed (${res.status})`);
  const blob = await res.blob();
  const disposition = res.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename="?([^";]+)"?/i);
  const href = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = href;
  link.download = match?.[1] || fallbackName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(href);
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
  const mode = c === "mkv" ? "copy" : "x264";
  return `${GATEWAY_BASE}/gateway/camera/${encodeURIComponent(cam.camera_id)}/stream?c=${mode}`;
}

// Server-side snapshot (one refreshed JPEG per camera). Works for every codec
// incl. H.265, so all cameras can be viewed at once without decoding N live
// streams in the browser.
export function cameraSnapshotUrl(cam: { camera_id: string }): string {
  return `${GATEWAY_BASE}/gateway/camera/${encodeURIComponent(cam.camera_id)}/snapshot`;
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
  source_system: string;
  source_adapter: string;
  external_id: string;
  installed_at: string | null;
  maintenance_status: string;
  last_service_at: string | null;
  next_service_at: string | null;
  eol_at: string | null;
  maintenance_notes: string | null;
  dept_inferred: boolean;
}

export interface Stats {
  total: number;
  by_department: Record<string, number>;
  by_status: Record<string, number>;
  by_type: Record<string, number>;
  by_city: Record<string, number>;
  by_source_system: Record<string, number>;
  analytics_enabled: number;
}

export type CameraCreate = Partial<Omit<Camera, "id">> & {
  camera_id: string;
};

export interface BulkResult {
  inserted: number;
  skipped: number;
  total: number;
}

export type CameraLifecycleUpdate = Pick<
  Camera,
  | "installed_at"
  | "maintenance_status"
  | "last_service_at"
  | "next_service_at"
  | "eol_at"
  | "maintenance_notes"
> & { make: string | null; model: string | null };

export async function updateCameraLifecycle(
  cameraId: string,
  lifecycle: CameraLifecycleUpdate
): Promise<Camera> {
  const res = await apiPatch(
    `/api/cameras/${encodeURIComponent(cameraId)}/lifecycle`,
    lifecycle
  );
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `Lifecycle update failed (${res.status})`);
  }
  return res.json();
}

export async function createCamera(camera: CameraCreate): Promise<Camera> {
  const res = await apiPost(`/api/cameras`, camera);
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `Camera onboarding failed (${res.status})`);
  }
  return res.json();
}

export async function bulkCreateCameras(
  cameras: CameraCreate[]
): Promise<BulkResult> {
  const res = await apiPost(`/api/cameras/bulk`, cameras);
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `Bulk onboarding failed (${res.status})`);
  }
  return res.json();
}

export async function exportCameraRegistry(
  params: Record<string, string> = {}
): Promise<void> {
  const qs = new URLSearchParams(params).toString();
  return downloadApi(
    `/api/reports/cameras.csv${qs ? "?" + qs : ""}`,
    "netra-camera-registry.csv"
  );
}

export async function exportDetectionReport(
  params: Record<string, string>
): Promise<void> {
  const qs = new URLSearchParams(params).toString();
  return downloadApi(
    `/api/reports/detections.csv?${qs}`,
    "netra-movement-evidence.csv"
  );
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
  maintenance_due: number;
  end_of_life: number;
  incomplete_asset_records: number;
  lifecycle_completeness_pct: number;
  thin_coverage: string[];
  districts: {
    city: string;
    total: number;
    online: number;
    degraded: number;
    offline: number;
  }[];
  offline_cameras: { camera_id: string; name: string; city: string; site: string }[];
  maintenance_cameras: {
    camera_id: string;
    name: string;
    city: string;
    maintenance_status: string;
    next_service_at: string | null;
    eol_at: string | null;
  }[];
}
export async function fetchGapAnalysis(): Promise<GapAnalysis> {
  return apiGet(`/api/gap-analysis`);
}

export interface FederationReport {
  systems: {
    source_system: string;
    source_adapter: string;
    cameras: number;
    online: number;
    analytics_enabled: number;
    events: number;
    active_cameras: number;
  }[];
  system_count: number;
  adapter_system_count: number;
  camera_count: number;
  event_count: number;
  federated: boolean;
  demonstration_gap: string | null;
}
export async function fetchFederationReport(): Promise<FederationReport> {
  return apiGet(`/api/reports/federation`);
}

export interface ReadinessReport {
  generated_at: string;
  models: {
    model: number;
    title: string;
    status: "pass" | "partial" | "blocked";
    summary: string;
    checks: { label: string; value: string | number; ok: boolean }[];
    blocker: string | null;
  }[];
}
export async function fetchReadinessReport(): Promise<ReadinessReport> {
  return apiGet(`/api/reports/readiness`);
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
  adapters: {
    key: string;
    source_system: string;
    status: string;
    discovered: number;
    inserted: number;
    error?: string;
  }[];
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
  source_system: string | null;
  source_adapter: string | null;
  event_type: string; // anpr | vehicle
  plate: string | null;
  plate_norm: string | null;
  vehicle_type: string | null;
  color: string | null;
  confidence: number;
  plate_confidence: number | null;
  track_uuid: string | null;
  track_id: number | null;
  track_hits: number;
  class_confidence: number | null;
  color_confidence: number | null;
  snapshot: string | null;
  lat: number | null;
  lng: number | null;
  first_seen: string | null;
  last_seen: string | null;
  ts: string | null;
  ingested_at: string | null;
  time_source: string;
  direction: string | null;
  dwell_seconds: number | null;
  motion_px_per_second: number | null;
  stopped: boolean;
  wrong_way: boolean | null;
}

export interface DetStats {
  total: number;
  anpr: number;
  unique_plates: number;
  active_cameras: number;
}

export function snapshotUrl(path: string | null): string | null {
  if (!path) return null;
  // Evidence in private object storage is served by the authenticated proxy;
  // <img> can't send a Bearer header, so pass the session token in the query.
  if (path.startsWith("/api/evidence/") && _session?.token) {
    const sep = path.includes("?") ? "&" : "?";
    return `${API_BASE}${path}${sep}t=${encodeURIComponent(_session.token)}`;
  }
  return `${API_BASE}${path}`;
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

export interface CameraBaseline {
  camera_id: string;
  baseline: number;
  samples: number;
  peak: number;
  warmed: boolean;
  congestion_threshold: number;
  override: number | null;
}
export interface AlertCalibration {
  warmup_samples: number;
  congestion_floor: number;
  baseline_factor: number;
  cameras: CameraBaseline[];
}
export async function fetchAlertBaselines(): Promise<AlertCalibration> {
  return apiGet(`/api/alerts/baselines`);
}

export interface RoutePoint {
  id: number;
  camera_id: string;
  camera_name: string;
  city: string;
  source_system: string | null;
  source_adapter: string | null;
  lat: number;
  lng: number;
  ts: string;
  plate: string | null;
  vehicle_type: string | null;
  color: string | null;
  snapshot: string | null;
  track_uuid: string | null;
  track_id: number | null;
  track_hits: number;
  class_confidence: number | null;
  first_seen: string | null;
  last_seen: string | null;
  time_source: string;
  direction: string | null;
  dwell_seconds: number | null;
  motion_px_per_second: number | null;
  stopped: boolean;
  wrong_way: boolean | null;
}

export interface PathStop {
  camera_id: string;
  camera_name: string;
  city: string;
  source_system: string | null;
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
  source_system: string | null;
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
  match_confidence: number | null;
  detection_id: number | null;
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
  source_system: string | null;
  severity: string;
  snapshot: string | null;
  acknowledged: boolean;
  ts: string;
  ingested_at: string;
  time_source: string;
}

export interface GroupedAlert extends Alert {
  occurrence_count: number;
  first_ts: string;
}

export function groupAlerts(
  alerts: Alert[],
  windowSeconds = 300
): GroupedAlert[] {
  const groups: GroupedAlert[] = [];
  const latestByKey = new Map<string, GroupedAlert>();
  for (const alert of alerts) {
    const key = [alert.kind, alert.camera_id, alert.case_ref || "", alert.matched_on || ""].join("|");
    const existing = latestByKey.get(key);
    const withinWindow = existing &&
      Math.abs(new Date(existing.ts).getTime() - new Date(alert.ts).getTime()) <= windowSeconds * 1000;
    if (existing && withinWindow) {
      existing.occurrence_count += 1;
      existing.first_ts = alert.ts;
      continue;
    }
    const grouped = { ...alert, occurrence_count: 1, first_ts: alert.ts };
    groups.push(grouped);
    latestByKey.set(key, grouped);
  }
  return groups;
}

export interface AlertEvidence {
  alert_id: number;
  alert_ts: string;
  window_minutes: number;
  camera: Pick<Camera, "camera_id" | "name" | "stream_url" | "container" | "health_status"> | null;
  timeline: {
    id: number;
    ts: string;
    event_type: string;
    plate: string | null;
    vehicle_type: string | null;
    color: string | null;
    confidence: number;
    track_id: number | null;
    track_hits: number;
    class_confidence: number | null;
    time_source: string;
    direction: string | null;
    dwell_seconds: number | null;
    stopped: boolean;
    wrong_way: boolean | null;
    snapshot: string | null;
    is_alert_detection: boolean;
  }[];
}

export async function fetchAlertEvidence(id: number): Promise<AlertEvidence> {
  return apiGet(`/api/alerts/${id}/evidence`);
}

export interface WatchItem {
  id: number;
  category: string;
  label: string;
  kind: string;
  plate_norm: string | null;
  vehicle_type: string | null;
  color: string | null;
  case_ref: string | null;
  reason: string;
  source: string;
  severity: string;
  min_confidence: number;
  min_track_hits: number;
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

export async function fetchWatchlist(
  params: Record<string, string> = {}
): Promise<WatchItem[]> {
  const qs = new URLSearchParams(params).toString();
  return apiGet(`/api/watchlist${qs ? "?" + qs : ""}`);
}

export async function addWatch(item: Record<string, string | number>): Promise<boolean> {
  const res = await apiPost(`/api/watchlist`, item);
  return res.ok;
}

export async function deleteWatch(id: number): Promise<boolean> {
  const res = await apiDelete(`/api/watchlist/${id}`);
  return res.ok;
}
