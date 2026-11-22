import { useMemo, useState } from "react";
import { api } from "../api/client";
import { GraphLegend, LineageGraph } from "../components/LineageGraph";
import { Card, Loading, VendorTag } from "../components/ui";
import { useApi, useEstate } from "../lib/estate";
import { shortJob } from "../lib/format";

export function Lineage() {
  const [process, setProcess] = useState("");
  const [crossOnly, setCrossOnly] = useState(false);
  const { openJob } = useEstate();
  const { data: procs } = useApi(api.processes);
  const { data: graph, error } = useApi(() => api.graph(process || undefined, crossOnly), [process, crossOnly]);
  const cross = useMemo(() => graph?.edges.filter((e) => e.cross_scheduler) ?? [], [graph]);
  return (
    <div className="page">
      <h1>Cross-scheduler lineage</h1>
      <p className="muted">One graph for the whole estate. Native dependencies come from each scheduler. The links
        between schedulers are found by the overlay: shared files and datasets, name matches, and timing patterns
        in run history. No single vendor console can show these.</p>
      <div className="toolbar">
        <label>Business process&nbsp;
          <select value={process} onChange={(e) => setProcess(e.target.value)}>
            <option value="">Whole estate</option>
            {procs?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </label>
        <label className="toggle"><input type="checkbox" checked={crossOnly} onChange={(e) => setCrossOnly(e.target.checked)} />
          Only jobs with cross-scheduler links</label>
        <GraphLegend />
      </div>
      {!graph ? <Loading error={error} /> : (
        <>
          <Card><LineageGraph graph={graph} onSelect={openJob} maxHeight={760} /></Card>
          <Card title={`Cross-scheduler links (${cross.length})`} className="mt">
            <div className="xlinks">
              {cross.map((d) => (
                <div key={d.id} className={`xlink origin-${d.origin}`}>
                  <div className="xlink-ends">
                    <VendorTag schedulerId={d.source.split("::")[0]} />
                    <button className="link" onClick={() => openJob(d.source)}>{shortJob(d.source).split(/[/.]/).pop()}</button>
                    <span className="arrow">→</span>
                    <VendorTag schedulerId={d.target.split("::")[0]} />
                    <button className="link" onClick={() => openJob(d.target)}>{shortJob(d.target).split(/[/.]/).pop()}</button>
                  </div>
                  <div className="small">
                    <span className={`chip ${d.origin === "inferred" ? "chip-warning" : "chip-accent"}`}>{d.origin}</span>
                    <span className="muted"> confidence {Math.round(d.confidence * 100)}% · {d.review_state}</span>
                  </div>
                  {d.evidence.map((e, i) => <div key={i} className="muted small">• {e.detail}</div>)}
                </div>
              ))}
            </div>
          </Card>
        </>
      )}
    </div>
  );
}
