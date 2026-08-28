const PptxGenJS = require("pptxgenjs");
const p = new PptxGenJS();
p.layout = "LAYOUT_WIDE";           // 13.33 x 7.5
const W = 13.33, H = 7.5, M = 0.6;

// ---- palette (midnight authority + amber vigilance; "Netra" = the eye) ----
const INK = "0E1A2B", INK2 = "16273F", PAPER = "FFFFFF", MIST = "F3F6FB";
const STEEL = "2B4C7E", AMBER = "F59E0B", TEAL = "0E9AA0";
const TXT = "16273F", BODY = "3A4A61", MUTED = "7A8AA3", LINE = "DCE3EE";
const GREEN = "16A34A", RED = "DC2626";
const HF = "Cambria", BF = "Calibri";

const shadow = () => ({ type: "outer", color: "0E1A2B", blur: 9, offset: 3, angle: 90, opacity: 0.16 });

function bg(s, color) { s.background = { color }; }
function eyebrow(s, t, x, y, color) {
  s.addText(t.toUpperCase(), { isTextBox: true, x, y, w: 9, h: 0.3, margin: 0,
    fontFace: BF, fontSize: 12, bold: true, color, charSpacing: 3 });
}
function title(s, t, x, y, color, size) {
  s.addText(t, { isTextBox: true, x, y, w: W - 2 * x, h: 1.0, margin: 0,
    fontFace: HF, fontSize: size || 34, bold: true, color: color || TXT, lineSpacingMultiple: 0.98 });
}
function card(s, x, y, w, h, fill) {
  s.addShape(p.ShapeType.roundRect, { x, y, w, h, rectRadius: 0.09,
    fill: { color: fill }, line: { color: fill }, shadow: shadow() });
}
function circle(s, x, y, d, fill, glyph, gcolor, gsize) {
  s.addShape(p.ShapeType.ellipse, { x, y, w: d, h: d, fill: { color: fill }, line: { type: "none" } });
  if (glyph) s.addText(glyph, { isTextBox: true, x, y, w: d, h: d, margin: 0, align: "center", valign: "middle",
    fontFace: BF, fontSize: gsize || 15, bold: true, color: gcolor || "FFFFFF" });
}
function foot(s, n, dark) {
  s.addText("Netra · Gujarat Police Innovation Challenge 2026", { isTextBox: true, x: M, y: H - 0.42, w: 8, h: 0.3,
    margin: 0, fontFace: BF, fontSize: 9, color: dark ? "6E7F98" : MUTED });
  s.addText(String(n), { isTextBox: true, x: W - M - 0.6, y: H - 0.42, w: 0.6, h: 0.3, margin: 0, align: "right",
    fontFace: BF, fontSize: 9, color: dark ? "6E7F98" : MUTED });
}

// ============================ 1 · TITLE ============================
(() => {
  const s = p.addSlide(); bg(s, INK);
  // concentric "eye" motif, right side
  const cx = 10.7, cy = 3.7;
  [[3.4, "1B2E49"], [2.5, "22405F"], [1.6, STEEL]].forEach(([d, c]) =>
    s.addShape(p.ShapeType.ellipse, { x: cx - d / 2, y: cy - d / 2, w: d, h: d, fill: { color: c }, line: { type: "none" } }));
  s.addShape(p.ShapeType.ellipse, { x: cx - 0.42, y: cy - 0.42, w: 0.84, h: 0.84, fill: { color: AMBER }, line: { type: "none" } });
  eyebrow(s, "Gujarat Police Innovation Challenge 2026", M, 0.9, AMBER);
  s.addText("NETRA", { isTextBox: true, x: M, y: 1.7, w: 8, h: 1.5, margin: 0, fontFace: HF, fontSize: 96, bold: true, color: "FFFFFF", charSpacing: 2 });
  s.addText("Unified CCTV Integration & Intelligence Platform", { isTextBox: true, x: M, y: 3.25, w: 8.2, h: 0.6, margin: 0, fontFace: HF, fontSize: 24, color: "CADCFC" });
  s.addText("One federation layer over every camera - reconstruct any vehicle's route across the state, from a single registration number.",
    { isTextBox: true, x: M, y: 4.05, w: 7.7, h: 0.9, margin: 0, fontFace: BF, fontSize: 15, color: "9FB2CC", lineSpacingMultiple: 1.15 });
  const chips = ["Model 1 · Registry + GIS", "Model 2 · Analytics", "Model 3 · Federation"];
  let x = M;
  chips.forEach((c) => {
    const w = 0.28 + c.length * 0.093;
    s.addShape(p.ShapeType.roundRect, { x, y: 5.4, w, h: 0.44, rectRadius: 0.22, fill: { color: INK2 }, line: { color: STEEL, width: 1 } });
    s.addText(c, { isTextBox: true, x, y: 5.4, w, h: 0.44, margin: 0, align: "center", valign: "middle", fontFace: BF, fontSize: 11.5, bold: true, color: "CADCFC" });
    x += w + 0.2;
  });
  foot(s, 1, true);
})();

// ============================ 2 · PROBLEM ============================
(() => {
  const s = p.addSlide(); bg(s, PAPER);
  eyebrow(s, "The problem", M, 0.6, AMBER);
  title(s, "Cameras everywhere - but no way to follow a vehicle", M, 0.95, TXT, 30);
  const items = [
    ["◧", "Siloed across departments", "Traffic, city police, transport and private VMS platforms don't talk to each other. Footage lives in incompatible islands."],
    ["◎", "No unified operational view", "Operators tab between systems. There is no single map, no shared registry, no cross-system search."],
    ["➤", "Can't answer “where did it go?”", "The core investigative question - a vehicle's path across the city - needs hours of manual review across many recorders."],
  ];
  const cw = (W - 2 * M - 2 * 0.4) / 3;
  items.forEach(([g, h, b], i) => {
    const x = M + i * (cw + 0.4);
    card(s, x, 2.15, cw, 3.6, MIST);
    circle(s, x + 0.4, 2.5, 0.72, INK, g, AMBER, 24);
    s.addText(h, { isTextBox: true, x: x + 0.4, y: 3.45, w: cw - 0.8, h: 0.7, margin: 0, fontFace: HF, fontSize: 17, bold: true, color: TXT });
    s.addText(b, { isTextBox: true, x: x + 0.4, y: 4.2, w: cw - 0.8, h: 1.4, margin: 0, fontFace: BF, fontSize: 13, color: BODY, lineSpacingMultiple: 1.2 });
  });
  s.addText("Netra closes this gap without ripping out a single existing camera or VMS.",
    { isTextBox: true, x: M, y: 6.1, w: W - 2 * M, h: 0.5, margin: 0, fontFace: HF, italic: true, fontSize: 16, color: STEEL });
  foot(s, 2);
})();

// ============================ 3 · THE TEST (dark) ============================
(() => {
  const s = p.addSlide(); bg(s, INK);
  eyebrow(s, "The scored test case", M, 0.6, AMBER);
  title(s, "A registration number in - a route out", M, 0.95, "FFFFFF", 30);
  const steps = [
    ["1", "Onboard", "Live feed → registry"],
    ["2", "Detect", "Vehicle + plate (ANPR)"],
    ["3", "Read", "Multi-frame consensus"],
    ["4", "Track", "Correlate across cameras"],
    ["5", "Route", "Map + timeline + CSV"],
  ];
  const bw = 2.15, gap = 0.29, startX = M, y = 2.35;
  steps.forEach(([n, h, d], i) => {
    const x = startX + i * (bw + gap);
    card(s, x, y, bw, 1.75, INK2);
    circle(s, x + 0.22, y + 0.22, 0.5, AMBER, n, INK, 16);
    s.addText(h, { isTextBox: true, x: x + 0.82, y: y + 0.24, w: bw - 0.9, h: 0.45, margin: 0, valign: "middle", fontFace: HF, fontSize: 15, bold: true, color: "FFFFFF" });
    s.addText(d, { isTextBox: true, x: x + 0.22, y: y + 0.95, w: bw - 0.4, h: 0.7, margin: 0, fontFace: BF, fontSize: 11.5, color: "9FB2CC", lineSpacingMultiple: 1.1 });
    if (i < steps.length - 1) s.addText("→", { isTextBox: true, x: x + bw - 0.06, y, w: gap + 0.12, h: 1.75, margin: 0, align: "center", valign: "middle", fontFace: BF, fontSize: 18, bold: true, color: AMBER });
  });
  // proof band
  card(s, M, 4.55, W - 2 * M, 1.7, INK2);
  s.addText("PROVEN LIVE", { isTextBox: true, x: M + 0.45, y: 4.8, w: 3, h: 0.3, margin: 0, fontFace: BF, fontSize: 12, bold: true, color: TEAL, charSpacing: 2 });
  const proof = [["GJ01AB1234", "vehicle of interest"], ["3", "cameras on the route"], ["300", "correlated sightings"], ["live RTSP", "not a recording"]];
  const pw = (W - 2 * M - 0.9) / 4;
  proof.forEach(([n, l], i) => {
    const x = M + 0.45 + i * pw;
    s.addText(n, { isTextBox: true, x, y: 5.15, w: pw - 0.2, h: 0.6, margin: 0, fontFace: HF, fontSize: n.length > 6 ? 21 : 32, bold: true, color: "FFFFFF" });
    s.addText(l, { isTextBox: true, x, y: 5.78, w: pw - 0.2, h: 0.35, margin: 0, fontFace: BF, fontSize: 12, color: "9FB2CC" });
  });
  foot(s, 3, true);
})();

// ============================ 4 · SOLUTION ============================
(() => {
  const s = p.addSlide(); bg(s, PAPER);
  eyebrow(s, "The approach", M, 0.6, AMBER);
  title(s, "One platform, three models, one federation layer", M, 0.95, TXT, 30);
  const models = [
    [STEEL, "MODEL 1", "Registry + GIS", "Every camera catalogued, geolocated, and lifecycle-managed - the single source of truth for the state's CCTV estate."],
    [TEAL, "MODEL 2", "Unified viewing + analytics", "One map and viewer over all feeds, with ANPR, cross-camera vehicle tracking and evidence-backed alerts."],
    [AMBER, "MODEL 3", "VMS federation", "Formal adapters normalize independent systems (CSITMS + RTSP/ONVIF) into one event stream with full provenance."],
  ];
  const cw = (W - 2 * M - 2 * 0.4) / 3;
  models.forEach(([c, tag, h, b], i) => {
    const x = M + i * (cw + 0.4);
    card(s, x, 2.1, cw, 2.85, MIST);
    s.addShape(p.ShapeType.roundRect, { x: x + 0.4, y: 2.45, w: 1.35, h: 0.42, rectRadius: 0.21, fill: { color: c }, line: { type: "none" } });
    s.addText(tag, { isTextBox: true, x: x + 0.4, y: 2.45, w: 1.35, h: 0.42, margin: 0, align: "center", valign: "middle", fontFace: BF, fontSize: 11, bold: true, color: "FFFFFF", charSpacing: 1 });
    s.addText(h, { isTextBox: true, x: x + 0.4, y: 3.05, w: cw - 0.8, h: 0.7, margin: 0, fontFace: HF, fontSize: 18, bold: true, color: TXT });
    s.addText(b, { isTextBox: true, x: x + 0.4, y: 3.75, w: cw - 0.8, h: 1.1, margin: 0, fontFace: BF, fontSize: 12.5, color: BODY, lineSpacingMultiple: 1.18 });
  });
  // federation band
  card(s, M, 5.2, W - 2 * M, 1.0, INK);
  s.addText("+ selective Model 4 central AI  ·  bound together by a real event-driven federation middleware (Redis Streams → Redpanda at scale)",
    { isTextBox: true, x: M + 0.45, y: 5.2, w: W - 2 * M - 0.9, h: 1.0, margin: 0, valign: "middle", fontFace: BF, fontSize: 14, bold: true, color: "CADCFC" });
  foot(s, 4);
})();

// ============================ 5 · ARCHITECTURE ============================
(() => {
  const s = p.addSlide(); bg(s, PAPER);
  eyebrow(s, "Architecture", M, 0.6, AMBER);
  title(s, "Adapters → federation → event bus → services", M, 0.95, TXT, 30);
  const col = (x, w, y, h, fill, tcol, head, lines, headColor) => {
    card(s, x, y, w, h, fill);
    s.addText(head, { isTextBox: true, x: x + 0.2, y: y + 0.16, w: w - 0.4, h: 0.4, margin: 0, fontFace: HF, fontSize: 13.5, bold: true, color: headColor || tcol });
    s.addText(lines.map((t) => ({ text: t, options: { bullet: false, breakLine: true } })),
      { isTextBox: true, x: x + 0.2, y: y + 0.6, w: w - 0.4, h: h - 0.75, margin: 0, fontFace: BF, fontSize: 11, color: tcol, lineSpacingMultiple: 1.15 });
  };
  const y0 = 2.15, ch = 2.35;
  // sources
  col(M, 2.5, y0, ch, INK, "CADCFC", "Sources", ["Gujarat CSITMS", "(HLS · 30 cams)", "", "Independent RTSP", "(MediaMTX · 3 cams)"], "FFFFFF");
  arrow(s, M + 2.5, y0 + ch / 2);
  // adapters
  col(M + 2.9, 2.5, y0, ch, MIST, BODY, "Adapters", ["CameraAdapter contract:", "discover · normalize", "resolve_stream", "health · provenance"]);
  arrow(s, M + 2.9 + 2.5, y0 + ch / 2);
  // federation
  col(M + 5.8, 2.6, y0, ch, MIST, BODY, "Federation", ["Canonical schema", "Timestamp normalize", "Event dedup", "Cross-system correlate"]);
  arrow(s, M + 5.8 + 2.6, y0 + ch / 2);
  // event bus
  col(M + 8.8, W - M - (M + 8.8), y0, ch, INK2, "CADCFC", "Event bus", ["Redis Streams (proto)", "→ Redpanda / NATS", "at statewide scale"], "FFFFFF");
  // services row
  const sy = 5.05, sh = 1.25;
  const svcs = [["Analytics · ANPR", TEAL], ["Unified viewer + GIS", STEEL], ["Alerts + Watchlist", AMBER], ["Vehicle route + CSV", "6D4AFF"]];
  const sw = (W - 2 * M - 3 * 0.3) / 4;
  svcs.forEach(([t, c], i) => {
    const x = M + i * (sw + 0.3);
    card(s, x, sy, sw, sh, PAPER);
    s.addShape(p.ShapeType.roundRect, { x, y: sy, w: sw, h: sh, rectRadius: 0.09, fill: { type: "none" }, line: { color: LINE, width: 1 } });
    circle(s, x + 0.25, sy + 0.3, 0.5, c, "◆", "FFFFFF", 13);
    s.addText(t, { isTextBox: true, x: x + 0.85, y: sy, w: sw - 1.0, h: sh, margin: 0, valign: "middle", fontFace: HF, fontSize: 13.5, bold: true, color: TXT });
  });
  s.addText("Persistence: PostgreSQL + PostGIS  ·  private object storage (evidence)  ·  signed-JWT auth, RBAC & tamper-evident audit across every layer",
    { isTextBox: true, x: M, y: 6.5, w: W - 2 * M, h: 0.4, margin: 0, fontFace: BF, italic: true, fontSize: 12, color: MUTED });
  foot(s, 5);
})();
function arrow(s, x, y) {
  s.addText("→", { isTextBox: true, x: x - 0.02, y: y - 0.3, w: 0.42, h: 0.6, margin: 0, align: "center", valign: "middle", fontFace: BF, fontSize: 20, bold: true, color: AMBER });
}

// ============================ 6 · MODEL 1 ============================
(() => {
  const s = p.addSlide(); bg(s, PAPER);
  eyebrow(s, "Model 1 · Registry + GIS", M, 0.6, STEEL);
  title(s, "The state's CCTV estate, catalogued and alive", M, 0.95, TXT, 30);
  const stats = [["33", "cameras onboarded"], ["13", "districts mapped"], ["100%", "geolocated"], ["100%", "asset records complete"]];
  const sw = (W - 2 * M - 3 * 0.3) / 4;
  stats.forEach(([n, l], i) => {
    const x = M + i * (sw + 0.3);
    card(s, x, 2.1, sw, 1.5, MIST);
    s.addText(n, { isTextBox: true, x, y: 2.25, w: sw, h: 0.75, margin: 0, align: "center", fontFace: HF, fontSize: 40, bold: true, color: STEEL });
    s.addText(l, { isTextBox: true, x, y: 3.05, w: sw, h: 0.4, margin: 0, align: "center", fontFace: BF, fontSize: 12, color: BODY });
  });
  const feats = [
    ["Live onboarding", "Real government feed via a typed adapter; coordinates geocoded and flagged, category inferred - nothing faked."],
    ["Asset lifecycle", "Make, model, install date, AMC and EOL per camera - 17 maintenance-due and 12 end-of-life surfaced automatically."],
    ["Coverage & gap analysis", "Per-district coverage, thin-coverage and offline lists; downloadable gap report for planning."],
  ];
  const cw = (W - 2 * M - 2 * 0.4) / 3;
  feats.forEach(([h, b], i) => {
    const x = M + i * (cw + 0.4);
    card(s, x, 3.9, cw, 2.25, PAPER);
    s.addShape(p.ShapeType.roundRect, { x, y: 3.9, w: cw, h: 2.25, rectRadius: 0.09, fill: { type: "none" }, line: { color: LINE, width: 1 } });
    s.addText(h, { isTextBox: true, x: x + 0.3, y: 4.15, w: cw - 0.6, h: 0.5, margin: 0, fontFace: HF, fontSize: 15, bold: true, color: TXT });
    s.addText(b, { isTextBox: true, x: x + 0.3, y: 4.7, w: cw - 0.6, h: 1.3, margin: 0, fontFace: BF, fontSize: 12, color: BODY, lineSpacingMultiple: 1.2 });
  });
  foot(s, 6);
})();

// ============================ 7 · MODEL 2 ============================
(() => {
  const s = p.addSlide(); bg(s, PAPER);
  eyebrow(s, "Model 2 · Unified viewing + analytics", M, 0.6, TEAL);
  title(s, "Real analytics, evidence-gated end to end", M, 0.95, TXT, 30);
  // ANPR pipeline
  const stg = ["Vehicle detect", "Plate detect", "OCR read", "Multi-frame\nconsensus", "Durable event\n+ evidence"];
  const bw = 2.15, gap = 0.28, y = 2.2;
  stg.forEach((t, i) => {
    const x = M + i * (bw + gap);
    card(s, x, y, bw, 1.15, i === stg.length - 1 ? INK2 : MIST);
    s.addText(t, { isTextBox: true, x: x + 0.1, y, w: bw - 0.2, h: 1.15, margin: 0, align: "center", valign: "middle", fontFace: HF, fontSize: 13.5, bold: true, color: i === stg.length - 1 ? "FFFFFF" : TXT, lineSpacingMultiple: 1.0 });
    if (i < stg.length - 1) s.addText("→", { isTextBox: true, x: x + bw - 0.04, y, w: gap + 0.1, h: 1.15, margin: 0, align: "center", valign: "middle", fontFace: BF, fontSize: 16, bold: true, color: TEAL });
  });
  const pts = [
    ["Consensus gating", "A plate is stored only after ≥3 corroborating reads pass a format check - low-confidence guesses are rejected, not saved."],
    ["Evidence-backed", "100% of stored events carry a decoded evidence frame; metadata-only detections never enter the operational timeline."],
    ["Search & correlate", "Searchable plate + camera-wise indexing feed cross-camera route reconstruction and boxed watchlist (BOLO) alerts."],
  ];
  const cw = (W - 2 * M - 2 * 0.4) / 3;
  pts.forEach(([h, b], i) => {
    const x = M + i * (cw + 0.4);
    card(s, x, 3.75, cw, 2.4, MIST);
    circle(s, x + 0.35, 4.05, 0.5, TEAL, "✓", "FFFFFF", 15);
    s.addText(h, { isTextBox: true, x: x + 0.35, y: 4.7, w: cw - 0.7, h: 0.45, margin: 0, fontFace: HF, fontSize: 15, bold: true, color: TXT });
    s.addText(b, { isTextBox: true, x: x + 0.35, y: 5.15, w: cw - 0.7, h: 1.0, margin: 0, fontFace: BF, fontSize: 12, color: BODY, lineSpacingMultiple: 1.18 });
  });
  s.addText("Honest by design: plate yield on wide-angle overview feeds is near-zero (a source-resolution limit), so a controlled ANPR-grade RTSP clip proves the full read → route → CSV path.",
    { isTextBox: true, x: M, y: 6.4, w: W - 2 * M, h: 0.5, margin: 0, fontFace: BF, italic: true, fontSize: 11.5, color: MUTED, lineSpacingMultiple: 1.1 });
  foot(s, 7);
})();

// ============================ 8 · MODEL 3 ============================
(() => {
  const s = p.addSlide(); bg(s, PAPER);
  eyebrow(s, "Model 3 · VMS federation", M, 0.6, AMBER);
  title(s, "Two genuinely independent systems, one stream", M, 0.95, TXT, 30);
  const sys = [
    [STEEL, "Gujarat CSITMS", "Government feed", ["Adapter: csitms_api", "Delivery: HLS live edge", "30 cameras · statewide"]],
    [AMBER, "Independent RTSP System", "Participant / test rig", ["Adapter: rtsp_catalog", "Delivery: RTSP (MediaMTX)", "3 corridor cameras"]],
  ];
  const cw = (W - 2 * M - 0.5) / 2;
  sys.forEach(([c, h, sub, lines], i) => {
    const x = M + i * (cw + 0.5);
    card(s, x, 2.15, cw, 2.5, MIST);
    circle(s, x + 0.4, 2.5, 0.6, c, "◉", "FFFFFF", 18);
    s.addText(h, { isTextBox: true, x: x + 1.2, y: 2.5, w: cw - 1.5, h: 0.4, margin: 0, valign: "middle", fontFace: HF, fontSize: 17, bold: true, color: TXT });
    s.addText(sub, { isTextBox: true, x: x + 1.2, y: 2.92, w: cw - 1.5, h: 0.3, margin: 0, fontFace: BF, fontSize: 12, italic: true, color: MUTED });
    s.addText(lines.map((t) => ({ text: t, options: { bullet: { code: "2022", indent: 12 }, breakLine: true, color: BODY } })),
      { isTextBox: true, x: x + 0.45, y: 3.4, w: cw - 0.9, h: 1.1, margin: 0, fontFace: BF, fontSize: 13, lineSpacingMultiple: 1.2 });
  });
  // outcome band
  card(s, M, 4.95, W - 2 * M, 1.25, INK);
  s.addText([
    { text: "Same vehicle, both systems.  ", options: { bold: true, color: "FFFFFF" } },
    { text: "Every event carries source-system provenance; the cross-camera route spans both - federation report shows ", options: { color: "CADCFC" } },
    { text: "demonstration_gap: null", options: { bold: true, color: TEAL, fontFace: "Courier New" } },
    { text: ".", options: { color: "CADCFC" } },
  ], { isTextBox: true, x: M + 0.45, y: 4.95, w: W - 2 * M - 0.9, h: 1.25, margin: 0, valign: "middle", fontFace: BF, fontSize: 15, lineSpacingMultiple: 1.15 });
  foot(s, 8);
})();

// ============================ 9 · DATA INTEGRITY ============================
(() => {
  const s = p.addSlide(); bg(s, PAPER);
  eyebrow(s, "Trust", M, 0.6, AMBER);
  title(s, "Real data, or an honest error - never a fake", M, 0.95, TXT, 30);
  const rows = [
    ["Live feeds only", "Cameras come only from the real government feed. If it's unreachable, the registry stays empty and the true error is surfaced - no synthetic substitution."],
    ["Analytics from the feed", "Congestion and surge alerts are computed from actual per-frame counts against a learned baseline - not mock database rows."],
    ["Representative data is labelled", "Watchlist, asset lifecycle and demo users are clearly marked representative (challenge Step 3) - never passed off as live government records."],
    ["Fail gracefully", "Firewalled RTSP, a 502 media plane, an offline feed - each degrades visibly with the real reason, never a silent fallback."],
  ];
  const cw = (W - 2 * M - 0.5) / 2, ch = 1.75;
  rows.forEach(([h, b], i) => {
    const x = M + (i % 2) * (cw + 0.5);
    const y = 2.15 + Math.floor(i / 2) * (ch + 0.35);
    card(s, x, y, cw, ch, MIST);
    circle(s, x + 0.35, y + 0.35, 0.5, INK, "✓", AMBER, 15);
    s.addText(h, { isTextBox: true, x: x + 1.05, y: y + 0.3, w: cw - 1.3, h: 0.5, margin: 0, valign: "middle", fontFace: HF, fontSize: 16, bold: true, color: TXT });
    s.addText(b, { isTextBox: true, x: x + 1.05, y: y + 0.8, w: cw - 1.35, h: 0.85, margin: 0, fontFace: BF, fontSize: 12, color: BODY, lineSpacingMultiple: 1.15 });
  });
  foot(s, 9);
})();

// ============================ 10 · SECURITY ============================
(() => {
  const s = p.addSlide(); bg(s, PAPER);
  eyebrow(s, "Security & governance", M, 0.6, AMBER);
  title(s, "Built for a police-grade chain of custody", M, 0.95, TXT, 30);
  const pillars = [
    ["◉", "Signed-token identity", "Spoofable role headers replaced by signed JWTs. A forged role fails verification - a spoofed header now returns 401."],
    ["▣", "Scoped RBAC", "State admin, district officer (district-scoped), viewer. Every camera and stat filtered by verified identity."],
    ["▤", "Private evidence store", "Evidence moved off local disk into a private object-storage bucket, served only through an authenticated proxy."],
    ["◰", "Tamper-evident audit", "Every track query, alert ack and BOLO change is attributed to a user and role in an append-only trail."],
  ];
  const cw = (W - 2 * M - 3 * 0.3) / 4;
  pillars.forEach(([g, h, b], i) => {
    const x = M + i * (cw + 0.3);
    card(s, x, 2.15, cw, 3.6, MIST);
    circle(s, x + (cw - 0.85) / 2, 2.5, 0.85, INK, g, AMBER, 26);
    s.addText(h, { isTextBox: true, x: x + 0.25, y: 3.55, w: cw - 0.5, h: 0.7, margin: 0, align: "center", fontFace: HF, fontSize: 15, bold: true, color: TXT });
    s.addText(b, { isTextBox: true, x: x + 0.25, y: 4.25, w: cw - 0.5, h: 1.4, margin: 0, align: "center", fontFace: BF, fontSize: 11.5, color: BODY, lineSpacingMultiple: 1.18 });
  });
  foot(s, 10);
})();

// ============================ 11 · SCALABILITY ============================
(() => {
  const s = p.addSlide(); bg(s, PAPER);
  eyebrow(s, "Scalability - measured", M, 0.6, AMBER);
  title(s, "Benchmarked, bottlenecked, and fixed", M, 0.95, TXT, 30);
  // native bar chart of ingestion throughput
  s.addChart(p.ChartType.bar, [{
    name: "req/s", labels: ["As-shipped", "+ camera cache", "+ batched persist"], values: [15, 222, 820],
  }], {
    x: M, y: 2.15, w: 6.0, h: 3.7, barDir: "col", chartColors: [STEEL, TEAL, AMBER],
    showValue: true, dataLabelPosition: "outEnd", dataLabelColor: TXT, dataLabelFontFace: BF, dataLabelFontSize: 13, dataLabelFontBold: true,
    showTitle: true, title: "Ingestion throughput  (POST /api/frame, one backend process)", titleColor: TXT, titleFontFace: HF, titleFontSize: 13,
    showLegend: false, catAxisLabelColor: BODY, catAxisLabelFontFace: BF, catAxisLabelFontSize: 11,
    valAxisHidden: true, valGridLine: { style: "none" }, catGridLine: { style: "none" }, valAxisMaxVal: 950,
  });
  s.addText("15 → 820 req/s  (~55×)", { isTextBox: true, x: M, y: 5.9, w: 6.0, h: 0.4, margin: 0, align: "center", fontFace: HF, italic: true, fontSize: 14, bold: true, color: AMBER });
  // right column: what it means
  const rx = 7.1, rw = W - M - rx;
  const facts = [
    ["164 feeds / process", "One backend now sustains ~164 feeds at 5 fps - 3.3× the 50-feed target, 0 errors. Replicas scale it linearly."],
    ["Analytics is GPU work", "Full ANPR is ~5 s/frame on CPU - confirming the design: edge/regional GPU pools (~40 cams/GPU), not a central CPU farm."],
    ["Bus is never the bottleneck", "Statewide event load (40–200k/s) is ~0.3% of the video data; a small Redpanda cluster clears it with headroom."],
  ];
  let y = 2.15;
  facts.forEach(([h, b]) => {
    card(s, rx, y, rw, 1.15, MIST);
    s.addText(h, { isTextBox: true, x: rx + 0.3, y: y + 0.14, w: rw - 0.6, h: 0.4, margin: 0, fontFace: HF, fontSize: 15, bold: true, color: STEEL });
    s.addText(b, { isTextBox: true, x: rx + 0.3, y: y + 0.54, w: rw - 0.6, h: 0.55, margin: 0, fontFace: BF, fontSize: 11.5, color: BODY, lineSpacingMultiple: 1.12 });
    y += 1.25;
  });
  foot(s, 11);
})();

// ============================ 12 · READINESS (dark) ============================
(() => {
  const s = p.addSlide(); bg(s, INK);
  eyebrow(s, "Where we stand", M, 0.6, AMBER);
  title(s, "All three models - measured PASS", M, 0.95, "FFFFFF", 30);
  const models = [
    ["MODEL 1", "Registry + GIS", "33 cams · 100% mapped · 100% asset records"],
    ["MODEL 2", "Unified viewing + analytics", "100% events evidence-backed · live ANPR route"],
    ["MODEL 3", "VMS federation", "2 adapters · provenance · demonstration_gap null"],
  ];
  const cw = (W - 2 * M - 2 * 0.4) / 3;
  models.forEach(([tag, h, d], i) => {
    const x = M + i * (cw + 0.4);
    card(s, x, 2.1, cw, 1.95, INK2);
    s.addText(tag, { isTextBox: true, x: x + 0.35, y: 2.35, w: cw - 1.4, h: 0.35, margin: 0, fontFace: BF, fontSize: 12, bold: true, color: "9FB2CC", charSpacing: 1 });
    s.addShape(p.ShapeType.roundRect, { x: x + cw - 1.15, y: 2.32, w: 0.8, h: 0.42, rectRadius: 0.21, fill: { color: GREEN }, line: { type: "none" } });
    s.addText("PASS", { isTextBox: true, x: x + cw - 1.15, y: 2.32, w: 0.8, h: 0.42, margin: 0, align: "center", valign: "middle", fontFace: BF, fontSize: 11, bold: true, color: "FFFFFF" });
    s.addText(h, { isTextBox: true, x: x + 0.35, y: 2.8, w: cw - 0.7, h: 0.5, margin: 0, fontFace: HF, fontSize: 16, bold: true, color: "FFFFFF" });
    s.addText(d, { isTextBox: true, x: x + 0.35, y: 3.3, w: cw - 0.7, h: 0.65, margin: 0, fontFace: BF, fontSize: 11.5, color: "9FB2CC", lineSpacingMultiple: 1.12 });
  });
  // blockers closed
  s.addText("Every non-negotiable blocker closed", { isTextBox: true, x: M, y: 4.35, w: 9, h: 0.4, margin: 0, fontFace: HF, fontSize: 16, bold: true, color: "FFFFFF" });
  const closed = ["ANPR correctness", "Analytics stability", "Truthful KPIs", "Auth: headers → JWT", "Evidence → storage", "2-system federation", "Alert calibration", "50-feed benchmark"];
  const gw = (W - 2 * M - 3 * 0.3) / 4;
  closed.forEach((t, i) => {
    const x = M + (i % 4) * (gw + 0.3);
    const y = 4.85 + Math.floor(i / 4) * 0.62;
    s.addShape(p.ShapeType.roundRect, { x, y, w: gw, h: 0.5, rectRadius: 0.1, fill: { color: INK2 }, line: { type: "none" } });
    circle(s, x + 0.14, y + 0.13, 0.24, GREEN, "✓", "FFFFFF", 10);
    s.addText(t, { isTextBox: true, x: x + 0.5, y, w: gw - 0.6, h: 0.5, margin: 0, valign: "middle", fontFace: BF, fontSize: 11.5, bold: true, color: "CADCFC" });
  });
  foot(s, 12, true);
})();

// ============================ 13 · ROADMAP ============================
(() => {
  const s = p.addSlide(); bg(s, PAPER);
  eyebrow(s, "The path to statewide", M, 0.6, AMBER);
  title(s, "From pilot to ~80,000 cameras", M, 0.95, TXT, 30);
  const phases = [
    ["01", "Pilot", "One city / range. Federate CSITMS + a participant VMS; validate route reconstruction on real corridors."],
    ["02", "Range expansion", "Scale to a full police range. Add edge/regional GPU pools; tune GPU-to-bandwidth ratios against real load."],
    ["03", "Statewide", "Hierarchical edge → regional → state topology. Redpanda core, per-region Kubernetes, mTLS everywhere."],
  ];
  const cw = (W - 2 * M - 2 * 0.4) / 3;
  phases.forEach(([n, h, b], i) => {
    const x = M + i * (cw + 0.4);
    card(s, x, 2.1, cw, 2.5, MIST);
    circle(s, x + 0.35, 2.4, 0.7, INK, n, AMBER, 20);
    s.addText(h, { isTextBox: true, x: x + 0.35, y: 3.25, w: cw - 0.7, h: 0.5, margin: 0, fontFace: HF, fontSize: 17, bold: true, color: TXT });
    s.addText(b, { isTextBox: true, x: x + 0.35, y: 3.75, w: cw - 0.7, h: 1.0, margin: 0, fontFace: BF, fontSize: 12, color: BODY, lineSpacingMultiple: 1.18 });
    if (i < phases.length - 1) s.addText("→", { isTextBox: true, x: x + cw + 0.02, y: 2.1, w: 0.36, h: 2.5, margin: 0, align: "center", valign: "middle", fontFace: BF, fontSize: 20, bold: true, color: AMBER });
  });
  card(s, M, 5.0, W - 2 * M, 1.2, INK);
  s.addText([
    { text: "Why it's affordable at scale:  ", options: { bold: true, color: "FFFFFF" } },
    { text: "events are ~0.3% of the data that video is. Cross-camera search runs over ~100 TB of tiny events - not 32 PB of video - so it stays fast and horizontally shardable.", options: { color: "CADCFC" } },
  ], { isTextBox: true, x: M + 0.45, y: 5.0, w: W - 2 * M - 0.9, h: 1.2, margin: 0, valign: "middle", fontFace: BF, fontSize: 14, lineSpacingMultiple: 1.15 });
  foot(s, 13);
})();

// ============================ 14 · CLOSE (dark) ============================
(() => {
  const s = p.addSlide(); bg(s, INK);
  const cx = 6.66, cy = 2.7;
  [[2.2, "1B2E49"], [1.5, "22405F"]].forEach(([d, c]) =>
    s.addShape(p.ShapeType.ellipse, { x: cx - d / 2, y: cy - d / 2, w: d, h: d, fill: { color: c }, line: { type: "none" } }));
  s.addShape(p.ShapeType.ellipse, { x: cx - 0.33, y: cy - 0.33, w: 0.66, h: 0.66, fill: { color: AMBER }, line: { type: "none" } });
  s.addText("The state's eye - unified.", { isTextBox: true, x: 1, y: 3.9, w: W - 2, h: 0.9, margin: 0, align: "center", fontFace: HF, fontSize: 40, bold: true, color: "FFFFFF" });
  s.addText("Model 1 registry + GIS  ·  Model 2 analytics  ·  Model 3 federation  -  working, measured, and honest.",
    { isTextBox: true, x: 1, y: 4.85, w: W - 2, h: 0.5, margin: 0, align: "center", fontFace: BF, fontSize: 15, color: "9FB2CC" });
  s.addText("NETRA", { isTextBox: true, x: 1, y: 5.7, w: W - 2, h: 0.6, margin: 0, align: "center", fontFace: HF, fontSize: 22, bold: true, color: AMBER, charSpacing: 4 });
  foot(s, 14, true);
})();

p.writeFile({ fileName: "netra_deck.pptx" }).then((f) => console.log("wrote", f));
