import { useEffect, useMemo, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import {
  ackAlert,
  addWatch,
  fetchAlertEvidence,
  fetchAlerts,
  fetchWatchlist,
  groupAlerts,
  snapshotUrl,
  streamSrc,
  type Alert,
  type AlertEvidence,
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

function EvidenceViewer({ alert, onClose }: { alert: Alert; onClose: () => void }) {
  const [evidence, setEvidence] = useState<AlertEvidence | null>(null);
  const [selectedSnapshot, setSelectedSnapshot] = useState(alert.snapshot);
  const [mode, setMode] = useState<"evidence" | "live">("evidence");
  const [imageSize, setImageSize] = useState<[number, number] | null>(null);

  useEffect(() => {
    fetchAlertEvidence(alert.id).then(setEvidence).catch(() => {});
  }, [alert.id]);

  const selectedUrl = snapshotUrl(selectedSnapshot);
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="evidence-modal" onClick={(e) => e.stopPropagation()}>
        <div className="evidence-head">
          <div>
            <span className={"kind-badge k-" + alert.kind}>{KIND_LABEL[alert.kind] || alert.kind}</span>
            <strong>{alert.reason}</strong>
            <small>
              {alert.camera_name} · {alert.city} · {new Date(alert.ts).toLocaleString()}
              {alert.match_confidence != null ? ` · match ${(alert.match_confidence * 100).toFixed(0)}%` : ""}
              {` · ${alert.time_source.replace("_", " ")} time`}
            </small>
          </div>
          <button onClick={onClose}>✕</button>
        </div>
        <div className="evidence-tabs">
          <button className={mode === "evidence" ? "active" : ""} onClick={() => setMode("evidence")}>Event evidence</button>
          <button className={mode === "live" ? "active" : ""} onClick={() => setMode("live")}>Live camera</button>
          <span>± {evidence?.window_minutes || 5} minute timeline</span>
        </div>
        <div className="evidence-stage">
          {mode === "live" && evidence?.camera ? (
            <video src={streamSrc(evidence.camera)} autoPlay muted controls playsInline />
          ) : selectedUrl ? (
            <img
              className={imageSize && Math.max(...imageSize) < 320 ? "low-res-evidence" : ""}
              src={selectedUrl}
              alt="Alert evidence"
              onLoad={(event) => setImageSize([event.currentTarget.naturalWidth, event.currentTarget.naturalHeight])}
            />
          ) : (
            <div className="evidence-empty">No image was retained for this event.<small>Metadata and nearby camera detections remain available below.</small></div>
          )}
          <div className="evidence-stamp">
            {mode === "live"
              ? "LIVE · not recorded"
              : imageSize && Math.max(...imageSize) < 320
                ? `DETECTION CROP · LOW RESOLUTION · ${imageSize[0]}×${imageSize[1]}`
                : "EVENT CONTEXT FRAME"}
          </div>
        </div>
        <div className="evidence-timeline">
          <div className="timeline-axis" />
          {!evidence && <div className="hint">Loading nearby detections…</div>}
          {evidence?.timeline.length === 0 && <div className="hint">No nearby detections in this camera window.</div>}
          {evidence?.timeline.map((event) => {
            const thumb = snapshotUrl(event.snapshot);
            return (
              <button
                key={event.id}
                className={"evidence-event" + (event.is_alert_detection ? " alert-event" : "")}
                onClick={() => { if (event.snapshot) { setImageSize(null); setSelectedSnapshot(event.snapshot); setMode("evidence"); } }}
              >
                <span className="timeline-dot" />
                <span className="timeline-time">{new Date(event.ts).toLocaleTimeString([], { hour12: false })}</span>
                {thumb ? <img src={thumb} alt="" /> : <span className="timeline-placeholder">{event.vehicle_type?.[0] || "·"}</span>}
                <strong>{event.plate || `${event.color || ""} ${event.vehicle_type || "object"}`.trim()}</strong>
                <small>
                  Track {event.track_id ?? "legacy"} · {event.track_hits} observations
                  {event.direction ? ` · ${event.direction}` : ""}
                </small>
                {event.is_alert_detection && <small>Alert match</small>}
              </button>
            );
          })}
        </div>
        <div className="evidence-foot">
          Video remains at the source VMS. This view shows retained event evidence and the current federated stream.
        </div>
      </div>
    </div>
  );
}

export default function AlertsView() {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [watch, setWatch] = useState<WatchItem[]>([]);
  const [vtype, setVtype] = useState("");
  const [color, setColor] = useState("");
  const [reason, setReason] = useState("");
  const [selectedAlert, setSelectedAlert] = useState<Alert | null>(null);
  const groupedAlerts = useMemo(() => groupAlerts(alerts), [alerts]);

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
          {groupedAlerts.length === 0 && (
            <div className="hint" style={{ padding: 12 }}>
              No alerts yet. When a detection matches the watchlist, a real-time
              alert appears here.
            </div>
          )}
          {groupedAlerts.map((a) => {
            const snap = snapshotUrl(a.snapshot);
            return (
              <div
                key={a.id}
                className={"alert-row" + (a.acknowledged ? " acked" : "")}
                style={{ borderLeftColor: SEV[a.severity] }}
                onClick={() => setSelectedAlert(a)}
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
                    {a.match_confidence != null && ` · ${(a.match_confidence * 100).toFixed(0)}% match`}
                  </div>
                  <div className="alert-time">
                    {new Date(a.ts).toLocaleTimeString([], { hour12: false })}
                    {a.occurrence_count > 1 && (
                      <span className="occurrence-count">{a.occurrence_count} occurrences</span>
                    )}
                  </div>
                </div>
                {!a.acknowledged ? (
                  <button className="ack-btn" onClick={(e) => { e.stopPropagation(); ack(a.id); }}>
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
      <AlertMap alerts={groupedAlerts} />
      {selectedAlert && <EvidenceViewer alert={selectedAlert} onClose={() => setSelectedAlert(null)} />}
    </div>
  );
}
