import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  addWatch,
  deleteWatch,
  fetchWatchlist,
  getPrincipal,
  type WatchItem,
} from "./api";

const CATEGORIES: Record<string, string> = {
  stolen_vehicle: "Stolen vehicle",
  blacklisted_vehicle: "Blacklisted vehicle",
  suspect_vehicle: "Suspect vehicle",
  wanted_person: "Wanted person",
  missing_person: "Missing person",
};
const COLORS = ["white", "black", "silver/grey", "red", "orange", "yellow", "green", "blue"];
const TYPES = ["car", "motorcycle", "bus", "truck"];

const title = (value: string) => CATEGORIES[value] || value.replaceAll("_", " ");

export default function WatchlistView() {
  const [items, setItems] = useState<WatchItem[]>([]);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState({
    category: "suspect_vehicle",
    plate_norm: "",
    vehicle_type: "",
    color: "",
    case_ref: "",
    reason: "",
    severity: "high",
    min_confidence: "0.65",
    min_track_hits: "3",
  });
  const [message, setMessage] = useState("");

  const load = () => fetchWatchlist().then(setItems).catch(() => setMessage("Could not load watchlist."));
  useEffect(() => {
    void load();
  }, []);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return items.filter((item) => {
      if (category && item.category !== category) return false;
      if (!needle) return true;
      return [item.label, item.plate_norm, item.case_ref, item.reason]
        .some((value) => value?.toLowerCase().includes(needle));
    });
  }, [items, query, category]);

  const counts = useMemo(() => items.reduce<Record<string, number>>((acc, item) => {
    acc[item.category] = (acc[item.category] || 0) + 1;
    return acc;
  }, {}), [items]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setMessage("");
    if (!form.plate_norm && !form.vehicle_type && !form.color) {
      setMessage("Enter a plate or at least one vehicle attribute.");
      return;
    }
    const ok = await addWatch(form);
    if (!ok) {
      setMessage("This role cannot add watchlist entries.");
      return;
    }
    setForm({ ...form, plate_norm: "", vehicle_type: "", color: "", case_ref: "", reason: "" });
    setFormOpen(false);
    setMessage("Watchlist entry added.");
    load();
  };

  const remove = async (item: WatchItem) => {
    if (!window.confirm(`Remove “${item.label}” from the watchlist?`)) return;
    const ok = await deleteWatch(item.id);
    setMessage(ok ? "Watchlist entry removed." : "This role cannot remove watchlist entries.");
    if (ok) load();
  };

  const canAct = getPrincipal().role !== "viewer";

  return (
    <div className="watchlist-view">
      <div className="watchlist-head">
        <div>
          <div className="watchlist-eyebrow">Representative dataset · live matching enabled</div>
          <h2>Watchlist</h2>
          <p>Vehicles are matched against live ANPR and visual attributes. Person matching is retained as a deployment roadmap item.</p>
        </div>
        <button className="primary-btn" disabled={!canAct} onClick={() => setFormOpen(!formOpen)}>
          {formOpen ? "Close" : "+ Add entry"}
        </button>
      </div>

      <div className="watchlist-summary">
        <button className={!category ? "active" : ""} onClick={() => setCategory("")}><b>{items.length}</b><span>All records</span></button>
        {Object.entries(CATEGORIES).map(([key, label]) => (
          <button key={key} className={category === key ? "active" : ""} onClick={() => setCategory(category === key ? "" : key)}>
            <b>{counts[key] || 0}</b><span>{label}</span>
          </button>
        ))}
      </div>

      {formOpen && (
        <form className="watchlist-form" onSubmit={submit}>
          <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
            {Object.entries(CATEGORIES).slice(0, 3).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
          </select>
          <input aria-label="Registration plate" placeholder="Plate, e.g. GJ01AB1234" value={form.plate_norm} onChange={(e) => setForm({ ...form, plate_norm: e.target.value })} />
          <select value={form.vehicle_type} onChange={(e) => setForm({ ...form, vehicle_type: e.target.value })}><option value="">Vehicle type</option>{TYPES.map((x) => <option key={x}>{x}</option>)}</select>
          <select value={form.color} onChange={(e) => setForm({ ...form, color: e.target.value })}><option value="">Colour</option>{COLORS.map((x) => <option key={x}>{x}</option>)}</select>
          <input placeholder="Case / FIR reference" value={form.case_ref} onChange={(e) => setForm({ ...form, case_ref: e.target.value })} />
          <input className="reason-input" placeholder="Reason" required value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} />
          <select value={form.severity} onChange={(e) => setForm({ ...form, severity: e.target.value })}><option value="high">High severity</option><option value="medium">Medium severity</option><option value="low">Low severity</option></select>
          <input aria-label="Minimum confidence" type="number" min="0.5" max="1" step="0.05" value={form.min_confidence} onChange={(e) => setForm({ ...form, min_confidence: e.target.value })} title="Minimum detector or OCR confidence" />
          <input aria-label="Minimum track observations" type="number" min="2" max="20" step="1" value={form.min_track_hits} onChange={(e) => setForm({ ...form, min_track_hits: e.target.value })} title="Frames required before matching" />
          <button className="primary-btn" type="submit">Add to watchlist</button>
        </form>
      )}

      <div className="watchlist-tools">
        <input type="search" placeholder="Search plate, label, case or reason…" value={query} onChange={(e) => setQuery(e.target.value)} />
        <span>{filtered.length} of {items.length} records</span>
      </div>
      {message && <div className="watchlist-message">{message}</div>}

      <div className="watchlist-table-wrap">
        <table className="watchlist-table">
          <thead><tr><th>Subject</th><th>Category</th><th>Match rule</th><th>Case</th><th>Severity</th><th>Status</th><th /></tr></thead>
          <tbody>
            {filtered.map((item) => (
              <tr key={item.id}>
                <td><strong>{item.label}</strong><small>{item.reason}</small></td>
                <td><span className="category-pill">{title(item.category)}</span></td>
                <td>{item.kind === "plate" ? <code>{item.plate_norm}</code> : item.kind === "person" ? <span className="roadmap">Face recognition · roadmap</span> : <span className="attribute-rule">{item.color} {item.vehicle_type}</span>} {item.kind !== "person" && <small>≥ {(item.min_confidence * 100).toFixed(0)}% · {item.min_track_hits} observations</small>}</td>
                <td>{item.case_ref || "—"}</td>
                <td><span className={`severity-dot ${item.severity}`} />{item.severity}</td>
                <td><span className={item.kind === "person" ? "status-muted" : "status-live"}>{item.kind === "person" ? "Pending integration" : "Live matching"}</span></td>
                <td><button className="remove-btn" disabled={!canAct} onClick={() => remove(item)} title="Remove entry">×</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
