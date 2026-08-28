import { useEffect, useMemo, useRef, useState } from "react";
import {
  bulkCreateCameras,
  createCamera,
  exportCameraRegistry,
  fetchCameras,
  getPrincipal,
  updateCameraLifecycle,
  type Camera,
  type CameraCreate,
  type CameraLifecycleUpdate,
} from "./api";

const EMPTY: CameraCreate = {
  camera_id: "",
  name: "",
  department: "",
  city: "",
  site: "",
  stream_url: "",
  protocol: "RTSP",
  container: "mp4",
  health_status: "online",
  analytics_enabled: true,
  source: "Participant-provided",
};

function parseCsv(text: string): Record<string, string>[] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    if (char === '"' && quoted && text[i + 1] === '"') {
      cell += '"';
      i += 1;
    } else if (char === '"') quoted = !quoted;
    else if (char === "," && !quoted) {
      row.push(cell.trim());
      cell = "";
    } else if ((char === "\n" || char === "\r") && !quoted) {
      if (char === "\r" && text[i + 1] === "\n") i += 1;
      row.push(cell.trim());
      if (row.some(Boolean)) rows.push(row);
      row = [];
      cell = "";
    } else cell += char;
  }
  row.push(cell.trim());
  if (row.some(Boolean)) rows.push(row);
  if (rows.length < 2) return [];
  const headers = rows[0].map((h) => h.trim().toLowerCase());
  return rows.slice(1).map((values) =>
    Object.fromEntries(headers.map((header, i) => [header, values[i] || ""]))
  );
}

function csvCamera(row: Record<string, string>): CameraCreate {
  const number = (value: string) => value === "" ? undefined : Number(value);
  return {
    camera_id: row.camera_id,
    name: row.name,
    department: row.department,
    city: row.city,
    site: row.site,
    lat: number(row.lat),
    lng: number(row.lng),
    camera_type: row.camera_type || "IP",
    protocol: row.protocol || "RTSP",
    stream_url: row.stream_url,
    codec: row.codec || "h264",
    container: row.container || "mp4",
    health_status: row.health_status || "online",
    analytics_enabled: !["false", "0", "no"].includes(
      (row.analytics_enabled || "true").toLowerCase()
    ),
    source: row.source || "Participant-provided CSV",
  };
}

export default function RegistryView({ onChanged }: { onChanged?: () => void }) {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [query, setQuery] = useState("");
  const [department, setDepartment] = useState("");
  const [status, setStatus] = useState("");
  const [form, setForm] = useState<CameraCreate>(EMPTY);
  const [showForm, setShowForm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [editing, setEditing] = useState<Camera | null>(null);
  const [lifecycle, setLifecycle] = useState<CameraLifecycleUpdate | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const canAct = getPrincipal().role !== "viewer";

  const load = () => fetchCameras().then(setCameras).catch(() => setMessage("Registry API unavailable."));
  useEffect(() => { void load(); }, []);

  const departments = useMemo(
    () => [...new Set(cameras.map((c) => c.department).filter(Boolean))].sort(),
    [cameras]
  );
  const filtered = useMemo(() => {
    const term = query.toLowerCase();
    return cameras.filter((camera) =>
      (!term || [camera.camera_id, camera.name, camera.site, camera.city].some((v) => (v || "").toLowerCase().includes(term))) &&
      (!department || camera.department === department) &&
      (!status || camera.health_status === status)
    );
  }, [cameras, query, department, status]);

  const setField = (field: keyof CameraCreate, value: string | boolean) =>
    setForm((current) => ({ ...current, [field]: value }));

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!form.camera_id || !form.name || !form.city || !form.stream_url) {
      setMessage("Camera ID, name, district and stream URL are required.");
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      await createCamera({
        ...form,
        lat: form.lat === undefined || form.lat === null || String(form.lat) === "" ? undefined : Number(form.lat),
        lng: form.lng === undefined || form.lng === null || String(form.lng) === "" ? undefined : Number(form.lng),
      });
      setForm(EMPTY);
      setShowForm(false);
      setMessage("Camera onboarded and recorded in the audit trail.");
      await load();
      onChanged?.();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Onboarding failed.");
    } finally { setBusy(false); }
  };

  const importCsv = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setBusy(true);
    setMessage("");
    try {
      const rows = parseCsv(await file.text());
      if (!rows.length || !rows.every((row) => row.camera_id)) {
        throw new Error("CSV needs a header row and a camera_id in every record.");
      }
      const result = await bulkCreateCameras(rows.map(csvCamera));
      setMessage(`${result.inserted} cameras onboarded · ${result.skipped} existing skipped.`);
      await load();
      onChanged?.();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "CSV import failed.");
    } finally { setBusy(false); }
  };

  const exportRows = async () => {
    setMessage("");
    try {
      await exportCameraRegistry({
        ...(query ? { q: query } : {}),
        ...(department ? { department } : {}),
        ...(status ? { health_status: status } : {}),
      });
      setMessage(`${filtered.length} visible registry rows exported.`);
    } catch { setMessage("Registry export failed."); }
  };

  const editLifecycle = (camera: Camera) => {
    setEditing(camera);
    setLifecycle({
      make: camera.make || null,
      model: camera.model || null,
      installed_at: camera.installed_at,
      maintenance_status: camera.maintenance_status || "unknown",
      last_service_at: camera.last_service_at,
      next_service_at: camera.next_service_at,
      eol_at: camera.eol_at,
      maintenance_notes: camera.maintenance_notes,
    });
  };

  const dateInput = (value: string | null) => value ? value.slice(0, 16) : "";
  const saveLifecycle = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!editing || !lifecycle) return;
    setBusy(true);
    setMessage("");
    try {
      const iso = (value: string | null) => value ? new Date(value).toISOString() : null;
      await updateCameraLifecycle(editing.camera_id, {
        ...lifecycle,
        installed_at: iso(lifecycle.installed_at),
        last_service_at: iso(lifecycle.last_service_at),
        next_service_at: iso(lifecycle.next_service_at),
        eol_at: iso(lifecycle.eol_at),
      });
      setMessage(`${editing.camera_id} lifecycle updated and audited.`);
      setEditing(null);
      setLifecycle(null);
      await load();
      onChanged?.();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Lifecycle update failed.");
    } finally { setBusy(false); }
  };

  return (
    <section className="registry" aria-label="Camera registry">
      <div className="registry-head">
        <div>
          <span className="eyebrow">MODEL 1 · COMMON FOUNDATION</span>
          <h1>Camera registry</h1>
          <p>Search, onboard and audit heterogeneous government and participant-provided feeds.</p>
        </div>
        <div className="registry-actions">
          <button onClick={exportRows}>Export CSV</button>
          {canAct && <button onClick={() => fileRef.current?.click()} disabled={busy}>Import CSV</button>}
          {canAct && <button className="primary" onClick={() => setShowForm((value) => !value)}>+ Add camera</button>}
          <input ref={fileRef} type="file" accept=".csv,text/csv" hidden onChange={importCsv} />
        </div>
      </div>

      <div className="registry-tools">
        <input aria-label="Search registry" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search ID, camera, site or district" />
        <select value={department} onChange={(e) => setDepartment(e.target.value)}>
          <option value="">All departments</option>
          {departments.map((value) => <option key={value}>{value}</option>)}
        </select>
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All health states</option>
          <option>online</option><option>degraded</option><option>offline</option>
        </select>
        <span>{filtered.length} / {cameras.length} cameras</span>
      </div>

      {showForm && (
        <form className="registry-form" onSubmit={submit}>
          <div className="form-title"><strong>Onboard a camera</strong><span>Adapter metadata is retained for interoperability and audit.</span></div>
          {(["camera_id", "name", "city", "site", "department", "stream_url"] as const).map((field) => (
            <label key={field}><span>{field.replace("_", " ")}{["camera_id", "name", "city", "stream_url"].includes(field) ? " *" : ""}</span><input value={String(form[field] || "")} onChange={(e) => setField(field, e.target.value)} /></label>
          ))}
          <label><span>protocol</span><select value={form.protocol} onChange={(e) => setField("protocol", e.target.value)}><option>RTSP</option><option>HTTP</option><option>HLS</option><option>ONVIF</option></select></label>
          <label><span>container</span><select value={form.container} onChange={(e) => setField("container", e.target.value)}><option>mp4</option><option>mkv</option><option>webm</option><option>avi</option></select></label>
          <label><span>latitude</span><input type="number" step="any" value={String(form.lat ?? "")} onChange={(e) => setField("lat", e.target.value)} /></label>
          <label><span>longitude</span><input type="number" step="any" value={String(form.lng ?? "")} onChange={(e) => setField("lng", e.target.value)} /></label>
          <label className="registry-check"><input type="checkbox" checked={Boolean(form.analytics_enabled)} onChange={(e) => setField("analytics_enabled", e.target.checked)} /> Analytics enabled</label>
          <div className="form-actions"><button type="button" onClick={() => setShowForm(false)}>Cancel</button><button className="primary" disabled={busy}>{busy ? "Onboarding…" : "Onboard camera"}</button></div>
        </form>
      )}

      {editing && lifecycle && (
        <form className="registry-form lifecycle-form" onSubmit={saveLifecycle}>
          <div className="form-title">
            <strong>Asset lifecycle · {editing.name}</strong>
            <span>{editing.camera_id} · dates must be verified from department records</span>
          </div>
          <label><span>maintenance status</span><select value={lifecycle.maintenance_status} onChange={(e) => setLifecycle({ ...lifecycle, maintenance_status: e.target.value })}>
            <option>unknown</option><option>healthy</option><option>due</option><option>overdue</option><option>under_maintenance</option><option>retired</option>
          </select></label>
          <label><span>camera make</span><input value={lifecycle.make || ""} onChange={(e) => setLifecycle({ ...lifecycle, make: e.target.value || null })} maxLength={200} /></label>
          <label><span>camera model</span><input value={lifecycle.model || ""} onChange={(e) => setLifecycle({ ...lifecycle, model: e.target.value || null })} maxLength={200} /></label>
          {(["installed_at", "last_service_at", "next_service_at", "eol_at"] as const).map((field) => (
            <label key={field}><span>{field.replaceAll("_", " ")}</span><input type="datetime-local" value={dateInput(lifecycle[field])} onChange={(e) => setLifecycle({ ...lifecycle, [field]: e.target.value || null })} /></label>
          ))}
          <label className="lifecycle-notes"><span>maintenance notes</span><textarea value={lifecycle.maintenance_notes || ""} onChange={(e) => setLifecycle({ ...lifecycle, maintenance_notes: e.target.value || null })} maxLength={2000} /></label>
          <div className="form-actions"><button type="button" onClick={() => { setEditing(null); setLifecycle(null); }}>Cancel</button><button className="primary" disabled={busy}>{busy ? "Saving…" : "Save lifecycle"}</button></div>
        </form>
      )}

      {message && <div className="registry-message" role="status">{message}</div>}
      {!canAct && <div className="registry-message">Viewer role is read-only. Export remains available.</div>}

      <div className="registry-table-wrap">
        <table className="registry-table">
          <thead><tr><th>Camera</th><th>Location</th><th>Department</th><th>Integration</th><th>Health</th><th>Lifecycle</th><th>Provenance</th></tr></thead>
          <tbody>{filtered.map((camera) => (
            <tr key={camera.camera_id}>
              <td><strong>{camera.name || "Unnamed camera"}</strong><code>{camera.camera_id}</code></td>
              <td>{camera.site || "-"}<small>{camera.city || "Unknown district"}</small></td>
              <td>{camera.department || "-"}</td>
              <td>{camera.protocol || "-"} · {camera.container || camera.codec || "unknown"}<small>{camera.analytics_enabled ? "Analytics enabled" : "View only"}</small></td>
              <td><span className={`health-chip ${camera.health_status}`}>{camera.health_status || "unknown"}</span></td>
              <td><span className={`maintenance-chip ${camera.maintenance_status}`}>{camera.maintenance_status || "unknown"}</span>{camera.next_service_at && <small>Next {new Date(camera.next_service_at).toLocaleDateString()}</small>}{canAct && <button className="table-action" onClick={() => editLifecycle(camera)}>Manage</button>}</td>
              <td>{camera.source || "Unspecified"}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
    </section>
  );
}
