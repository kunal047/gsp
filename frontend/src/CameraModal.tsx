import { useState } from "react";
import type { Camera } from "./api";
import { cameraSnapshotUrl, streamSrc } from "./api";

export default function CameraModal({
  cam,
  onClose,
}: {
  cam: Camera;
  onClose: () => void;
}) {
  const [ready, setReady] = useState(false);
  const [err, setErr] = useState(false);

  const providerId = cam.camera_id.split("-").pop();
  const providerBase = (cam.source || "").replace(/\/$/, "");
  const providerPlayer = providerBase.includes("corp8.cloud")
    ? `${providerBase}/camera/${providerId}`
    : null;
  const isHevc = ["hevc", "h265"].includes((cam.codec || "").toLowerCase());

  const rows: [string, string][] = [
    ["Camera ID", cam.camera_id],
    ["Location", cam.site],
    ["District", cam.city + (cam.coords_approx ? " (approx)" : "")],
    ["Category", cam.department + (cam.dept_inferred ? " (inferred)" : "")],
    ["Codec", (cam.codec || "unknown") + (isHevc ? " (H.265)" : "")],
    ["Delivery", cam.delivery || "?"],
    ["Protocol", cam.protocol || "?"],
    ["VMS", cam.vms_platform || "-"],
    ["Stream", cam.stream_url],
    ["Source", cam.source || "-"],
  ];

  let player;
  if (isHevc) {
    // No browser decodes H.265; show the live server-side snapshot instead.
    player = (
      <div className="modal-hevc">
        <img
          src={`${cameraSnapshotUrl(cam)}?t=${Date.now()}`}
          alt={cam.name}
          onError={() => setErr(true)}
        />
        <div className="modal-hevc-note">
          H.265 feed - live snapshot shown (browsers can’t decode H.265).
          Full video is available over RTSP/WebRTC; analytics runs on this feed.
        </div>
      </div>
    );
  } else if (providerPlayer && !err) {
    player = (
      <>
        <iframe
          title={`${cam.name} live`}
          src={providerPlayer}
          allow="autoplay; fullscreen"
          onLoad={() => setReady(true)}
          onError={() => setErr(true)}
        />
        {!ready && <div className="modal-loading">connecting…</div>}
      </>
    );
  } else if (!err) {
    player = (
      <>
        <video
          key={cam.camera_id}
          src={streamSrc(cam)}
          autoPlay
          muted
          loop
          controls
          playsInline
          onCanPlay={() => setReady(true)}
          onError={() => setErr(true)}
        />
        {!ready && <div className="modal-loading">connecting…</div>}
      </>
    );
  } else {
    player = (
      <div className="tile-ph big">
        Live preview unavailable in-browser - analytics still runs on this feed.
      </div>
    );
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div>
            <b>{cam.name}</b> <span className="dim">· {cam.site}</span>
          </div>
          <button onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">
          <div className="modal-video">{player}</div>
          <div className="modal-meta">
            {rows.map(([k, v]) => (
              <div className="mrow" key={k}>
                <span>{k}</span>
                <div>{v}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
