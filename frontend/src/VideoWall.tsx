import { useEffect, useRef, useState } from "react";
import type { Camera } from "./api";
import { cameraSnapshotUrl } from "./api";
import { districtColor } from "./theme";

// Refresh interval for each tile's snapshot. The gateway caches frames for a
// few seconds, so this is mostly served from cache with periodic re-grabs.
const REFRESH_MS = Number(
  (import.meta as any).env?.VITE_WALL_REFRESH_MS || 8000
);

// A snapshot tile: shows a periodically-refreshed still for every camera (any
// codec, incl. H.265) so the whole grid is viewable at once. Click for full
// live video. Frames are double-buffered (preload then swap) to avoid flicker,
// and only on-screen tiles fetch.
function SnapshotTile({
  cam,
  onSelect,
  active,
}: {
  cam: Camera;
  onSelect: (c: Camera) => void;
  active: boolean;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  const [shownSrc, setShownSrc] = useState("");
  const [ready, setReady] = useState(false);
  const [err, setErr] = useState(false);
  const isHevc = ["hevc", "h265"].includes((cam.codec || "").toLowerCase());

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const io = new IntersectionObserver(
      ([e]) => setVisible(e.isIntersecting),
      { rootMargin: "200px", threshold: 0.05 }
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  useEffect(() => {
    if (!visible || !active) return;
    let alive = true;
    const load = () => {
      const url = `${cameraSnapshotUrl(cam)}?t=${Date.now()}`;
      const img = new Image();
      img.onload = () => {
        if (!alive) return;
        setShownSrc(url);
        setReady(true);
        setErr(false);
      };
      img.onerror = () => alive && setErr(true);
      img.src = url;
    };
    const t0 = setTimeout(load, Math.random() * 2000); // stagger initial burst
    const iv = setInterval(load, REFRESH_MS);
    return () => {
      alive = false;
      clearTimeout(t0);
      clearInterval(iv);
    };
  }, [visible, active, cam.camera_id]);

  return (
    <div className="tile" ref={wrap} onClick={() => onSelect(cam)}>
      <div className="tile-video">
        {shownSrc && !err && (
          <img className="tile-snap" src={shownSrc} alt={cam.name} />
        )}
        {err && (
          <div className="tile-ph">
            <div className="ph-num">{cam.camera_id.split("-").pop()}</div>
            <div className="ph-note">snapshot unavailable</div>
          </div>
        )}
        <div className="tile-badges">
          <span className="live-badge">
            <span className="live-dot" /> LIVE
          </span>
          {isHevc && <span className="codec-badge">H.265</span>}
          {cam.analytics_enabled && <span className="anpr-badge">ANPR</span>}
        </div>
        {visible && active && !ready && !err && (
          <div className="tile-loading">loading…</div>
        )}
      </div>
      <div className="tile-meta">
        <span className="tdot" style={{ background: districtColor(cam.city) }} />
        <div className="tile-name">
          <b>{cam.name}</b>
          <small>{cam.site}</small>
        </div>
      </div>
    </div>
  );
}

export default function VideoWall({
  cameras,
  onSelect,
  active = true,
}: {
  cameras: Camera[];
  onSelect: (c: Camera) => void;
  active?: boolean;
}) {
  return (
    <div className="wall">
      <div className="wall-bar">
        <span>{cameras.length} cameras · live snapshots (all feeds)</span>
        <span className="dim">
          refreshes every few seconds · click a tile for full live video
        </span>
      </div>
      <div className="wall-grid">
        {cameras.map((c) => (
          <SnapshotTile
            key={c.camera_id}
            cam={c}
            onSelect={onSelect}
            active={active}
          />
        ))}
      </div>
    </div>
  );
}
