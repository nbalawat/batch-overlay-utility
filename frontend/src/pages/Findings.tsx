import { useState } from "react";
import { api } from "../api/client";
import { FindingCard } from "../components/FindingCard";
import { Card, Kpi, Loading } from "../components/ui";
import { useApi } from "../lib/estate";
import { vendorOf } from "../lib/format";

const KINDS: [string, string, string][] = [
  ["static", "Static", "What the definitions, the code and the links say, before anything runs."],
  ["runtime", "Runtime", "What 30 nights of run history say about how the estate behaves and where to improve."],
];

export function Findings() {
  const [kind, setKind] = useState("static");
  const [scope, setScope] = useState("");
  const [category, setCategory] = useState("");
  const [severity, setSeverity] = useState("");
  const { data, error } = useApi(() => api.findings({ kind, scope, category, severity }), [kind, scope, category, severity]);
  if (!data) return <Loading error={error} />;
  const s = data.summary;
  const cats = s.categories.filter((c) => c.kind === kind);
  return (
    <div className="page">
      <h1>Findings</h1>
      <p className="muted">Every finding names the jobs, the evidence (file and line, or the nights it happened) and what to do.</p>
      <div className="kpis">
        <Kpi label="Static" value={s.by_kind.static ?? 0} />
        <Kpi label="Runtime" value={s.by_kind.runtime ?? 0} />
        <Kpi label="High" value={s.by_severity.high} tone={s.by_severity.high ? "critical" : undefined} />
        <Kpi label="Medium" value={s.by_severity.medium} />
        <Kpi label="Cross-ecosystem" value={s.by_scope.cross ?? 0} />
      </div>
      <div className="tabs">{KINDS.map(([k, l]) => (
        <button key={k} className={`tab ${kind === k ? "active" : ""}`} onClick={() => { setKind(k); setCategory(""); }}>{l}</button>
      ))}</div>
      <p className="muted small">{KINDS.find(([k]) => k === kind)?.[2]}</p>
      <div className="toolbar">
        <label>Ecosystem <select value={scope} onChange={(e) => setScope(e.target.value)} data-testid="finding-scope">
          <option value="">All</option>
          {Object.keys(s.by_scope).map((sc) => <option key={sc} value={sc}>{sc === "cross" ? "Cross-ecosystem" : vendorOf(sc)?.label ?? sc}</option>)}
        </select></label>
        <label>Severity <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
          <option value="">All</option>{["high", "medium", "low", "info"].map((v) => <option key={v}>{v}</option>)}
        </select></label>
      </div>
      <div className="grid-side-main">
        <Card title="Categories">
          <div className="insight-list">
            <button className={`insight-item ${category === "" ? "active" : ""}`} onClick={() => setCategory("")}>All categories</button>
            {cats.map((c) => (
              <button key={c.category} className={`insight-item ${category === c.category ? "active" : ""}`} onClick={() => setCategory(c.category)}>
                <span className="chip">{c.count}</span><span>{c.title}</span>
              </button>
            ))}
          </div>
        </Card>
        <div className="findings" data-testid="findings">
          {data.findings.length === 0 && <Card><div className="muted">Nothing matches.</div></Card>}
          {data.findings.map((f) => <FindingCard key={f.id} f={f} />)}
        </div>
      </div>
    </div>
  );
}
