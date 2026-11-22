import { Link } from "react-router-dom";
import { api } from "../api/client";
import { InsightView } from "../components/InsightView";
import { Card, Kpi, Loading, ProbabilityBar, StatusPill, VendorTag } from "../components/ui";
import { useApi } from "../lib/estate";
import { hhmm } from "../lib/format";
import { useState } from "react";

export function CommandCenter() {
  const { data, error } = useApi(api.overview);
  const [open, setOpen] = useState<string | null>(null);
  if (!data) return <Loading error={error} />;
  const k = data.kpis;
  const top = data.insights.find((i) => i.id === open) ?? null;
  return (
    <div className="page">
      <div className="scenario-banner">
        <div>
          <div className="eyebrow">Tonight's story · {data.meta.scenario.name}</div>
          <p>{data.meta.scenario.summary}</p>
        </div>
      </div>

      <div className="kpis">
        <Kpi label="Schedulers unified" value={k.schedulers} sub={`${k.jobs} jobs · ${k.history_runs.toLocaleString()} runs analysed`} />
        <Kpi label="Cross-scheduler links" value={k.cross_scheduler_links} sub={`${k.inferred_links} inferred by AI, awaiting review`} tone="accent" />
        <Kpi label="Tonight" value={`${k.succeeded} / ${k.jobs}`} sub={`${k.running} running · ${k.waiting} waiting`} />
        <Kpi label="Failures" value={k.failed} tone={k.failed ? "critical" : undefined} sub="jobs with a failed attempt" />
        <Kpi label="Anomalies" value={k.anomalies} tone={k.anomalies ? "warning" : undefined} sub="duration drift vs 30-night baseline" />
        <Kpi label="Business processes at risk" value={`${k.processes_at_risk} / ${data.processes.length}`}
          tone={k.processes_at_risk ? "critical" : "good"} sub="Monte Carlo SLA forecast" />
      </div>

      <div className="grid-2">
        <Card title="Business process health" actions={<Link to="/processes" className="link">All processes →</Link>}>
          <table className="table">
            <thead><tr><th>Process</th><th>Status</th><th>SLA</th><th>Projected</th><th>Breach risk</th><th>Runs in</th></tr></thead>
            <tbody>
              {data.processes.map((p) => (
                <tr key={p.id}>
                  <td><Link className="link" to={`/processes/${p.id}`}>{p.name}</Link>
                    <div className="muted small">{p.criticality}{p.regulatory ? " · regulatory" : ""}</div></td>
                  <td><StatusPill status={p.status} /></td>
                  <td className="mono">{p.sla}</td>
                  <td className="mono">{p.status === "done" ? "✓ done" : hhmm(p.projected_p50)}</td>
                  <td style={{ minWidth: 110 }}><ProbabilityBar p={p.breach_probability} />
                    <span className="small muted">{Math.round(p.breach_probability * 100)}%</span></td>
                  <td>{Object.keys(p.jobs_by_scheduler).map((s) => <VendorTag key={s} schedulerId={s} />)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>

        <Card title="AI insights" actions={<Link to="/insights" className="link">Open insights →</Link>}>
          <div className="insight-list">
            {data.insights.map((i) => (
              <button key={i.id} className={`insight-item ${open === i.id ? "active" : ""}`} onClick={() => setOpen(open === i.id ? null : i.id)}>
                <StatusPill status={i.severity} compact />
                <div><div className="insight-item-title">{i.title}</div><div className="muted small clamp-2">{i.summary}</div></div>
              </button>
            ))}
          </div>
        </Card>
      </div>
      {top && <Card className="mt"><InsightView insight={top} /></Card>}

      <Card title="Connected schedulers (simulated connectors)" className="mt" actions={<Link to="/connectors" className="link">Inspect native payloads →</Link>}>
        <div className="connectors">
          {data.connectors.map((c) => (
            <div key={c.id} className="connector">
              <div className="connector-head"><VendorTag vendor={c.vendor} full /><span className="chip chip-good">● {c.status}</span></div>
              <div className="connector-name">{c.name}</div>
              <div className="muted small">{c.description}</div>
              <div className="connector-stats">
                <span><b>{c.jobs}</b> jobs</span><span><b>{c.tonight.succeeded}</b> done</span>
                <span><b>{c.tonight.running}</b> running</span>
                <span className={c.failed_tonight ? "tone-text-critical" : ""}><b>{c.failed_tonight}</b> failed</span>
                <span className="tone-text-accent"><b>{c.cross_links}</b> cross links</span>
              </div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
