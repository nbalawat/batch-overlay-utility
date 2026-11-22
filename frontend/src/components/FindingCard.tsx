import { Link } from "react-router-dom";
import type { Finding } from "../api/types";
import { useEstate } from "../lib/estate";
import { shortJob } from "../lib/format";
import { StatusPill, VendorTag } from "./ui";

const METRIC_LABEL: Record<string, string> = {
  race_nights: "Race nights", nights: "Nights compared", median_wait_min: "Median wait (min)",
  slot_hours_month: "Worker slot-hours / month", suggested_start: "Suggested start", weekly_growth: "Growth / week",
  r2: "Fit (R²)", weeks_to_sla: "Weeks until SLA margin is gone", median_delay_min: "Median delay (min)",
  failed_nights: "Failed nights", minutes_saved: "Minutes saved", share: "Share of critical path",
  median_peak: "Median peak", processes: "Processes", links: "Links", pending: "Pending review",
};

function fmt(k: string, v: unknown): string {
  if (typeof v === "number") {
    if (k === "weekly_growth" || k === "share") return `${Math.round(v * 100)}%`;
    return String(Math.round(v * 10) / 10);
  }
  return String(v);
}

/** Small trend line for a metric series (e.g. nightly duration). Not decorative: the finding is the trend. */
export function Sparkline({ values, width = 220, height = 44, label }: { values: number[]; width?: number; height?: number; label: string }) {
  if (values.length < 2) return null;
  const lo = Math.min(...values), hi = Math.max(...values);
  const x = (i: number) => (i / (values.length - 1)) * (width - 4) + 2;
  const y = (v: number) => height - 4 - ((v - lo) / Math.max(hi - lo, 1e-6)) * (height - 8);
  const d = values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  return (
    <svg className="sparkline" viewBox={`0 0 ${width} ${height}`} width={width} height={height} role="img" aria-label={label}>
      <path d={d} fill="none" stroke="var(--accent)" strokeWidth={2} strokeLinejoin="round" />
      <circle cx={x(values.length - 1)} cy={y(values[values.length - 1])} r={3} fill="var(--accent)" />
      <title>{label}: {values[0]} → {values[values.length - 1]}</title>
    </svg>
  );
}

export function FindingCard({ f, compact = false }: { f: Finding; compact?: boolean }) {
  const { openJob } = useEstate();
  const metrics = Object.entries(f.metrics).filter(([k, v]) => METRIC_LABEL[k] && v !== null && typeof v !== "object");
  const series = Array.isArray(f.metrics.series) ? (f.metrics.series as number[]) : null;
  return (
    <article className={`finding sev-${f.severity}`} data-testid="finding">
      <header className="finding-head">
        <StatusPill status={f.severity} />
        <span className="chip">{f.kind}</span>
        {f.scope === "cross" ? <span className="chip chip-accent">cross-ecosystem</span> : <VendorTag schedulerId={f.scope} full />}
        <h4>{f.title}</h4>
      </header>
      <p className="small">{f.detail}</p>
      {!compact && series && <Sparkline values={series} label="Nightly duration in minutes" />}
      {!compact && metrics.length > 0 && (
        <dl className="metrics">
          {metrics.map(([k, v]) => <div key={k}><dt>{METRIC_LABEL[k]}</dt><dd>{fmt(k, v)}</dd></div>)}
        </dl>
      )}
      <p className="small finding-rec"><b>Do this:</b> {f.recommendation}</p>
      {!compact && f.evidence.length > 0 && (
        <details className="small"><summary>Evidence ({f.evidence.length})</summary>
          <ul>{f.evidence.map((e, i) => <li key={i} className="mono">{e}</li>)}</ul>
        </details>
      )}
      <div className="finding-foot small">
        {f.job_ids.slice(0, 6).map((j) => (
          <button key={j} className="link" onClick={() => openJob(j)}>{shortJob(j).split(/[/.]/).pop()}</button>
        ))}
        {f.job_ids.length > 6 && <span className="muted">+{f.job_ids.length - 6} more</span>}
        {f.link_id && <Link className="btn btn-small" to={`/links?link=${encodeURIComponent(f.link_id)}`}>Review the link</Link>}
      </div>
    </article>
  );
}
