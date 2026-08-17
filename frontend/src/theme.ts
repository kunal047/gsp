// District palette (primary map dimension for the live CSITMS feed).
const DISTRICT_PALETTE = [
  "#3b82f6", // blue
  "#f59e0b", // amber
  "#10b981", // emerald
  "#ef4444", // red
  "#a855f7", // purple
  "#06b6d4", // cyan
  "#ec4899", // pink
  "#84cc16", // lime
  "#f97316", // orange
  "#14b8a6", // teal
  "#8b5cf6", // violet
  "#eab308", // yellow
  "#64748b", // slate (fallback / unmapped)
];

const FIXED: Record<string, string> = {
  Ahmedabad: "#3b82f6",
  Junagadh: "#f59e0b",
  Navsari: "#10b981",
  Rajkot: "#ef4444",
  Gandhinagar: "#a855f7",
  "Gir Somnath": "#06b6d4",
  Patan: "#ec4899",
  Kutch: "#84cc16",
  Sabarkantha: "#f97316",
  Mehsana: "#14b8a6",
  Kheda: "#8b5cf6",
  Vadodara: "#eab308",
  "Gujarat (unmapped)": "#64748b",
};

export const STATUS_COLORS: Record<string, string> = {
  online: "#22c55e",
  degraded: "#f59e0b",
  offline: "#6b7280",
};

function hashColor(s: string): string {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return DISTRICT_PALETTE[Math.abs(h) % DISTRICT_PALETTE.length];
}

export function districtColor(d: string): string {
  return FIXED[d] || hashColor(d || "?");
}
