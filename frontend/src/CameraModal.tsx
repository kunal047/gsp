import { useState } from "react";
import type { Camera } from "./api";
import { streamSrc } from "./api";

export default function CameraModal({
  cam,
  onClose,
}: {
  cam: Camera;
  onClose: () => void;
}) {
  const [ready, setReady] = useState(false);
  const [err, setErr] = useState(false);
  const rows: [string, string][] = [
    ["Camera ID", cam.camera_id],
    ["Location", cam.site],
    ["District", cam.city + (cam.coords_approx ? " (approx)" : "")],
    ["Category", cam.department + (cam.dept_inferred ? " (inferred)" : "")],
    ["Codec / Container", `${cam.codec || "?"} / ${cam.container || "?"}`],
    ["Delivery", cam.delivery || "?"],
    ["Protocol", cam.protocol || "?"],
    ["VMS", cam.vms_platform || "—"],
    ["Stream", cam.stream_url],
    ["Source", cam.source || "—"],
  ];

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
          <div className="modal-video">
            {err ? (
              <div className="tile-ph big">
                Stream unavailable — source returned an error for this feed.
              </div>
            ) : (
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
            )}
          </div>
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
