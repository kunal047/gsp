import { useEffect, useState } from "react";
import {
  fetchDetections,
  fetchDetectionStats,
  snapshotUrl,
  type Detection,
  type DetStats,
} from "./api";
import { districtColor } from "./theme";

function timeOf(ts: string | null): string {
  if (!ts) return "";
  const d = new Date(ts);
  return d.toLocaleTimeString([], { hour12: false });
}

export default function DetectionsPanel() {
  const [dets, setDets] = useState<Detection[]>([]);
  const [stats, setStats] = useState<DetStats | null>(null);

  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const [d, s] = await Promise.all([
          fetchDetections({ limit: "40" }),
          fetchDetectionStats(),
        ]);
        if (alive) {
          setDets(d);
          setStats(s);
        }
      } catch {
        /* ignore transient */
      }
    };
    poll();
    const t = setInterval(poll, 2000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  return (
    <aside className="detpanel">
      <div className="detpanel-head">
        <div className="section-title" style={{ margin: 0 }}>
          Live detections
        </div>
        <div className="det-stats">
          <div>
            <b>{stats?.total ?? 0}</b>
            <small>events</small>
          </div>
          <div>
            <b>{stats?.anpr ?? 0}</b>
            <small>ANPR</small>
          </div>
          <div>
            <b>{stats?.unique_plates ?? 0}</b>
            <small>plates</small>
          </div>
          <div>
            <b>{stats?.active_cameras ?? 0}</b>
            <small>cams</small>
          </div>
        </div>
      </div>
      <div className="det-list">
        {dets.length === 0 && (
          <div className="hint" style={{ padding: 12 }}>
            Waiting for detections… the analytics worker (YOLOv8 + EasyOCR) is
            scanning live feeds.
          </div>
        )}
        {dets.map((d) => {
          const snap = snapshotUrl(d.snapshot);
          const isAnpr = d.event_type === "anpr" && d.plate;
          return (
            <div
              key={d.id}
              className={"det-row" + (isAnpr ? " anpr" : "")}
            >
              <div className="det-thumb">
                {snap ? (
                  <img src={snap} alt="detection" />
                ) : (
                  <div className="det-noimg">{d.vehicle_type?.[0] || "?"}</div>
                )}
              </div>
              <div className="det-info">
                {isAnpr ? (
                  <div className="det-plate">{d.plate}</div>
                ) : (
                  <div className="det-vtype">{d.vehicle_type || "object"}</div>
                )}
                <div className="det-cam">
                  <span
                    className="tdot"
                    style={{ background: districtColor(d.city) }}
                  />
                  {d.camera_name} · {d.city}
                </div>
              </div>
              <div className="det-time">{timeOf(d.ts)}</div>
            </div>
          );
        })}
      </div>
    </aside>
  );
}
