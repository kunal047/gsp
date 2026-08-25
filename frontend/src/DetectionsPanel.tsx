import { useEffect, useMemo, useState } from "react";
import {
  fetchAlerts,
  fetchAlertStats,
  fetchDetections,
  fetchDetectionStats,
  groupAlerts,
  snapshotUrl,
  type Alert,
  type Detection,
  type DetStats,
} from "./api";
import { districtColor } from "./theme";

const ACTIVITY_LABELS: Record<string, string> = {
  watchlist: "Watchlist match",
  congestion: "Congestion",
  surge: "Traffic surge",
  feed_offline: "Feed offline",
};
const ACTIVITY_MARKS: Record<string, string> = {
  watchlist: "WL",
  congestion: "CG",
  surge: "TS",
  feed_offline: "FD",
};

function timeOf(ts: string | null): string {
  return ts ? new Date(ts).toLocaleTimeString([], { hour12: false }) : "";
}

export default function DetectionsPanel({ onOpenAlerts }: { onOpenAlerts: () => void }) {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [dets, setDets] = useState<Detection[]>([]);
  const [stats, setStats] = useState<DetStats | null>(null);
  const [unacknowledged, setUnacknowledged] = useState(0);
  const [mode, setMode] = useState<"priority" | "diagnostics">("priority");

  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const [nextAlerts, nextAlertStats, nextStats] = await Promise.all([
          fetchAlerts({ limit: "50" }),
          fetchAlertStats(),
          fetchDetectionStats(),
        ]);
        if (alive) {
          setAlerts(nextAlerts);
          setUnacknowledged(nextAlertStats.unacknowledged);
          setStats(nextStats);
        }
      } catch {
        /* retain the last useful operational state during a transient failure */
      }
    };
    poll();
    const timer = setInterval(poll, 2500);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    if (mode !== "diagnostics") return;
    let alive = true;
    const poll = () => fetchDetections({ limit: "40" })
      .then((next) => { if (alive) setDets(next); })
      .catch(() => {});
    poll();
    const timer = setInterval(poll, 2000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [mode]);

  const summary = useMemo(() => ({
    actionable: unacknowledged,
    watchlist: alerts.filter((alert) => alert.kind === "watchlist" && !alert.acknowledged).length,
    outages: alerts.filter((alert) => alert.kind === "feed_offline" && !alert.acknowledged).length,
  }), [alerts, unacknowledged]);
  const priorityAlerts = useMemo(
    () => groupAlerts(alerts.filter((alert) => !alert.acknowledged)).slice(0, 30),
    [alerts]
  );

  return (
    <aside className="detpanel">
      <div className="activity-head">
        <div className="activity-heading">
          <span>Operational activity</span>
          <small>{stats?.active_cameras ?? 0} cameras under analytics</small>
        </div>
        <div className="activity-tabs" aria-label="Activity display mode">
          <button className={mode === "priority" ? "active" : ""} onClick={() => setMode("priority")}>Priority</button>
          <button className={mode === "diagnostics" ? "active" : ""} onClick={() => setMode("diagnostics")}>Diagnostics</button>
        </div>
      </div>

      {mode === "priority" ? (
        <>
          <div className="activity-summary">
            <div><b>{summary.actionable}</b><span>Needs review</span></div>
            <div><b>{summary.watchlist}</b><span>Watchlist</span></div>
            <div><b>{summary.outages}</b><span>Feed issues</span></div>
          </div>
          <div className="activity-list">
            {priorityAlerts.length === 0 && (
              <div className="activity-empty"><strong>No operational events</strong><span>Watchlist matches, traffic anomalies, and camera issues will appear here.</span></div>
            )}
            {priorityAlerts.map((alert) => {
              const snap = snapshotUrl(alert.snapshot);
              return (
                <button className={"activity-row activity-" + alert.kind} key={alert.id} onClick={onOpenAlerts}>
                  <span className="activity-visual">
                    {snap ? <img src={snap} alt="" /> : <span>{ACTIVITY_MARKS[alert.kind] || "AL"}</span>}
                  </span>
                  <span className="activity-copy">
                    <span className="activity-kind">{ACTIVITY_LABELS[alert.kind] || alert.kind}</span>
                    <strong>{alert.reason}</strong>
                    <small><i style={{ background: districtColor(alert.city) }} />{alert.camera_name} · {alert.city}</small>
                    {alert.occurrence_count > 1 && <em>{alert.occurrence_count} occurrences grouped</em>}
                  </span>
                  <span className="activity-time">{timeOf(alert.ts)}</span>
                </button>
              );
            })}
          </div>
          <button className="activity-all" onClick={onOpenAlerts}>Open alerts workspace →</button>
        </>
      ) : (
        <>
          <div className="diagnostic-note">
            <strong>Analytics telemetry</strong>
            <span>{stats?.total ?? 0} completed tracks · {stats?.anpr ?? 0} ANPR · {stats?.unique_plates ?? 0} unique plates</span>
          </div>
          <div className="det-list">
            {dets.length === 0 && <div className="activity-empty"><strong>Waiting for detections</strong><span>The analytics worker is scanning active feeds.</span></div>}
            {dets.map((detection) => {
              const snap = snapshotUrl(detection.snapshot);
              const isAnpr = detection.event_type === "anpr" && detection.plate;
              return (
                <div key={detection.id} className={"det-row" + (isAnpr ? " anpr" : "")}>
                  <div className="det-thumb">{snap && <img src={snap} alt="Tracked vehicle crop" />}</div>
                  <div className="det-info">
                    {isAnpr ? <div className="det-plate">{detection.plate}</div> : <div className="det-vtype">{detection.vehicle_type || "object"}</div>}
                    <div className="det-cam"><span className="tdot" style={{ background: districtColor(detection.city) }} />{detection.camera_name} · {detection.city}</div>
                    <div className="det-cam">
                      Track {detection.track_id ?? "legacy"} · {detection.track_hits} observations
                      {detection.direction ? ` · ${detection.direction}` : ""}
                      {detection.stopped ? " · stopped" : ""}
                    </div>
                  </div>
                  <div className="det-time" title={`Time source: ${detection.time_source}`}>
                    {timeOf(detection.ts)}
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}
    </aside>
  );
}
