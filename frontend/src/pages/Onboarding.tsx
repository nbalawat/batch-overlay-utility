import { useState } from "react";
import { ApiError, api } from "../api/client";
import type { ImportResult } from "../api/types";
import { Card, Kpi, Loading, StatusPill, VendorTag } from "../components/ui";
import { useApi } from "../lib/estate";

const VENDORS: [string, string][] = [["control-m", "Control-M (Automation API JSON)"], ["autosys", "AutoSys (JIL)"],
  ["airflow", "Airflow (REST JSON)"], ["azure-data-factory", "Azure Data Factory (management API JSON)"]];

function Sandbox() {
  const { data: samples } = useApi(api.samples);
  const [vendor, setVendor] = useState("autosys");
  const [content, setContent] = useState("");
  const [sid, setSid] = useState("new-scheduler");
  const [name, setName] = useState("New scheduler");
  const [res, setRes] = useState<ImportResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run() {
    setBusy(true); setErr(null); setRes(null);
    try { setRes(await api.importSandbox({ vendor, content, scheduler_id: sid, name })); }
    catch (e) { setErr(e instanceof ApiError ? e.detail : String(e)); }
    finally { setBusy(false); }
  }
  async function readFile(f: File | undefined) { if (f) setContent(await f.text()); }

  return (
    <Card title="Try an export" className="mt">
      <p className="muted small">Paste or upload a scheduler export. The real adapter for that dialect parses it; nothing is added to
        the estate. You see what was understood, what looks wrong, and which links to the live estate the overlay would propose.</p>
      <div className="toolbar">
        <span className="small muted">Samples:</span>
        {samples?.map((s) => (
          <button key={s.id} className="btn btn-small" data-testid={`sample-${s.id}`} onClick={() => {
            setVendor(s.vendor); setContent(s.content); setSid(s.scheduler_id); setName(s.name); setRes(null); setErr(null);
          }}>{s.name}</button>
        ))}
      </div>
      <div className="sandbox-form">
        <label>Dialect <select value={vendor} onChange={(e) => setVendor(e.target.value)}>
          {VENDORS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
        <label>Scheduler id <input value={sid} onChange={(e) => setSid(e.target.value)} /></label>
        <label>Name <input value={name} onChange={(e) => setName(e.target.value)} /></label>
        <label className="file-pick">Upload <input type="file" accept=".jil,.json,.txt" onChange={(e) => readFile(e.target.files?.[0])} /></label>
      </div>
      <textarea className="code-input mono" rows={12} value={content} onChange={(e) => setContent(e.target.value)}
        placeholder="Paste JIL or JSON here" aria-label="Scheduler export" />
      <div className="btn-row"><button className="btn btn-primary" disabled={busy || !content.trim()} onClick={run} data-testid="analyse">
        {busy ? "Analysing…" : "Analyse"}</button></div>
      {err && <div className="tone-text-critical" role="alert">{err}</div>}
      {res && (
        <div className="sandbox-result" data-testid="sandbox-result">
          <div className="kpis">
            <Kpi label="Jobs understood" value={res.jobs.length} />
            <Kpi label="Internal dependencies" value={res.dependencies.length} />
            <Kpi label="Graph" value={res.graph.nodes} sub={`nodes, ${res.graph.edges} relations`} />
            <Kpi label="Links to the live estate" value={res.proposed_links.length} tone="accent" />
            <Kpi label="Problems" value={res.checks.length} tone={res.checks.length ? "warning" : undefined} />
          </div>
          {res.proposed_links.length > 0 && (
            <>
              <h4 className="mt">Links the overlay would propose</h4>
              <ul className="small">
                {res.proposed_links.map((p, i) => (
                  <li key={i}><VendorTag schedulerId={p.source.scheduler_id} /> <b>{p.source.name}</b> → <b>{p.target.name}</b>
                    {" "}({Math.round(p.probability * 100)}%, {p.direction}): <span className="muted">{p.evidence.detail}</span></li>
                ))}
              </ul>
            </>
          )}
          {res.checks.length > 0 && (
            <>
              <h4 className="mt">Problems in the export</h4>
              <ul className="small">{res.checks.map((c, i) => <li key={i}><StatusPill status={c.severity} compact /> {c.job}: {c.message}</li>)}</ul>
            </>
          )}
          <h4 className="mt">Jobs</h4>
          <table className="table small">
            <thead><tr><th>Job</th><th>Container</th><th>Schedule</th><th>Host</th><th>Owner</th><th>Reads</th><th>Writes</th></tr></thead>
            <tbody>{res.jobs.map((j) => (
              <tr key={j.id}><td className="mono">{j.name}</td><td>{j.container}</td><td>{j.schedule ?? "—"}</td><td>{j.host ?? "—"}</td>
                <td>{j.team ?? "—"}</td><td className="mono">{j.consumes.join(", ") || "—"}</td><td className="mono">{j.produces.join(", ") || "—"}</td></tr>
            ))}</tbody>
          </table>
          <h4 className="mt">Next steps</h4>
          <ol className="small">{res.next_steps.map((n) => <li key={n}>{n}</li>)}</ol>
        </div>
      )}
    </Card>
  );
}

export function OnboardingPage() {
  const { data, error } = useApi(api.onboarding);
  if (!data) return <Loading error={error} />;
  const t = data.totals;
  return (
    <div className="page">
      <h1>Onboarding</h1>
      <p className="muted">Connecting a scheduler is read-only and needs no agents on the client's estate: a definitions export or API,
        run history, and read access to the job code. Everything after that is automatic and repeats on every sync.</p>
      <div className="pipeline" data-testid="pipeline">
        {data.stages.map((s, i) => (
          <div key={s.id} className="stage"><div className="stage-n">{i + 1}</div><div><b>{s.title}</b><div className="muted small">{s.detail}</div></div></div>
        ))}
      </div>
      <div className="kpis mt">
        <Kpi label="Job definitions" value={t.definitions} />
        <Kpi label="Run records" value={t.runs.toLocaleString()} />
        <Kpi label="Source files mined" value={t.source_files} />
        <Kpi label="Facts found in code" value={t.mined_facts} />
      </div>
      <Card title="Connectors" className="mt">
        <table className="table small">
          <thead><tr><th>Scheduler</th><th>Definitions</th><th>Declared deps</th><th>Runs</th><th>Code location</th><th>Files</th><th>Facts</th><th>Ingest</th><th>Mining</th></tr></thead>
          <tbody>{data.connectors.map((c) => (
            <tr key={c.scheduler_id}><td><VendorTag vendor={c.vendor} /> {c.name}</td><td>{c.definitions}</td><td>{c.declared_dependencies}</td>
              <td>{c.runs}</td><td className="mono">{c.source_repo}</td><td>{c.source_files}</td><td>{c.mined_facts}</td>
              <td>{c.ingest_ms} ms</td><td>{c.mine_ms} ms</td></tr>
          ))}</tbody>
        </table>
      </Card>
      <Sandbox />
    </div>
  );
}
