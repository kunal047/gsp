import { useEffect, useState } from "react";
import {
  fetchAudit,
  fetchGapAnalysis,
  fetchFederationReport,
  fetchReadinessReport,
  fetchAlertBaselines,
  type AuditEntry,
  type GapAnalysis,
  type FederationReport,
  type ReadinessReport,
  type AlertCalibration,
} from "./api";
import { districtColor } from "./theme";

export default function OpsView() {
  const [gap, setGap] = useState<GapAnalysis | null>(null);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [federation, setFederation] = useState<FederationReport | null>(null);
  const [readiness, setReadiness] = useState<ReadinessReport | null>(null);
  const [calibration, setCalibration] = useState<AlertCalibration | null>(null);

  useEffect(() => {
    const load = () => {
      fetchGapAnalysis().then(setGap).catch(() => {});
      fetchAudit().then(setAudit).catch(() => {});
      fetchFederationReport().then(setFederation).catch(() => {});
      fetchReadinessReport().then(setReadiness).catch(() => {});
      fetchAlertBaselines().then(setCalibration).catch(() => {});
    };
    load();
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="ops">
      {readiness && (
        <section className="readiness" aria-label="Evaluation readiness">
          <div className="readiness-head">
            <div><span className="eyebrow">LIVE EVALUATION EVIDENCE</span><h2>Model 1–3 readiness</h2></div>
            <small>Measured {new Date(readiness.generated_at).toLocaleTimeString([], { hour12: false })}</small>
          </div>
          <div className="readiness-grid">
            {readiness.models.map((model) => (
              <article className={`readiness-card ${model.status}`} key={model.model}>
                <div className="readiness-title"><span>MODEL {model.model}</span><b>{model.status}</b></div>
                <h3>{model.title}</h3>
                <p>{model.summary}</p>
                <div className="readiness-checks">{model.checks.map((check) => (
                  <div key={check.label}><i className={check.ok ? "ok" : "gap"}>{check.ok ? "✓" : "!"}</i><span>{check.label}</span><strong>{check.value}</strong></div>
                ))}</div>
                {model.blocker && <div className="readiness-blocker">Next: {model.blocker}</div>}
              </article>
            ))}
          </div>
        </section>
      )}
      <div className="ops-col">
        <div className="section-title" style={{ marginTop: 0 }}>
          Coverage & Gap Analysis · Model 1
        </div>
        {gap && (
          <>
            <div className="ops-kpis">
              <div className="ops-kpi">
                <b>{gap.coverage_pct}%</b>
                <small>Coverage</small>
              </div>
              <div className="ops-kpi">
                <b style={{ color: "#22c55e" }}>{gap.online}</b>
                <small>Online</small>
              </div>
              <div className="ops-kpi">
                <b style={{ color: "#ef4444" }}>{gap.offline}</b>
                <small>Offline</small>
              </div>
              <div className="ops-kpi">
                <b>{gap.lifecycle_completeness_pct}%</b>
                <small>Asset records complete</small>
              </div>
            </div>

            <div className="ops-sub">Asset lifecycle</div>
            <div className="hint">
              {gap.maintenance_due} maintenance due · {gap.end_of_life} at end of life · {gap.incomplete_asset_records} records need make/model/install metadata
            </div>

            {gap.offline_cameras.length > 0 && (
              <>
                <div className="ops-sub">Offline feeds (health monitor)</div>
                {gap.offline_cameras.map((c) => (
                  <div className="ops-off" key={c.camera_id}>
                    <span className="off-dot" /> {c.name} - {c.site} ({c.city})
                  </div>
                ))}
              </>
            )}

            <div className="ops-sub">Thin coverage (≤1 camera)</div>
            <div className="watch-chips">
              {gap.thin_coverage.map((c) => (
                <span key={c} className="watch-chip" style={{ borderColor: "#f59e0b" }}>
                  {c}
                </span>
              ))}
            </div>

            <div className="ops-sub">Per-district</div>
            <table className="ops-table">
              <thead>
                <tr>
                  <th>District</th>
                  <th>Total</th>
                  <th>Online</th>
                  <th>Offline</th>
                </tr>
              </thead>
              <tbody>
                {gap.districts.map((d) => (
                  <tr key={d.city}>
                    <td>
                      <span
                        className="tdot"
                        style={{ background: districtColor(d.city) }}
                      />
                      {d.city}
                    </td>
                    <td>{d.total}</td>
                    <td style={{ color: "#22c55e" }}>{d.online}</td>
                    <td style={{ color: d.offline ? "#ef4444" : "inherit" }}>
                      {d.offline}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </div>

      <div className="ops-col">
        <div className="section-title" style={{ marginTop: 0 }}>
          Federation · Model 3
        </div>
        {federation && (
          <>
            <div className="hint">
              {federation.adapter_system_count} adapter-backed source system{federation.adapter_system_count === 1 ? "" : "s"} · {federation.camera_count} normalized cameras · {federation.event_count} tracked events
            </div>
            {federation.demonstration_gap && (
              <div className="hint" style={{ color: "#f59e0b" }}>
                Demonstration gap: {federation.demonstration_gap}
              </div>
            )}
            <table className="ops-table">
              <thead><tr><th>Source</th><th>Cameras</th><th>Online</th><th>Events</th></tr></thead>
              <tbody>{federation.systems.map((system) => (
                <tr key={system.source_system}>
                  <td>{system.source_system}<small style={{ display: "block" }}>{system.source_adapter}</small></td>
                  <td>{system.cameras}</td><td>{system.online}</td><td>{system.events}</td>
                </tr>
              ))}</tbody>
            </table>
          </>
        )}
        <div className="section-title" style={{ marginTop: 0 }}>
          Alert Calibration · adaptive per-camera thresholds
        </div>
        {calibration && (
          <>
            <div className="hint">
              Congestion floor {calibration.congestion_floor} · adaptive at
              baseline × {calibration.baseline_factor} once warmed
              ({calibration.warmup_samples} frames). Baselines are learned live
              and persist across restarts.
            </div>
            <table className="ops-table">
              <thead>
                <tr>
                  <th>Camera</th>
                  <th>Baseline</th>
                  <th>Samples</th>
                  <th>Peak</th>
                  <th>Threshold</th>
                </tr>
              </thead>
              <tbody>
                {calibration.cameras.length === 0 && (
                  <tr><td colSpan={5}><span className="hint">No baselines yet - cameras warming up.</span></td></tr>
                )}
                {calibration.cameras.slice(0, 12).map((c) => (
                  <tr key={c.camera_id}>
                    <td>{c.camera_id}</td>
                    <td>{c.baseline.toFixed(1)}</td>
                    <td>
                      {c.samples}
                      {!c.warmed && <em style={{ color: "#f59e0b" }}> · warming</em>}
                    </td>
                    <td>{c.peak}</td>
                    <td>
                      {c.congestion_threshold}
                      {c.override != null && (
                        <em style={{ color: "#60a5fa" }}> · pinned</em>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}

        <div className="section-title" style={{ marginTop: 0 }}>
          Audit Log · tamper-evident trail
        </div>
        <div className="audit-list">
          {audit.length === 0 && (
            <div className="hint">
              No audited actions yet. Track queries, alert acks and BOLO changes
              are recorded here with the acting user and role.
            </div>
          )}
          {audit.map((a) => (
            <div className="audit-row" key={a.id}>
              <div className="audit-action">{a.action}</div>
              <div className="audit-detail">{a.detail}</div>
              <div className="audit-meta">
                <span className="audit-user">{a.user}</span>
                <span className="audit-role">{a.role}</span>
                <span className="audit-time">
                  {new Date(a.ts).toLocaleTimeString([], { hour12: false })}
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
