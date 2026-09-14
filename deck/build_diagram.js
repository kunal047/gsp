// Netra - standalone architecture & data-flow diagram (one landscape page).
// Mirrors the deck palette. No em dashes in any content.
const PptxGenJS = require("pptxgenjs");
const p = new PptxGenJS();
p.layout = "LAYOUT_WIDE"; // 13.33 x 7.5
const W = 13.33, H = 7.5, M = 0.5;

const INK = "0E1A2B", INK2 = "16273F", PAPER = "FFFFFF", MIST = "F3F6FB";
const STEEL = "2B4C7E", AMBER = "F59E0B", TEAL = "0E9AA0";
const TXT = "16273F", BODY = "3A4A61", MUTED = "7A8AA3", LINE = "DCE3EE";
const HF = "Cambria", BF = "Calibri";
const shadow = () => ({ type: "outer", color: "0E1A2B", blur: 9, offset: 3, angle: 90, opacity: 0.16 });

function card(s, x, y, w, h, fill) {
  s.addShape(p.ShapeType.roundRect, { x, y, w, h, rectRadius: 0.09, fill: { color: fill }, line: { color: fill }, shadow: shadow() });
}
function box(s, x, y, w, h, fill, tcol, head, lines, headColor) {
  card(s, x, y, w, h, fill);
  s.addText(head, { isTextBox: true, x: x + 0.18, y: y + 0.13, w: w - 0.36, h: 0.38, margin: 0, fontFace: HF, fontSize: 13, bold: true, color: headColor || tcol });
  if (lines && lines.length) s.addText(
    lines.map((t) => ({ text: t, options: { bullet: false, breakLine: true } })),
    { isTextBox: true, x: x + 0.18, y: y + 0.55, w: w - 0.34, h: h - 0.66, margin: 0, fontFace: BF, fontSize: 10, color: tcol, lineSpacingMultiple: 1.12 });
}
function arrowR(s, x, y, w) {
  s.addText("→", { isTextBox: true, x, y: y - 0.3, w: w || 0.44, h: 0.6, margin: 0, align: "center", valign: "middle", fontFace: BF, fontSize: 19, bold: true, color: AMBER });
}
function arrowD(s, x, y, label) {
  s.addText("↓", { isTextBox: true, x, y, w: 0.5, h: 0.42, margin: 0, align: "center", fontFace: BF, fontSize: 18, bold: true, color: AMBER });
  if (label) s.addText(label, { isTextBox: true, x: x + 0.45, y: y - 0.02, w: 3.2, h: 0.4, margin: 0, valign: "middle", fontFace: BF, italic: true, fontSize: 9.5, color: MUTED });
}

const s = p.addSlide();
s.background = { color: PAPER };

// ---- header ----
s.addText("NETRA · SYSTEM ARCHITECTURE & DATA FLOW", { isTextBox: true, x: M, y: 0.35, w: 11, h: 0.3, margin: 0, fontFace: BF, fontSize: 12, bold: true, color: AMBER, charSpacing: 3 });
s.addText("Adapters normalise every source into one registry; a CV worker turns live feeds into evidence-backed events and alerts.",
  { isTextBox: true, x: M, y: 0.68, w: 12.3, h: 0.4, margin: 0, fontFace: HF, fontSize: 15, bold: true, color: TXT });

// ---- Tier 1: ingestion pipeline (5 boxes, left to right) ----
const y1 = 1.35, h1 = 1.7;
const bw = 2.16, ar = 0.42;
let x = M;
box(s, x, y1, bw, h1, INK, "CADCFC", "Sources", ["Gujarat CSITMS (HLS)", "Independent RTSP", "(MediaMTX)", "Manual / CSV"], "FFFFFF");
arrowR(s, x + bw, y1 + h1 / 2, ar); x += bw + ar;
box(s, x, y1, bw, h1, MIST, BODY, "Adapters", ["CameraSourceAdapter", "discover · normalize", "resolve stream · health", "provenance stamp"]);
arrowR(s, x + bw, y1 + h1 / 2, ar); x += bw + ar;
box(s, x, y1, bw, h1, MIST, BODY, "Canonical registry", ["Postgres + PostGIS", "geo points (SRID 4326)", "cameras · events · alerts"]);
arrowR(s, x + bw, y1 + h1 / 2, ar); x += bw + ar;
box(s, x, y1, bw, h1, INK2, "CADCFC", "Backend API", ["FastAPI /api", "registry · tracking", "alerts · auth / RBAC", "single DB writer"], "FFFFFF");
arrowR(s, x + bw, y1 + h1 / 2, ar); x += bw + ar;
box(s, x, y1, bw, h1, MIST, BODY, "Ops console", ["React · Vite", "MapLibre GIS map", "live view · detections", "tracking · calibration"]);

// ---- connector into tier 2 ----
arrowD(s, M + bw + ar + bw / 2 - 0.25, y1 + h1 + 0.02, "adapters feed the registry; worker posts to the API");

// ---- Tier 2: real-time analytics, federation & alerting ----
const y2 = 3.85, h2 = 1.85;
s.addText("REAL-TIME ANALYTICS, FEDERATION & ALERTING", { isTextBox: true, x: M, y: y2 - 0.34, w: 11, h: 0.3, margin: 0, fontFace: BF, fontSize: 11, bold: true, color: TEAL, charSpacing: 2 });
let x2 = M;
box(s, x2, y2, bw + 0.35, h2, PAPER, BODY, "Analytics worker (CV)", ["OpenCV capture (RTSP/TCP, HLS)", "YOLOv8 vehicle + ByteTrack", "YOLO plate + EasyOCR (ANPR)", "posts detections + frame counts"]);
s.addShape(p.ShapeType.roundRect, { x: x2, y: y2, w: bw + 0.35, h: h2, rectRadius: 0.09, fill: { type: "none" }, line: { color: LINE, width: 1 } });
arrowR(s, x2 + bw + 0.35, y2 + h2 / 2, ar); x2 += bw + 0.35 + ar;
box(s, x2, y2, bw + 0.15, h2, INK2, "CADCFC", "Event bus", ["Redis Streams (proto)", "detection events", "→ Redpanda at scale"], "FFFFFF");
arrowR(s, x2 + bw + 0.15, y2 + h2 / 2, ar); x2 += bw + 0.15 + ar;
box(s, x2, y2, bw + 0.55, h2, MIST, BODY, "Alert engine", ["congestion / surge (daypart)", "watchlist (BOLO) match", "cloned-plate (impossible move)", "throttled · evidence-gated"]);
arrowR(s, x2 + bw + 0.55, y2 + h2 / 2, ar); x2 += bw + 0.55 + ar;
box(s, x2, y2, bw + 0.15, h2, MIST, BODY, "Evidence store", ["private object storage", "authenticated proxy", "dedup + retention"]);

// ---- foundation band ----
const yb = 6.05;
card(s, M, yb, W - 2 * M, 0.95, INK);
s.addText([
  { text: "Cross-cutting:  ", options: { bold: true, color: "FFFFFF" } },
  { text: "signed-JWT identity  ·  scoped RBAC  ·  tamper-evident audit  ·  source-system provenance on every event  ·  fail-loud health with no synthetic fallback", options: { color: "CADCFC" } },
], { isTextBox: true, x: M + 0.4, y: yb, w: W - 2 * M - 0.8, h: 0.95, margin: 0, valign: "middle", fontFace: BF, fontSize: 13, lineSpacingMultiple: 1.1 });

s.addText("Netra · Gujarat Police Innovation Challenge 2026", { isTextBox: true, x: M, y: H - 0.34, w: 9, h: 0.3, margin: 0, fontFace: BF, fontSize: 9, color: MUTED });

p.writeFile({ fileName: "netra_diagram.pptx" }).then((f) => console.log("wrote", f));
