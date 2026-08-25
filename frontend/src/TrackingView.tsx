import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import {
  fetchTrack,
  fetchTrackVehicle,
  exportDetectionReport,
  snapshotUrl,
  type PathStop,
  type TrackResult,
  type SingleVehicleResult,
} from "./api";
import { districtColor } from "./theme";

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
    {
      id: "osm",
      type: "raster",
      source: "osm",
      paint: { "raster-opacity": 0.5, "raster-saturation": -0.6 },
    },
  ],
};

const COLORS = [
  "white",
  "black",
  "silver/grey",
  "red",
  "orange",
  "yellow",
  "green",
  "blue",
];
const TYPES = ["car", "motorcycle", "bus", "truck"];

function timeOf(ts: string): string {
  return new Date(ts).toLocaleString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    day: "2-digit",
    month: "short",
  });
}

function RouteMap({ pts }: { pts: PathStop[] }) {
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
      const line = {
        type: "FeatureCollection",
        features: [
          {
            type: "Feature",
            geometry: {
              type: "LineString",
              coordinates: pts.map((r) => [r.lng, r.lat]),
            },
            properties: {},
          },
        ],
      } as any;
      if (m.getSource("route")) {
        (m.getSource("route") as any).setData(line);
      } else {
        m.addSource("route", { type: "geojson", data: line });
        m.addLayer({
          id: "route-line",
          type: "line",
          source: "route",
          paint: {
            "line-color": "#3b82f6",
            "line-width": 3,
            "line-dasharray": [2, 1],
          },
        });
      }
      pts.forEach((r, i) => {
        const el = document.createElement("div");
        el.className = "route-marker";
        el.style.background = districtColor(r.city);
        el.textContent = String(i + 1);
        const mk = new maplibregl.Marker({ element: el })
          .setLngLat([r.lng, r.lat])
          .setPopup(
            new maplibregl.Popup({ offset: 16, closeButton: false }).setHTML(
              `<b>${i + 1}. ${r.camera_name}</b>
               <div class="popup-row"><span>${r.city}</span> ${r.count} sighting(s)</div>
               <div class="popup-row"><span>${timeOf(r.first_seen)}</span> → ${timeOf(
                r.last_seen
              )}</div>`
            )
          )
          .addTo(m);
        markers.current.push(mk);
      });
      if (pts.length) {
        const b = new maplibregl.LngLatBounds();
        pts.forEach((r) => b.extend([r.lng, r.lat]));
        m.fitBounds(b, { padding: 60, maxZoom: 12, duration: 500 });
      }
    };
    if (m.isStyleLoaded()) draw();
    else m.once("load", draw);
  }, [pts]);

  return <div className="track-map" ref={container} />;
}

export default function TrackingView() {
  const [plate, setPlate] = useState("");
  const [vtype, setVtype] = useState("");
  const [color, setColor] = useState("");
  const [single, setSingle] = useState(true);
  const [result, setResult] = useState<TrackResult | null>(null);
  const [sv, setSv] = useState<SingleVehicleResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [note, setNote] = useState("");

  const run = async () => {
    setNote("");
    setLoading(true);
    try {
      if (plate.trim()) {
        setSv(null);
        setResult(await fetchTrack({ plate: plate.trim() }));
      } else if (single) {
        if (!vtype || !color) {
          setNote("Single-vehicle mode needs both a vehicle type and a colour.");
          setLoading(false);
          return;
        }
        setResult(null);
        setSv(await fetchTrackVehicle(vtype, color));
      } else {
        const params: Record<string, string> = {};
        if (vtype) params.vehicle_type = vtype;
        if (color) params.color = color;
        if (!Object.keys(params).length) {
          setLoading(false);
          return;
        }
        setSv(null);
        setResult(await fetchTrack(params));
      }
    } catch {
      setResult(null);
      setSv(null);
    } finally {
      setLoading(false);
    }
  };

  const exportReport = async () => {
    setNote("");
    try {
      const params = sv
        ? { detection_ids: sv.path.map((stop) => stop.id).join(",") }
        : plate.trim()
          ? { plate: plate.trim() }
          : { ...(vtype ? { vehicle_type: vtype } : {}), ...(color ? { color } : {}) };
      await exportDetectionReport(params);
      setNote("Timestamped movement evidence exported as CSV and added to the audit trail.");
    } catch {
      setNote("Movement report export failed.");
    }
  };

  // Unified map points (single-vehicle stops mapped to the PathStop shape).
  const mapPts: PathStop[] = sv
    ? sv.path.map((s) => ({
        camera_id: s.camera_id,
        camera_name: s.camera_name,
        city: s.city,
        lat: s.lat,
        lng: s.lng,
        first_seen: s.ts,
        last_seen: s.ts,
        count: 1,
        snapshot: s.snapshot,
      }))
    : result?.path || [];

  return (
    <div className="track">
      <div className="track-controls">
        <div className="tc-group">
          <label>Plate (ANPR)</label>
          <input
            value={plate}
            onChange={(e) => setPlate(e.target.value)}
            placeholder="e.g. GJ01AB1234"
            onKeyDown={(e) => e.key === "Enter" && run()}
          />
        </div>
        <div className="tc-or">or attributes</div>
        <div className="tc-group">
          <label>Vehicle</label>
          <select
            value={vtype}
            onChange={(e) => setVtype(e.target.value)}
            disabled={!!plate.trim()}
          >
            <option value="">any</option>
            {TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>
        <div className="tc-group">
          <label>Colour</label>
          <select
            value={color}
            onChange={(e) => setColor(e.target.value)}
            disabled={!!plate.trim()}
          >
            <option value="">any</option>
            {COLORS.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>
        <label
          className="single-toggle"
          title="Isolate one vehicle using attribute + spatio-temporal reachability (a vehicle can't appear at a camera before it could physically drive there)."
        >
          <input
            type="checkbox"
            checked={single}
            disabled={!!plate.trim()}
            onChange={(e) => setSingle(e.target.checked)}
          />
          Single-vehicle (space-time)
        </label>
        <button className="track-btn" onClick={run}>
          {loading ? "Tracking…" : "Track"}
        </button>
        {sv && (
          <div className="track-summary">
            <b>{sv.hops}</b>-hop trajectory ·{" "}
            <b>{sv.rejected_infeasible}</b> infeasible rejected ·{" "}
            <span className="mode">single-vehicle</span>
          </div>
        )}
        {result && (
          <div className="track-summary">
            <b>{result.count}</b> detections · <b>{result.cameras}</b> cameras ·{" "}
            <span className="mode">{result.mode} match</span>
          </div>
        )}
        {(sv || result) && (
          <button className="track-export" onClick={exportReport}>
            Export movement report
          </button>
        )}
      </div>

      <div className="track-body">
        <div className="track-timeline">
          {note && (
            <div className="hint" style={{ padding: 12, color: "var(--danger)" }}>
              {note}
            </div>
          )}
          {!sv && !result && !note && (
            <div className="hint" style={{ padding: 12 }}>
              Enter a plate (exact), or pick a vehicle type + colour. With
              <b> Single-vehicle</b> on, one vehicle's most-plausible path is
              reconstructed using spatio-temporal reachability; off gives the
              class-level route (all matching vehicles).
            </div>
          )}
          {sv &&
            sv.path.map((s, i) => {
              const snap = snapshotUrl(s.snapshot);
              return (
                <div className="tl-row" key={s.id}>
                  <div className="tl-idx">{i + 1}</div>
                  <div className="tl-thumb">
                    {snap ? <img src={snap} alt="" /> : <div className="det-noimg">▶</div>}
                  </div>
                  <div className="tl-info">
                    <div className="tl-cam">
                      <span
                        className="tdot"
                        style={{ background: districtColor(s.city) }}
                      />
                      {s.camera_name} · {s.city}
                    </div>
                    <div className="tl-attr">
                      {i === 0
                        ? "start"
                        : `+${s.gap_s}s · ${s.dist_km} km · ${s.speed_kmh} km/h`}
                    </div>
                    <div className="tl-time">{timeOf(s.ts)}</div>
                  </div>
                </div>
              );
            })}
          {result &&
            result.path.map((r, i) => {
              const snap = snapshotUrl(r.snapshot);
              return (
                <div className="tl-row" key={r.camera_id}>
                  <div className="tl-idx">{i + 1}</div>
                  <div className="tl-thumb">
                    {snap ? (
                      <img src={snap} alt="" />
                    ) : (
                      <div className="det-noimg">{r.count}</div>
                    )}
                  </div>
                  <div className="tl-info">
                    <div className="tl-cam">
                      <span
                        className="tdot"
                        style={{ background: districtColor(r.city) }}
                      />
                      {r.camera_name} · {r.city}
                    </div>
                    <div className="tl-attr">{r.count} sighting(s)</div>
                    <div className="tl-time">
                      {timeOf(r.first_seen)} → {timeOf(r.last_seen)}
                    </div>
                  </div>
                </div>
              );
            })}
        </div>
        <RouteMap pts={mapPts} />
      </div>
    </div>
  );
}
