import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import {
  ackAlert,
  addWatch,
  fetchAlerts,
  fetchWatchlist,
  snapshotUrl,
  type Alert,
  type WatchItem,
} from "./api";

const SEV: Record<string, string> = {
  high: "#ef4444",
  medium: "#f59e0b",
  low: "#eab308",
};
const KIND_LABEL: Record<string, string> = {
  congestion: "CONGESTION",
  surge: "SURGE",
  watchlist: "BOLO",
  feed_offline: "FEED DOWN",
};
const COLORS = ["white", "black", "silver/grey", "red", "orange", "yellow", "green", "blue"];
const TYPES = ["car", "motorcycle", "bus", "truck"];

const OSM_STYLE: any = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
    },
  },
  layers: [
    { id: "bg", type: "background", paint: { "background-color": "#0b0f1a" } },
    { id: "osm", type: "raster", source: "osm", paint: { "raster-opacity": 0.5, "raster-saturation": -0.6 } },
  ],
};

function AlertMap({ alerts }: { alerts: Alert[] }) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const markers = useRef<maplibregl.Marker[]>([]);
  useEffect(() => {
    if (map.current || !container.current) return;
    map.current = new maplibregl.Map({
      container: container.current,
      style: OSM_STYLE,
      center: [72, 22.6],
      zoom: 6,
      attributionControl: false,
    });
  }, []);
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    const draw = () => {
      markers.current.forEach((x) => x.remove());
      markers.current = [];
      alerts.forEach((a) => {
        if (a.lat == null || a.lng == null) return;
        const el = document.createElement("div");
        el.className = "alert-marker";
        el.style.background = SEV[a.severity] || "#ef4444";
        const mk = new maplibregl.Marker({ element: el })
          .setLngLat([a.lng, a.lat])
          .setPopup(
            new maplibregl.Popup({ offset: 14, closeButton: false }).setHTML(
              `<b>${a.reason}</b><div class="popup-row"><span>${a.camera_name} · ${a.city}</span> ${a.source}</div>`
            )
          )
          .addTo(m);
        markers.current.push(mk);
      });
    };
    if (m.isStyleLoaded()) draw();
    else m.once("load", draw);
  }, [alerts]);
  return <div className="alerts-map" ref={container} />;
}

export default function AlertsView() {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [watch, setWatch] = useState<WatchItem[]>([]);
  const [vtype, setVtype] = useState("");
  const [color, setColor] = useState("");
  const [reason, setReason] = useState("");

  const load = async () => {
    try {
      const [a, w] = await Promise.all([
        fetchAlerts({ limit: "60" }),
        fetchWatchlist(),
      ]);
      setAlerts(a);
      setWatch(w);
    } catch {
      /* ignore */
    }
  };
  useEffect(() => {
    load();
    const t = setInterval(load, 2500);
    return () => clearInterval(t);
  }, []);

  const addBolo = async () => {
    if (!vtype && !color) return;
    await addWatch({
      vehicle_type: vtype,
      color,
      reason: reason || `BOLO: ${color} ${vtype}`.trim(),
      source: "Manual",
      severity: "high",
    });
    setVtype("");
    setColor("");
    setReason("");
    load();
  };

  const ack = async (id: number) => {
    await ackAlert(id);
    load();
  };

  return (
    <div className="alerts">
      <div className="alerts-left">
        <div className="watch-section">
          <div className="section-title" style={{ marginTop: 0 }}>
            Operator Watchlist · BOLO
          </div>
          <div className="watch-chips">
            {watch.map((w) => (
              <span key={w.id} className="watch-chip" style={{ borderColor: SEV[w.severity] }}>
                {w.kind === "plate" ? w.plate_norm : `${w.color || ""} ${w.vehicle_type || ""}`.trim()}
                <small>{w.source}</small>
              </span>
            ))}
          </div>
          <div className="watch-add">
            <select value={vtype} onChange={(e) => setVtype(e.target.value)}>
              <option value="">type…</option>
              {TYPES.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
            <select value={color} onChange={(e) => setColor(e.target.value)}>
              <option value="">colour…</option>
              {COLORS.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
            <input
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="reason (optional)"
            />
            <button onClick={addBolo}>+ BOLO</button>
          </div>
        </div>

        <div className="alerts-list">
          {alerts.length === 0 && (
            <div className="hint" style={{ padding: 12 }}>
              No alerts yet. When a detection matches the watchlist, a real-time
              alert appears here.
            </div>
          )}
          {alerts.map((a) => {
            const snap = snapshotUrl(a.snapshot);
            return (
              <div
                key={a.id}
                className={"alert-row" + (a.acknowledged ? " acked" : "")}
                style={{ borderLeftColor: SEV[a.severity] }}
              >
                <div className="alert-thumb">
                  {snap ? <img src={snap} alt="" /> : <div className="det-noimg">!</div>}
                </div>
                <div className="alert-info">
                  <div className="alert-reason">
                    <span className={"kind-badge k-" + a.kind}>
                      {KIND_LABEL[a.kind] || a.kind}
                    </span>
                    {a.reason}
                  </div>
                  <div className="alert-meta">
                    <span className="src-badge">{a.source}</span>
                    {a.kind === "watchlist" &&
                      (a.plate ||
                        `${a.color || ""} ${a.vehicle_type || ""}`.trim() +
                          " · ")}
                    {a.camera_name} · {a.city}
                  </div>
                  <div className="alert-time">
                    {new Date(a.ts).toLocaleTimeString([], { hour12: false })}
                  </div>
                </div>
                {!a.acknowledged ? (
                  <button className="ack-btn" onClick={() => ack(a.id)}>
                    ACK
                  </button>
                ) : (
                  <span className="acked-tag">✓</span>
                )}
              </div>
            );
          })}
        </div>
      </div>
      <AlertMap alerts={alerts} />
    </div>
  );
}
