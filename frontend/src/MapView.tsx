import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import type { Camera } from "./api";
import { districtColor } from "./theme";

const OSM_STYLE: any = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution: "© OpenStreetMap contributors",
    },
  },
  layers: [
    { id: "bg", type: "background", paint: { "background-color": "#0b0f1a" } },
    {
      id: "osm",
      type: "raster",
      source: "osm",
      paint: { "raster-opacity": 0.55, "raster-saturation": -0.6 },
    },
  ],
};

function popupHtml(c: Camera): string {
  const statusColor =
    c.health_status === "online"
      ? "#22c55e"
      : c.health_status === "degraded"
      ? "#f59e0b"
      : "#6b7280";
  return `
    <b>${c.name} - ${c.site || ""}</b>
    <div class="popup-row"><span>ID</span> ${c.camera_id}</div>
    <div class="popup-row"><span>District</span> ${c.city}${
    c.coords_approx ? " (approx)" : ""
  }</div>
    <div class="popup-row"><span>Category</span> ${c.department}${
    c.dept_inferred ? " (inferred)" : ""
  }</div>
    <div class="popup-row"><span>Feed</span> ${c.codec || "?"} · ${
    c.container || "?"
  } · ${c.delivery || "?"}</div>
    <div class="popup-row"><span>Protocol</span> ${c.protocol || "?"}</div>
    <div class="popup-row"><span>Stream</span> ${
      c.stream_url ? c.stream_url.replace(/^https?:\/\//, "") : "-"
    }</div>
    <div class="popup-row"><span>Status</span>
      <span class="badge" style="background:${statusColor}22;color:${statusColor}">
        ${c.health_status}${c.analytics_enabled ? " · ANPR" : ""}
      </span>
    </div>`;
}

export default function MapView({ cameras }: { cameras: Camera[] }) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const markers = useRef<maplibregl.Marker[]>([]);

  useEffect(() => {
    if (map.current || !container.current) return;
    map.current = new maplibregl.Map({
      container: container.current,
      style: OSM_STYLE,
      center: [72.0, 22.6], // Gujarat
      zoom: 6.4,
      attributionControl: false,
    });
    map.current.addControl(new maplibregl.NavigationControl(), "top-right");
  }, []);

  useEffect(() => {
    if (!map.current) return;
    markers.current.forEach((m) => m.remove());
    markers.current = [];
    cameras.forEach((c) => {
      if (c.lat == null || c.lng == null) return;
      const el = document.createElement("div");
      el.className =
        "cam-marker" +
        (c.health_status === "online" && c.analytics_enabled ? " pulse" : "");
      el.style.background = districtColor(c.city);
      if (c.health_status === "offline") el.style.opacity = "0.45";
      const marker = new maplibregl.Marker({ element: el })
        .setLngLat([c.lng, c.lat])
        .setPopup(
          new maplibregl.Popup({ offset: 14, closeButton: false }).setHTML(
            popupHtml(c)
          )
        )
        .addTo(map.current!);
      markers.current.push(marker);
    });
  }, [cameras]);

  return <div id="map" ref={container} />;
}
