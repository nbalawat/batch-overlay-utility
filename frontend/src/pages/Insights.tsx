import { useEffect, useState } from "react";
import { api } from "../api/client";
import { InsightView } from "../components/InsightView";
import { Card, Loading, StatusPill } from "../components/ui";
import { useApi, useEstate } from "../lib/estate";

const TYPES = [["", "All"], ["sla_risk", "SLA risk"], ["failure", "Failures"], ["anomaly", "Anomalies"], ["correlation", "Hidden links"]];

export function Insights() {
  const [type, setType] = useState("");
  const [sel, setSel] = useState<string | null>(null);
  const { data, error } = useApi(() => api.insights(type || undefined), [type]);
  useEffect(() => { if (data?.length && !data.find((i) => i.id === sel)) setSel(data[0].id); }, [data, sel]);
  const { receipts } = useEstate();
  const { data: audit } = useApi(api.audit, [sel, receipts]);
  if (!data) return <Loading error={error} />;
  const current = data.find((i) => i.id === sel);
  return (
    <div className="page">
      <h1>AI insights</h1>
      <div className="tabs">{TYPES.map(([k, l]) => (
        <button key={k} className={`tab ${type === k ? "active" : ""}`} onClick={() => setType(k)}>{l}</button>
      ))}</div>
      <div className="grid-side-main">
        <Card>
          <div className="insight-list">
            {data.length === 0 && <div className="muted">Nothing to report.</div>}
            {data.map((i) => (
              <button key={i.id} className={`insight-item ${sel === i.id ? "active" : ""}`} onClick={() => setSel(i.id)}>
                <StatusPill status={i.severity} compact />
                <div><div className="insight-item-title">{i.title}</div><div className="muted small clamp-2">{i.summary}</div></div>
              </button>
            ))}
          </div>
        </Card>
        <div>
          {current && <Card><InsightView insight={current} /></Card>}
          <Card title="Action log (human-in-the-loop)" className="mt">
            {!audit?.length ? <div className="muted">No actions yet. Approved actions are translated into each scheduler's native command.</div> : (
              <table className="table small">
                <thead><tr><th>At</th><th>Who</th><th>Action</th><th>Native command</th><th>Receipt</th></tr></thead>
                <tbody>{audit.map((a, i) => (
                  <tr key={i}><td className="mono">{a.at.slice(11)}</td><td>{a.actor}</td><td>{a.action}</td>
                    <td className="mono">{a.command}</td><td>{String(a.receipt?.request_id ?? (a.receipt?.accepted ? "accepted" : ""))}</td></tr>
                ))}</tbody>
              </table>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
