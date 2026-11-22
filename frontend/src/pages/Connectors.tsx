import { useState } from "react";
import { api } from "../api/client";
import { Card, Loading, StatusPill, VendorTag } from "../components/ui";
import { useApi, useEstate } from "../lib/estate";
import { hhmm } from "../lib/format";

export function Connectors() {
  const { data: conns, error } = useApi(api.connectors);
  const [sel, setSel] = useState("ctm-prd");
  const [view, setView] = useState<"definitions" | "runs">("definitions");
  const { data: native } = useApi(() => api.native(sel), [sel]);
  const { data: jobs } = useApi(() => api.jobs({ scheduler: sel }), [sel]);
  const { meta, openJob } = useEstate();
  if (!conns) return <Loading error={error} />;
  const raw = native ? (view === "definitions" ? native.definitions : native.runs) : null;
  return (
    <div className="page">
      <h1>Connectors</h1>
      <p className="muted">Every scheduler plugs in through the same adapter contract: a read-only client (simulated
        here, the vendor's REST API or CLI at a client) plus a translator into the unified model. Registered
        adapters: {meta?.adapters_registered.join(", ")}. Adding AWS Step Functions, Cloud Composer, Tidal or
        Stonebranch means adding one adapter. Nothing else changes.</p>
      <div className="tabs">
        {conns.map((c) => (
          <button key={c.id} className={`tab ${sel === c.id ? "active" : ""}`} onClick={() => setSel(c.id)}>
            <VendorTag vendor={c.vendor} /> {c.name}
          </button>
        ))}
      </div>
      <div className="grid-2">
        <Card title="What the scheduler sends (native)" actions={
          <div className="tabs small">
            <button className={`tab ${view === "definitions" ? "active" : ""}`} onClick={() => setView("definitions")}>Definitions</button>
            <button className={`tab ${view === "runs" ? "active" : ""}`} onClick={() => setView("runs")}>Tonight's runs</button>
          </div>}>
          <pre className="code">{raw == null ? "Loading…" : typeof raw === "string" ? raw : JSON.stringify(raw, null, 2)}</pre>
        </Card>
        <Card title={`What the overlay sees (unified model) · ${jobs?.length ?? 0} jobs`}>
          <table className="table small">
            <thead><tr><th>Job</th><th>Kind</th><th>Status</th><th>Start</th><th>End / ETA</th><th>Processes</th></tr></thead>
            <tbody>
              {jobs?.map((j) => (
                <tr key={j.id} className="clickable" onClick={() => openJob(j.id)}>
                  <td><div className="mono">{j.name}</div><div className="muted">{j.container}</div></td>
                  <td>{j.kind}</td><td><StatusPill status={j.status} /></td>
                  <td className="mono">{hhmm(j.start)}</td>
                  <td className="mono">{j.end ? hhmm(j.end) : j.projected_end ? `~${hhmm(j.projected_end)}` : "—"}</td>
                  <td className="small">{j.processes.length}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>
    </div>
  );
}
