import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { KgNode, KgPaths } from "../api/types";
import { KgGraph, NODE_STYLE, ProvenanceLegend } from "../components/KgGraph";
import { Card, Loading } from "../components/ui";
import { useApi, useEstate } from "../lib/estate";

const DATA_RELATIONS = "FEEDS,READS,WRITES,PUBLISHES,TRIGGERED_BY,RUNS_ON,TRANSFERS_TO,FETCHES_FROM,CALLS,NOTIFIES";
const START = "ctm-prd::CORE_BANKING_EOD/CBK_GL_EXTRACT";
const LAYERS: [string, string][] = [
  ["", "All relations"],
  ["FEEDS", "Job dependencies"],
  ["READS,WRITES,PUBLISHES,TRIGGERED_BY", "Data"],
  ["RUNS_ON,SCHEDULED_BY", "Hosts and schedules"],
  ["TRANSFERS_TO,FETCHES_FROM,CALLS,NOTIFIES", "Communications"],
  ["OWNED_BY,BELONGS_TO,CONTAINS", "Ownership and structure"],
  ["DELIVERS,PART_OF,SUPPORTS,AFFECTED", "Business and incidents"],
];

function NodeSearch({ label, onPick, testId }: { label: string; onPick: (n: KgNode) => void; testId: string }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<KgNode[]>([]);
  useEffect(() => {
    if (q.trim().length < 2) { setHits([]); return; }
    const t = setTimeout(() => api.kgSearch(q).then(setHits).catch(() => setHits([])), 150);
    return () => clearTimeout(t);
  }, [q]);
  return (
    <div className="kg-search">
      <input aria-label={label} placeholder={label} value={q} onChange={(e) => setQ(e.target.value)} data-testid={testId} />
      {hits.length > 0 && (
        <ul className="kg-hits">
          {hits.map((h) => (
            <li key={h.id}><button onClick={() => { onPick(h); setQ(""); setHits([]); }}>
              <span className="chip mono">{NODE_STYLE[h.type]?.code ?? h.type}</span> {h.label}
              <span className="muted small"> {h.id !== h.label ? h.id : ""}</span>
            </button></li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Props({ props }: { props: Record<string, unknown> }) {
  const rows = Object.entries(props).filter(([, v]) => v !== null && v !== undefined && v !== "" && typeof v !== "object");
  if (!rows.length) return null;
  return (
    <dl className="metrics">
      {rows.slice(0, 14).map(([k, v]) => <div key={k}><dt>{k.replace(/_/g, " ")}</dt><dd className="mono">{String(v)}</dd></div>)}
    </dl>
  );
}

export function Knowledge() {
  const [params, setParams] = useSearchParams();
  const center = params.get("node") ?? START;
  const [depth, setDepth] = useState(1);
  const [layer, setLayer] = useState("");
  const [pathFrom, setPathFrom] = useState<KgNode | null>(null);
  const [pathTo, setPathTo] = useState<KgNode | null>(null);
  const [paths, setPaths] = useState<KgPaths | null>(null);
  const { openJob } = useEstate();
  const { data: onto } = useApi(api.ontology);
  const { data: sub, error } = useApi(() => api.kgNeighbourhood(center, depth, layer || undefined), [center, depth, layer]);
  const { data: detail } = useApi(() => api.kgNode(center), [center]);
  const go = (id: string) => { setParams({ node: id }); setPaths(null); };

  useEffect(() => {
    if (!pathFrom || !pathTo) return;
    // Follow the direction of work first; if nothing flows that way, look for any data or dependency connection.
    api.kgPaths(pathFrom.id, pathTo.id, true)
      .then((r) => (r.paths.length ? r : api.kgPaths(pathFrom.id, pathTo.id, false, DATA_RELATIONS)))
      .then(setPaths).catch(() => setPaths(null));
  }, [pathFrom, pathTo]);
  const pathSet = useMemo(() => paths?.paths[0] ? new Set(paths.paths[0].hops.map((h) => h.id)) : null, [paths]);
  const graph = paths?.paths.length
    ? { nodes: [...new Map(paths.paths.flatMap((p) => p.hops).map((n) => [n.id, n])).values()],
        edges: [...new Map(paths.paths.flatMap((p) => p.edges).map((e) => [e.id, e])).values()] }
    : sub;

  return (
    <div className="page">
      <h1>Knowledge graph</h1>
      <p className="muted">Rebuilt from source on every sync: scheduler definitions, mined job code, run history, the business
        catalogue, reviewed links and incidents. Every relation records where it was learned, so nothing here is maintained by hand.</p>
      {onto && (
        <div className="ontology-strip">
          <span className="muted small">{onto.stats.nodes} nodes · {onto.stats.edges} relations</span>
          {onto.nodes.map((n) => (
            <span key={n.type} className="onto-chip" style={{ ["--vc" as string]: NODE_STYLE[n.type]?.color }} title={`${n.description}. e.g. ${n.examples}`}>
              {n.type} <b>{n.count}</b>
            </span>
          ))}
        </div>
      )}
      <div className="toolbar">
        <NodeSearch label="Find a job, file, table, host, e-mail, process…" onPick={(n) => go(n.id)} testId="kg-search" />
        <label>Depth <select value={depth} onChange={(e) => setDepth(Number(e.target.value))}>
          {[1, 2, 3].map((d) => <option key={d} value={d}>{d}</option>)}</select></label>
        <label>Layer <select value={layer} onChange={(e) => setLayer(e.target.value)} data-testid="kg-layer">
          {LAYERS.map(([v, l]) => <option key={l} value={v}>{l}</option>)}</select></label>
        <ProvenanceLegend />
      </div>
      <div className="grid-main-side">
        <Card title={paths ? `Paths: ${paths.from.label} → ${paths.to.label}` : `Around ${detail?.node.label ?? center}`}
          actions={paths && <button className="btn btn-small" onClick={() => { setPaths(null); setPathFrom(null); setPathTo(null); }}>Clear path</button>}>
          {!graph ? <Loading error={error} /> : (
            <KgGraph nodes={graph.nodes} edges={graph.edges} center={paths ? undefined : center} highlight={pathSet}
              onSelect={(id) => (paths ? undefined : go(id))} />
          )}
          {sub?.truncated && !paths && <div className="muted small">Showing the first 120 nodes. Narrow the layer or depth.</div>}
          {paths && paths.paths.length === 0 && <div className="muted">No connection found.</div>}
        </Card>
        <div>
          {detail && (
            <Card title={<><span className="chip mono">{NODE_STYLE[detail.node.type]?.code}</span> {detail.node.label}</>}
              actions={detail.node.type === "Job" && <button className="btn btn-small" onClick={() => openJob(detail.node.id)}>Job detail</button>}>
              <div className="muted small mono">{detail.node.id}</div>
              <Props props={detail.node.props} />
              <div className="relations" data-testid="kg-relations">
                {detail.relations.map((r) => (
                  <div key={`${r.direction}${r.type}`} className="relation">
                    <h4>{r.direction === "in" ? "←" : "→"} {r.type.toLowerCase().replace("_", " ")} ({r.edges.length})</h4>
                    <ul>
                      {r.edges.slice(0, 12).map((e) => (
                        <li key={e.id}>
                          <button className="link" onClick={() => go(e.other.id)}>{e.other.label}</button>
                          {e.provenance.map((p) => <span key={p} className={`chip prov-${p}`}>{p}</span>)}
                          {e.refs[0] && <span className="muted small mono"> {e.refs[0]}</span>}
                        </li>
                      ))}
                      {r.edges.length > 12 && <li className="muted small">+{r.edges.length - 12} more</li>}
                    </ul>
                  </div>
                ))}
              </div>
            </Card>
          )}
          <Card title="How are two things connected?" className="mt">
            <div className="path-pick">
              <div>{pathFrom ? <span className="chip">{pathFrom.label}</span> : <NodeSearch label="From" onPick={setPathFrom} testId="path-from" />}</div>
              <div>{pathTo ? <span className="chip">{pathTo.label}</span> : <NodeSearch label="To" onPick={setPathTo} testId="path-to" />}</div>
            </div>
            {paths && <div className="muted small">{paths.directed ? "Following the flow of work" : "No flow in that direction; showing shared data, hosts or links"}</div>}
            {paths?.paths.map((p, i) => (
              <div key={i} className="small path-text" data-testid="path-result">
                {p.hops.map((h, k) => <span key={h.id}>{k > 0 && <span className="muted"> —{p.edges[k - 1].type.toLowerCase()}→ </span>}{h.label}</span>)}
              </div>
            ))}
          </Card>
          {onto && (
            <Card title="Ontology" className="mt">
              <table className="table small"><tbody>
                {onto.edges.map((e) => (
                  <tr key={e.type}><td className="mono">{e.type}</td><td className="muted">{e.source.join("/")} → {e.target.join("/")}</td><td>{e.count}</td></tr>
                ))}
              </tbody></table>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
