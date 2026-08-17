import { useEffect, useRef, useState } from "react";
import type { Camera } from "./api";
import { streamSrc } from "./api";
import { districtColor } from "./theme";

// Lazy-play: only tiles scrolled into view attach a stream; off-screen tiles
// release the connection. Keeps concurrent streams within the browser's
// ~6-per-host limit even with all 31 cameras rendered at once.
function VideoTile({
  cam,
  onSelect,
  active,
}: {
  cam: Camera;
  onSelect: (c: Camera) => void;
  active: boolean;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const video = useRef<HTMLVideoElement>(null);
  const [visible, setVisible] = useState(false);
  const [err, setErr] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const io = new IntersectionObserver(
      ([e]) => setVisible(e.isIntersecting),
      { rootMargin: "150px", threshold: 0.1 }
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  useEffect(() => {
    const v = video.current;
    if (!v) return;
    if (visible && active && !err) {
      v.src = streamSrc(cam);
      v.play().catch(() => {});
    } else {
      v.pause();
      v.removeAttribute("src");
      v.load();
      setReady(false);
    }
  }, [visible, active, err]);

  return (
    <div className="tile" ref={wrap} onClick={() => onSelect(cam)}>
      <div className="tile-video">
        <video
          ref={video}
          muted
          loop
          playsInline
          preload="none"
          onCanPlay={() => setReady(true)}
          onError={() => setErr(true)}
          style={{ display: err ? "none" : "block" }}
        />
        {err && (
          <div className="tile-ph">
            <div className="ph-num">{cam.camera_id.split("-").pop()}</div>
            <div className="ph-note">stream unavailable</div>
          </div>
        )}
        <div className="tile-badges">
          <span className="live-badge">
            <span className="live-dot" /> LIVE
          </span>
          {cam.analytics_enabled && <span className="anpr-badge">ANPR</span>}
        </div>
        {visible && active && !err && !ready && (
          <div className="tile-loading">connecting…</div>
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
        <span>{cameras.length} live feeds · scroll to view all</span>
        <span className="dim">
          on-screen tiles stream · off-screen paused
        </span>
      </div>
      <div className="wall-grid">
        {cameras.map((c) => (
          <VideoTile
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
