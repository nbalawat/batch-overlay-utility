import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { ProcessGantt, SlackHistoryChart } from "../components/charts";
import { InsightView } from "../components/InsightView";
import { GraphLegend, LineageGraph } from "../components/LineageGraph";
import { Card, Kpi, Loading, ProbabilityBar, StatusPill, VendorTag } from "../components/ui";
import { useApi, useEstate } from "../lib/estate";
import { hhmm, mins, pct } from "../lib/format";

export function ProcessList() {
  const { data, error } = useApi(api.processes);
  const nav = useNavigate();
  if (!data) return <Loading error={error} />;
  return (
    <div className="page">
      <h1>Business processes</h1>
      <p className="muted">Each process is defined once, by its outcome. The overlay pulls in every upstream job,
        whichever scheduler runs it, through the correlated lineage graph.</p>
      <div className="proc-grid">
        {data.map((p) => (
          <button key={p.id} className={`proc-card status-${p.status}`} onClick={() => nav(`/processes/${p.id}`)}>
            <div className="proc-card-head"><StatusPill status={p.status} /><span className="muted small">{p.criticality}</span></div>
            <div className="proc-card-name">{p.name}</div>
            <div className="muted small">{p.description}</div>
            <div className="proc-card-sla">
              <div><span className="muted small">SLA</span><b className="mono">{p.sla}</b></div>
              <div><span className="muted small">Projected</span><b className="mono">{p.status === "done" ? "done" : hhmm(p.projected_p50)}</b></div>
              <div><span className="muted small">Breach risk</span><b>{pct(p.breach_probability)}</b></div>
            </div>
            <ProbabilityBar p={p.breach_probability} />
            <div className="proc-card-foot">
              {Object.entries(p.jobs_by_scheduler).map(([s, n]) => <span key={s} className="chip"><VendorTag schedulerId={s} /> {n}</span>)}
              <span className="muted small">{p.jobs_done}/{p.job_count} jobs done</span>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

export function ProcessDetailPage() {
  const { id = "" } = useParams();
  const { meta, openJob } = useEstate();
  const { data: p, error } = useApi(() => api.process(id), [id]);
  if (!p || !meta) return <Loading error={error} />;
  const sla = p.insights.find((i) => i.type === "sla_risk");
  return (
    <div className="page">
      <div className="crumbs"><Link className="link" to="/processes">Business processes</Link> / {p.name}</div>
      <div className="title-row">
        <h1>{p.name}</h1><StatusPill status={p.status} />
        {p.regulatory && <span className="chip chip-warning">regulatory</span>}
      </div>
      <p className="muted">{p.description} Owner: {p.owner}. {p.sla_description}</p>

      <div className="kpis">
        <Kpi label="SLA" value={p.sla} sub={`usually done ${hhmm(p.usual_end)}`} />
        <Kpi label="Projected finish (P50)" value={p.status === "done" ? "done" : hhmm(p.projected_p50)}
          sub={`P90 ${hhmm(p.projected_p90)}`} tone={p.slack_min < 0 ? "critical" : "good"} />
        <Kpi label="Breach probability" value={pct(p.breach_probability)} tone={p.breach_probability >= 0.6 ? "critical" : p.breach_probability >= 0.2 ? "warning" : "good"}
          sub="400 Monte Carlo runs" />
        <Kpi label="Slack" value={`${p.slack_min < 0 ? "−" : "+"}${mins(Math.abs(p.slack_min))}`} sub="deadline minus P50" />
        <Kpi label="Supply chain" value={`${p.job_count} jobs`} sub={<>{Object.entries(p.jobs_by_scheduler).map(([s, n]) =>
          <span key={s} className="chip"><VendorTag schedulerId={s} /> {n}</span>)}</>} />
        <Kpi label="Services" value={p.services.length} sub={p.services.map((s) => s.name).join(" · ")} />
      </div>

      <Card title="Tonight's run across schedulers" className="mt"
        actions={<span className="muted small">Rows in dependency order. Red bar = critical path. Click a row for detail.</span>}>
        <ProcessGantt rows={p.timeline} now={meta.now} deadline={p.deadline} usualEnd={p.usual_end} onSelect={openJob} />
      </Card>

      <Card title="End-to-end lineage, one lane per scheduler (critical path highlighted)" className="mt" actions={<GraphLegend />}>
        <LineageGraph graph={p.graph} onSelect={openJob} />
      </Card>

      <div className="grid-2 mt">
        {sla ? <Card><InsightView insight={sla} /></Card> : (
          <Card title="Forecast"><p>No SLA risk detected for this process tonight.</p></Card>
        )}
        <Card title="SLA history, last 30 nights"><SlackHistoryChart history={p.history} /></Card>
      </div>
    </div>
  );
}
