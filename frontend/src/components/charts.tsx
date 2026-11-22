import { useState } from "react";
import type { JobRun, TimelineRow } from "../api/types";
import { VENDORS, hhmm, mins } from "../lib/format";

const t = (iso: string) => new Date(iso).getTime();

interface Tip { x: number; y: number; lines: string[] }

function Tooltip({ tip }: { tip: Tip | null }) {
  if (!tip) return null;
  return (
    <div className="tooltip" style={{ left: tip.x + 12, top: tip.y + 12 }}>
      {tip.lines.map((l, i) => <div key={i} className={i === 0 ? "tooltip-title" : ""}>{l}</div>)}
    </div>
  );
}

/** Cross-scheduler run timeline for a process: actual, running, failed and projected work vs the SLA. */
export function ProcessGantt({ rows, now, deadline, usualEnd, onSelect }: {
  rows: TimelineRow[]; now: string; deadline: string; usualEnd: string | null; onSelect?: (id: string) => void;
}) {
  const [tip, setTip] = useState<Tip | null>(null);
  const rowH = 26, labelW = 250, width = 980, top = 28;
  const plotW = width - labelW - 16;
  const starts = rows.flatMap((r) => [r.start, ...r.failed_runs.map((f) => f.start)]).filter(Boolean) as string[];
  const ends = rows.flatMap((r) => [r.end, r.projected_end_p90, r.projected_end]).filter(Boolean) as string[];
  const lo = Math.min(...starts.map(t), t(now)) - 15 * 60e3;
  const hi = Math.max(...ends.map(t), t(deadline), t(now)) + 20 * 60e3;
  const x = (ms: number) => labelW + ((ms - lo) / (hi - lo)) * plotW;
  const height = top + rows.length * rowH + 10;
  const ticks: number[] = [];
  for (let h = Math.ceil(lo / 36e5) * 36e5; h <= hi; h += 36e5) ticks.push(h);

  return (
    <div className="chart-wrap" onMouseLeave={() => setTip(null)}>
      <svg viewBox={`0 0 ${width} ${height}`} width="100%" role="img" aria-label="Process run timeline">
        <defs>
          <pattern id="stripes" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="3" height="6" fill="rgba(255,255,255,0.22)" />
          </pattern>
        </defs>
        {ticks.map((h) => (
          <g key={h}>
            <line x1={x(h)} x2={x(h)} y1={top - 6} y2={height} className="grid-line" />
            <text x={x(h)} y={14} className="axis-label" textAnchor="middle">{`${String(new Date(h).getHours()).padStart(2, "0")}:00`}</text>
          </g>
        ))}
        {rows.map((r, i) => {
          const y = top + i * rowH;
          const v = VENDORS[r.vendor];
          const lines = [`${r.name} · ${v.label}`, `Status: ${r.status}`,
            r.start ? `Started ${hhmm(r.start)}` : "Not started", r.end ? `Ended ${hhmm(r.end)}` : "",
            r.projected_end ? `Projected end ${hhmm(r.projected_end)} (P90 ${hhmm(r.projected_end_p90)})` : "",
            `Usual duration ${mins(r.p50_min)}`, r.failed_attempts ? `${r.failed_attempts} failed attempt(s)` : "",
            r.critical ? "On the critical path" : ""].filter(Boolean);
          const projStart = r.status === "running" ? t(now)
            : r.projected_end ? Math.max(t(r.projected_end) - r.p50_min * 6e4, t(now)) : null;
          return (
            <g key={r.id} className="gantt-row" onClick={() => onSelect?.(r.id)}
              onMouseMove={(e) => setTip({ x: e.nativeEvent.offsetX, y: e.nativeEvent.offsetY, lines })}>
              <rect x={0} y={y} width={width} height={rowH} className={i % 2 ? "row-alt" : "row"} />
              {r.critical && <rect x={0} y={y + 3} width={3} height={rowH - 6} fill="var(--critical)" />}
              <text x={10} y={y + 17} className="gantt-vendor" fill={v.color}>{v.code}</text>
              <text x={52} y={y + 17} className={`gantt-label ${r.critical ? "strong" : ""}`}>{r.name}</text>
              {r.failed_runs.map((f) => f.start && f.end && (
                <rect key={f.id} x={x(t(f.start))} y={y + 6} width={Math.max(x(t(f.end)) - x(t(f.start)), 3)} height={rowH - 12}
                  rx={3} fill="var(--critical)" />
              ))}
              {r.start && (
                <rect x={x(t(r.start))} y={y + 6} rx={3} height={rowH - 12}
                  width={Math.max(x(t(r.end ?? now)) - x(t(r.start)), 3)} fill={v.color} />
              )}
              {r.status === "running" && r.start && (
                <rect x={x(t(r.start))} y={y + 6} rx={3} height={rowH - 12}
                  width={Math.max(x(t(now)) - x(t(r.start)), 3)} fill="url(#stripes)" />
              )}
              {projStart != null && r.projected_end && (
                <>
                  <rect x={x(projStart)} y={y + 6} rx={3} height={rowH - 12}
                    width={Math.max(x(t(r.projected_end)) - x(projStart), 3)} fill="none" stroke={v.color}
                    strokeDasharray="4 3" strokeWidth={1.5} />
                  {r.projected_end_p90 && (
                    <line x1={x(t(r.projected_end))} x2={x(t(r.projected_end_p90))} y1={y + rowH / 2} y2={y + rowH / 2}
                      stroke={v.color} strokeWidth={1.5} opacity={0.7} />
                  )}
                </>
              )}
            </g>
          );
        })}
        {usualEnd && <line x1={x(t(usualEnd))} x2={x(t(usualEnd))} y1={top - 6} y2={height} className="ref-usual" />}
        <line x1={x(t(now))} x2={x(t(now))} y1={top - 6} y2={height} className="ref-now" />
        <text x={x(t(now)) + 4} y={top - 2} className="ref-text accent">now {hhmm(now)}</text>
        <line x1={x(t(deadline))} x2={x(t(deadline))} y1={top - 6} y2={height} className="ref-sla" />
        <text x={x(t(deadline)) + 4} y={top - 2} className="ref-text critical">SLA {hhmm(deadline)}</text>
      </svg>
      <Tooltip tip={tip} />
      <div className="legend small">
        <span className="legend-item"><span className="legend-box" style={{ background: "var(--text-2)" }} />ran</span>
        <span className="legend-item"><span className="legend-box striped" />running now</span>
        <span className="legend-item"><span className="legend-box dashed" />projected (line = P90)</span>
        <span className="legend-item"><span className="legend-box" style={{ background: "var(--critical)" }} />failed attempt</span>
        <span className="legend-item"><span className="legend-line" style={{ background: "var(--text-3)" }} />usual finish</span>
      </div>
    </div>
  );
}

/** Duration per night for one job, with its P50 reference. Single series, so no legend box. */
export function RunHistoryChart({ runs, p50 }: { runs: JobRun[]; p50: number }) {
  const [tip, setTip] = useState<Tip | null>(null);
  const data = runs.filter((r) => r.duration_s != null || r.status === "running");
  if (!data.length) return <div className="muted">No runs yet.</div>;
  const w = 560, h = 140, padL = 34, padB = 18;
  const vals = data.map((r) => (r.duration_s ?? 0) / 60);
  const max = Math.max(...vals, p50 * 1.3, 1);
  const bw = (w - padL) / data.length;
  const y = (m: number) => h - padB - (m / max) * (h - padB - 8);
  return (
    <div className="chart-wrap" onMouseLeave={() => setTip(null)}>
      <svg viewBox={`0 0 ${w} ${h}`} width="100%" role="img" aria-label="Run duration history">
        {[0, max / 2, max].map((m) => (
          <g key={m}><line x1={padL} x2={w} y1={y(m)} y2={y(m)} className="grid-line" />
            <text x={padL - 4} y={y(m) + 3} className="axis-label" textAnchor="end">{Math.round(m)}</text></g>
        ))}
        {data.map((r, i) => {
          const m = (r.duration_s ?? 0) / 60;
          const fill = r.status === "failed" ? "var(--critical)" : m > p50 * 1.5 ? "var(--warning)" : "var(--series-neutral)";
          return (
            <rect key={r.id} x={padL + i * bw + 1} y={y(m)} width={Math.max(bw - 2, 2)} height={Math.max(h - padB - y(m), 1)}
              rx={2} fill={fill}
              onMouseMove={(e) => setTip({ x: e.nativeEvent.offsetX, y: e.nativeEvent.offsetY, lines: [
                `${r.business_date} · attempt ${r.attempt}`, `${r.status}${r.error_code ? ` (${r.error_code})` : ""}`,
                `${mins(m)}`] })} />
          );
        })}
        <line x1={padL} x2={w} y1={y(p50)} y2={y(p50)} className="ref-usual" />
        <text x={w - 2} y={y(p50) - 4} className="axis-label" textAnchor="end">P50 {mins(p50)}</text>
        <text x={padL} y={h - 4} className="axis-label">{data[0].business_date}</text>
        <text x={w} y={h - 4} className="axis-label" textAnchor="end">{data[data.length - 1].business_date}</text>
      </svg>
      <Tooltip tip={tip} />
    </div>
  );
}

/** SLA slack per night (positive = finished early). Bars above/below a zero line, labelled met/missed. */
export function SlackHistoryChart({ history }: { history: { business_date: string; end: string; slack_min: number }[] }) {
  const [tip, setTip] = useState<Tip | null>(null);
  if (!history.length) return null;
  const w = 560, h = 120, padL = 34;
  const ext = Math.max(...history.map((d) => Math.abs(d.slack_min)), 10);
  const mid = h / 2;
  const sy = (m: number) => mid - (m / ext) * (mid - 10);
  const bw = (w - padL) / history.length;
  return (
    <div className="chart-wrap" onMouseLeave={() => setTip(null)}>
      <svg viewBox={`0 0 ${w} ${h}`} width="100%" role="img" aria-label="SLA slack history">
        <line x1={padL} x2={w} y1={mid} y2={mid} className="axis-line" />
        <text x={padL - 4} y={sy(ext) + 3} className="axis-label" textAnchor="end">+{Math.round(ext)}</text>
        <text x={padL - 4} y={sy(-ext) + 3} className="axis-label" textAnchor="end">−{Math.round(ext)}</text>
        {history.map((d, i) => (
          <rect key={d.business_date} x={padL + i * bw + 1} width={Math.max(bw - 2, 2)}
            y={Math.min(sy(d.slack_min), mid)} height={Math.max(Math.abs(sy(d.slack_min) - mid), 1)} rx={2}
            fill={d.slack_min >= 0 ? "var(--series-neutral)" : "var(--critical)"}
            onMouseMove={(e) => setTip({ x: e.nativeEvent.offsetX, y: e.nativeEvent.offsetY, lines: [
              d.business_date, `Finished ${hhmm(d.end)}`, d.slack_min >= 0 ? `Met SLA with ${mins(d.slack_min)} to spare`
                : `Missed SLA by ${mins(-d.slack_min)}`] })} />
        ))}
      </svg>
      <Tooltip tip={tip} />
      <div className="legend small">
        <span className="legend-item"><span className="legend-box" style={{ background: "var(--series-neutral)" }} />met (minutes to spare)</span>
        <span className="legend-item"><span className="legend-box" style={{ background: "var(--critical)" }} />missed</span>
      </div>
    </div>
  );
}
