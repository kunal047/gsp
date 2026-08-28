import { useEffect, useMemo, useState } from "react";
import MapView from "./MapView";
import VideoWall from "./VideoWall";
import CameraModal from "./CameraModal";
import DetectionsPanel from "./DetectionsPanel";
import TrackingView from "./TrackingView";
import AlertsView from "./AlertsView";
import OpsView from "./OpsView";
import WatchlistView from "./WatchlistView";
import RegistryView from "./RegistryView";
import {
  fetchCameras,
  fetchStats,
  fetchAlertStats,
  fetchDetectionStats,
  fetchHealth,
  retryIngest,
  getSession,
  isAuthenticated,
  logout,
  type Camera,
  type Stats,
  type Health,
  type DetStats,
} from "./api";
import Login from "./Login";
import { STATUS_COLORS, districtColor } from "./theme";

const ROLE_LABELS: Record<string, string> = {
  state_admin: "State Admin",
  district_officer: "District Officer",
  viewer: "Viewer (read-only)",
};

export default function App() {
  const [theme, setTheme] = useState<"dark" | "light">(() => {
    const saved = localStorage.getItem("netra-theme");
    if (saved === "dark" || saved === "light") return saved;
    return window.matchMedia("(prefers-color-scheme: light)").matches
      ? "light"
      : "dark";
  });
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [detStats, setDetStats] = useState<DetStats | null>(null);
  const [cityFilter, setCityFilter] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<
    "map" | "registry" | "wall" | "track" | "watchlist" | "alerts" | "ops"
  >("map");
  const [selected, setSelected] = useState<Camera | null>(null);
  const [alertCount, setAlertCount] = useState(0);
  const [health, setHealth] = useState<Health | null>(null);
  const [authed, setAuthed] = useState(isAuthenticated());
  const [rev, setRev] = useState(0);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    localStorage.setItem("netra-theme", theme);
  }, [theme]);

  // A rejected/expired token anywhere in the app drops back to the login screen.
  useEffect(() => {
    const onUnauth = () => setAuthed(false);
    window.addEventListener("netra-unauthorized", onUnauth);
    return () => window.removeEventListener("netra-unauthorized", onUnauth);
  }, []);

  const signOut = () => {
    logout();
    setAuthed(false);
  };

  useEffect(() => {
    if (!authed) return;
    const poll = () => {
      fetchAlertStats()
        .then((s) => setAlertCount(s.unacknowledged))
        .catch(() => {});
      fetchHealth().then(setHealth).catch(() => {});
      fetchDetectionStats().then(setDetStats).catch(() => {});
    };
    poll();
    const t = setInterval(poll, 3000);
    return () => clearInterval(t);
  }, [authed]);

  const retry = async () => {
    try {
      setHealth(await retryIngest());
      const s = await fetchStats();
      setStats(s);
    } catch {
      /* ignore */
    }
  };

  useEffect(() => {
    if (!authed) return;
    fetchStats().then(setStats).catch((e) => setError(String(e)));
  }, [rev, authed]);

  useEffect(() => {
    if (!authed) return;
    const params: Record<string, string> = {};
    if (cityFilter) params.city = cityFilter;
    if (statusFilter) params.health_status = statusFilter;
    fetchCameras(params)
      .then(setCameras)
      .catch((e) => setError(String(e)));
  }, [cityFilter, statusFilter, rev, authed]);

  const cities = useMemo(
    () =>
      Object.entries(stats?.by_city || {}).sort((a, b) => b[1] - a[1]),
    [stats]
  );
  const source = cameras[0]?.source;
  const anyApprox = cameras.some((c) => c.coords_approx);

  if (!authed) {
    return <Login onLogin={() => { setAuthed(true); setRev((r) => r + 1); }} />;
  }

  const session = getSession();

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span>NETRA</span>
          <small>Unified CCTV Integration & Intelligence · Gujarat</small>
        </div>
        <div className="live-pill">
          <span className="live-dot" /> LIVE DATA
          {source ? ` · ${source}` : ""}
        </div>
        <div className="tabs">
          <button
            className={view === "map" ? "active" : ""}
            onClick={() => setView("map")}
          >
            Map
          </button>
          <button
            className={view === "registry" ? "active" : ""}
            onClick={() => setView("registry")}
          >
            Registry
          </button>
          <button
            className={view === "wall" ? "active" : ""}
            onClick={() => setView("wall")}
          >
            Video Wall
          </button>
          <button
            className={view === "track" ? "active" : ""}
            onClick={() => setView("track")}
          >
            Tracking
          </button>
          <button
            className={view === "watchlist" ? "active" : ""}
            onClick={() => setView("watchlist")}
          >
            Watchlist
          </button>
          <button
            className={
              (view === "alerts" ? "active" : "") +
              (alertCount ? " has-alerts" : "")
            }
            onClick={() => setView("alerts")}
          >
            Alerts
            {alertCount > 0 && <span className="alert-badge">{alertCount}</span>}
          </button>
          <button
            className={view === "ops" ? "active" : ""}
            onClick={() => setView("ops")}
          >
            Ops
          </button>
        </div>
        <div className="spacer" />
        <div className="user-chip" title="Signed-in identity (verified token)">
          <span className="user-name">{session?.full_name || session?.user}</span>
          <span className="user-role">
            {ROLE_LABELS[session?.role || "viewer"] || session?.role}
            {session?.scope ? ` · ${session.scope}` : ""}
          </span>
          <button className="signout" onClick={signOut} title="Sign out">
            Sign out
          </button>
        </div>
        <button
          className="theme-toggle"
          onClick={() =>
            setTheme((value) => (value === "dark" ? "light" : "dark"))
          }
          aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} appearance`}
          title="Appearance"
        >
          <span className="theme-symbol" aria-hidden="true">
            {theme === "dark" ? "◐" : "◑"}
          </span>
          {theme === "dark" ? "Light" : "Dark"}
        </button>
        <div className="kpis">
          <div className="kpi">
            <b>{stats?.total ?? "-"}</b>
            <small>Cameras</small>
          </div>
          <div className="kpi">
            <b>{cities.length || "-"}</b>
            <small>Districts</small>
          </div>
          <div className="kpi" title="Cameras the provider reports as live">
            <b>{stats?.by_status?.online ?? "-"}</b>
            <small>Online</small>
          </div>
          <div
            className="kpi"
            title="Cameras currently processed by the analytics worker"
          >
            <b>{detStats?.active_cameras ?? "-"}</b>
            <small>Analysed</small>
          </div>
          <div
            className="kpi"
            title="Distinct plates confirmed by multi-frame consensus"
          >
            <b>{detStats?.unique_plates ?? "-"}</b>
            <small>Plates</small>
          </div>
        </div>
      </header>

      {health && health.ingest_error && (
        <div className="ingest-banner">
          ⚠ Live camera feed unavailable - {health.ingest_error}. No synthetic
          data is shown.
          <button onClick={retry}>Retry onboarding</button>
        </div>
      )}

      <div className="main">
        <aside className="sidebar">
          <div className="section-title">Districts</div>
          <div
            className={"filter-row" + (cityFilter === null ? " active" : "")}
            onClick={() => setCityFilter(null)}
          >
            <div className="left">
              <span className="dot" style={{ background: "#64748b" }} />
              All districts
            </div>
            <span className="count">{stats?.total ?? ""}</span>
          </div>
          {cities.map(([c, n]) => (
            <div
              key={c}
              className={"filter-row" + (cityFilter === c ? " active" : "")}
              onClick={() => setCityFilter(cityFilter === c ? null : c)}
            >
              <div className="left">
                <span className="dot" style={{ background: districtColor(c) }} />
                {c}
              </div>
              <span className="count">{n}</span>
            </div>
          ))}

          <div className="section-title">Feed status</div>
          {["online", "degraded", "offline"].map((s) => (
            <div
              key={s}
              className={"filter-row" + (statusFilter === s ? " active" : "")}
              onClick={() => setStatusFilter(statusFilter === s ? null : s)}
            >
              <div className="left">
                <span className="dot" style={{ background: STATUS_COLORS[s] }} />
                {s[0].toUpperCase() + s.slice(1)}
              </div>
              <span className="count">{stats?.by_status?.[s] ?? 0}</span>
            </div>
          ))}

          <div className="section-title">Category (inferred)</div>
          {Object.entries(stats?.by_department || {}).map(([t, n]) => (
            <div key={t} className="filter-row">
              <div className="left">{t}</div>
              <span className="count">{n}</span>
            </div>
          ))}

          {error && (
            <div className="hint" style={{ color: "var(--danger)" }}>
              {error}
            </div>
          )}
        </aside>

        {view === "map" ? (
          <div className="map-wrap">
            <MapView cameras={cameras} />
            <div className="legend">
              <div className="row" style={{ fontWeight: 600 }}>
                <span className="live-dot" /> Live government feed
              </div>
              <div className="prov">
                {(stats?.by_source_system?.["Gujarat CSITMS"] ?? "-")} live CSITMS cameras · {stats?.total ?? "-"} registry assets
              </div>
              {anyApprox && (
                <div className="prov">
                  ⚠ Pin locations are approximate (geocoded from location text;
                  the source API provides no coordinates).
                </div>
              )}
            </div>
          </div>
        ) : view === "wall" ? (
          <VideoWall
            cameras={cameras}
            onSelect={setSelected}
            active={!selected}
          />
        ) : view === "track" ? (
          <TrackingView />
        ) : view === "registry" ? (
          <RegistryView key={rev} onChanged={() => setRev((r) => r + 1)} />
        ) : view === "alerts" ? (
          <AlertsView />
        ) : view === "watchlist" ? (
          <WatchlistView key={rev} />
        ) : (
          <OpsView />
        )}

        <DetectionsPanel onOpenAlerts={() => setView("alerts")} />
      </div>

      {selected && (
        <CameraModal cam={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}
