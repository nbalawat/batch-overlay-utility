import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { EcoJob } from "../api/types";
import { FindingCard } from "../components/FindingCard";
import { GraphLegend, LineageGraph } from "../components/LineageGraph";
import { Card, Kpi, Loading, StatusPill, VendorTag } from "../components/ui";
import { useApi, useEstate } from "../lib/estate";

export function EcosystemList() {
  const { data, error } = useApi(api.ecosystems);
  if (!data) return <Loading error={error} />;
  return (
    <div className="page">
      <h1>Ecosystems</h1>
      <p className="muted">Each scheduler as its own teams see it, translated into one vocabulary. Open one to browse its
        {" "}folders, boxes, DAGs or pipelines, its internal graph, and the links that leave it.</p>
      <div className="eco-grid">
        {data.map((e) => (
          <Link key={e.id} to={`/ecosystems/${e.id}`} className="card eco-card" data-testid="eco-card">
            <div className="eco-card-head"><VendorTag vendor={e.vendor} full /><span className="muted small">{e.environment}</span></div>
            <h3>{e.name}</h3>
            <p className="muted small clamp-2">{e.description}</p>
            <div className="eco-stats">
              <Kpi label="Jobs" value={e.jobs} sub={`${e.containers} ${e.container_kind}s`} />
              <Kpi label="Internal links" value={e.intra_links} />
              <Kpi label="Cross links" value={e.cross_links} sub={e.cross_pending ? `${e.cross_pending} in review` : "all confirmed"} />
              <Kpi label="Hosts" value={e.hosts} sub={`${e.teams} teams`} />
            </div>
            <div className="sev-row small">
              {(["high", "medium", "low", "info"] as const).map((s) => e.findings[s] > 0 && (
                <span key={s} className={`chip sev-chip-${s}`}>{e.findings[s]} {s}</span>
              ))}
              <span className="muted">findings</span>
            </div>
            <div className="muted small">{e.pipeline.source_files} source files mined · {e.pipeline.mined_facts} facts</div>
          </Link>
        ))}
      </div>
    </div>
  );
}

function ContainerTree({ containers, kind, onPick, selected }: {
  containers: { name: string; jobs: EcoJob[] }[]; kind: string; onPick: (id: string) => void; selected: string;
}) {
  const [filter, setFilter] = useState("");
  const f = filter.toLowerCase();
  return (
    <div className="tree">
      <input className="tree-filter" placeholder={`Filter ${kind}s and jobs`} value={filter} onChange={(e) => setFilter(e.target.value)} />
      {containers.map((c) => {
        const jobs = c.jobs.filter((j) => !f || j.name.toLowerCase().includes(f) || c.name.toLowerCase().includes(f));
        if (!jobs.length) return null;
        return (
          <details key={c.name} open>
            <summary><span className="mono">{c.name}</span> <span className="muted small">{kind} · {c.jobs.length}</span></summary>
            <ul>
              {jobs.map((j) => (
                <li key={j.id}>
                  <button className={`tree-job ${selected === j.id ? "active" : ""}`} onClick={() => onPick(j.id)}>
                    <StatusPill status={j.status} compact />
                    <span className="mono">{j.name}</span>
                    {j.alerting === false && <span className="chip chip-warning" title="No failure alert">silent</span>}
                    {j.unresolved_conditions.length > 0 && <span className="chip chip-critical" title={j.unresolved_conditions.join(", ")}>dead condition</span>}
                  </button>
                  <div className="muted small tree-meta">{j.schedule ?? "—"} · {j.host ?? "no host"} · {j.team ?? "no owner"}
                    {j.mined_facts > 0 && <> · {j.mined_facts} code facts</>}</div>
                </li>
              ))}
            </ul>
          </details>
        );
      })}
    </div>
  );
}

export function EcosystemDetailPage() {
  const { id = "" } = useParams();
  const { openJob } = useEstate();
  const navigate = useNavigate();
  const { data, error } = useApi(() => api.ecosystem(id), [id]);
  const [sel, setSel] = useState("");
  const highlight = useMemo(() => {
    if (!data || !sel) return null;
    const keep = new Set([sel]);
    data.graph.edges.forEach((e) => { if (e.source === sel) keep.add(e.target); if (e.target === sel) keep.add(e.source); });
    return keep;
  }, [data, sel]);
  if (!data) return <Loading error={error} />;
  const s = data.stats;
  const pick = (j: string) => { setSel(j); openJob(j); };
  return (
    <div className="page">
      <div className="crumbs small"><Link to="/ecosystems">Ecosystems</Link> / {data.name}</div>
      <h1><VendorTag vendor={data.vendor} full /> {data.name}</h1>
      <p className="muted">{data.description}</p>
      <div className="kpis">
        <Kpi label="Jobs" value={s.jobs} sub={`${s.containers} ${data.container_kind}s`} />
        <Kpi label="Internal links" value={s.intra_links} />
        <Kpi label="Links to other schedulers" value={s.boundary_links} sub={`${s.pending_boundary_links} in review`} tone={s.pending_boundary_links ? "warning" : undefined} />
        <Kpi label="Fail silently" value={s.unmonitored} tone={s.unmonitored ? "warning" : undefined} />
        <Kpi label="Dead conditions" value={s.unresolved_conditions} tone={s.unresolved_conditions ? "critical" : undefined} />
        <Kpi label="Facts mined from code" value={s.mined_facts} sub={data.pipeline.source_repo} />
      </div>
      <div className="grid-side-main mt">
        <Card title={`${data.container_kind[0].toUpperCase()}${data.container_kind.slice(1)}s and jobs`}>
          <ContainerTree containers={data.containers} kind={data.container_kind} onPick={pick} selected={sel} />
        </Card>
        <div>
          <Card title="Graph" actions={<GraphLegend />}>
            <p className="muted small">This scheduler's jobs, plus the jobs in other schedulers they connect to (in their own lanes).
              Dashed edges are recommended links still in review.</p>
            <LineageGraph graph={data.graph} onSelect={pick} highlight={highlight} maxHeight={560} />
          </Card>
          <div className="grid-2 mt">
            <Card title="Hosts">
              <table className="table small"><tbody>
                {data.hosts.map((h) => <tr key={h.host}><td className="mono">{h.host}</td><td>{h.jobs} jobs</td>
                  <td><Link to={`/knowledge?node=${encodeURIComponent(`host:${h.host}`)}`}>graph</Link></td></tr>)}
              </tbody></table>
            </Card>
            <Card title="Data it writes and reads">
              <table className="table small"><tbody>
                {data.outputs.slice(0, 8).map((o) => <tr key={`o${o.id}`}><td>writes</td><td className="mono">
                  <Link to={`/knowledge?node=${encodeURIComponent(o.id)}`}>{o.label}</Link></td><td className="muted">{o.type}</td></tr>)}
                {data.inputs.slice(0, 8).map((o) => <tr key={`i${o.id}`}><td>reads</td><td className="mono">
                  <Link to={`/knowledge?node=${encodeURIComponent(o.id)}`}>{o.label}</Link></td><td className="muted">{o.type}</td></tr>)}
              </tbody></table>
            </Card>
          </div>
          <Card title="Ask about this ecosystem" className="mt">
            <div className="suggestions">
              {data.suggested_questions.map((q) => (
                <button key={q} className="suggestion" onClick={() => navigate(`/ask?q=${encodeURIComponent(q)}`)}>{q}</button>
              ))}
            </div>
          </Card>
          <Card title={`Findings (${data.findings.length})`} className="mt">
            <div className="findings">
              {data.findings.map((f) => <FindingCard key={f.id} f={f} compact />)}
            </div>
          </Card>
          <p className="muted small">Last sync: {data.pipeline.definitions} definitions read in {data.pipeline.ingest_ms} ms,
            {" "}{data.pipeline.source_files} source files mined in {data.pipeline.mine_ms} ms.</p>
        </div>
      </div>
    </div>
  );
}
