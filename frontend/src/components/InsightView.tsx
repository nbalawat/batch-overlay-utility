import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { Hypothesis, Impact, Insight, Recommendation, SimilarIncident } from "../api/types";
import { useEstate } from "../lib/estate";
import { pct, shortJob, vendorOf } from "../lib/format";
import { StatusPill, VendorTag } from "./ui";

export function ActionButton({ rec, subtle = false }: { rec: Recommendation; subtle?: boolean }) {
  const { pushReceipt } = useEstate();
  const navigate = useNavigate();
  const [state, setState] = useState<"idle" | "busy" | "done">("idle");
  if (!rec.action) return null;
  if (rec.action.action === "review") {
    const target = rec.action.link_id ? `/links?link=${encodeURIComponent(rec.action.link_id)}` : "/links";
    return <div className="btn-row"><button className={`btn ${subtle ? "" : "btn-primary"}`}
      onClick={() => navigate(target)}>Open link review</button></div>;
  }
  const label = subtle ? ({ rerun: "Rerun", boost_priority: "Boost priority", hold: "Hold", release: "Release" }[rec.action.action] ?? rec.action.action) : { rerun: "Approve rerun", boost_priority: "Approve boost", notify: "Send alert",
    hold: "Approve hold", release: "Approve release", kill: "Approve kill" }[rec.action.action] ?? "Approve";
  return (
    <div className="btn-row">
      <button className={`btn ${subtle ? "" : "btn-primary"}`} disabled={state !== "idle"} onClick={async () => {
        setState("busy");
        try {
          const r = await api.act({ action: rec.action!.action, job_id: rec.action!.job_id,
            process_id: rec.action!.process_id, note: rec.title });
          pushReceipt(r);
          setState("done");
        } catch { setState("idle"); }
      }}>{state === "done" ? "✓ Sent" : state === "busy" ? "Sending…" : label}</button>
    </div>
  );
}

export function ImpactBlock({ impact }: { impact: Impact }) {
  return (
    <div className="impact">
      {impact.downstream_by_scheduler && (
        <div className="impact-row">
          <span className="muted">Downstream jobs</span>
          <strong>{impact.downstream_jobs}</strong>
          {Object.entries(impact.downstream_by_scheduler).map(([s, n]) => (
            <span key={s} className="chip"><VendorTag schedulerId={s} /> {n}</span>
          ))}
        </div>
      )}
      {impact.processes.map((p) => (
        <div key={p.id} className="impact-proc">
          <StatusPill status={p.status} />
          <span className="impact-proc-name">{p.name}</span>
          <span className="muted">{p.criticality}{p.regulatory ? " · regulatory" : ""}</span>
          <span>{p.status === "done" ? `finished ${p.projected_p50}` : `projected ${p.projected_p50}`} vs SLA {p.sla}</span>
          <span className="muted">{pct(p.breach_probability)} breach</span>
        </div>
      ))}
      {impact.services.length > 0 && (
        <div className="impact-row"><span className="muted">Services</span>
          {impact.services.map((s) => <span key={s} className="chip">{s}</span>)}</div>
      )}
    </div>
  );
}

export function RootCause({ hyps }: { hyps: Hypothesis[] }) {
  const { openJob } = useEstate();
  if (!hyps.length) return <div className="muted">No upstream failures or anomalies found.</div>;
  return (
    <ol className="rca">
      {hyps.slice(0, 4).map((h, i) => (
        <li key={i} className={h.origin ? "rca-origin" : ""}>
          <div className="rca-head">
            <span className="conf">{pct(h.confidence)}</span>
            <VendorTag schedulerId={h.job_id.split("::")[0]} />
            <button className="link" onClick={() => openJob(h.job_id)}>{shortJob(h.job_id)}</button>
            {h.origin && <span className="chip chip-critical">likely origin</span>}
            {h.depth > 0 && <span className="muted">{h.depth} hops upstream</span>}
          </div>
          <div className="rca-reason">{h.reason}</div>
        </li>
      ))}
    </ol>
  );
}

export function SimilarIncidents({ items }: { items: SimilarIncident[] }) {
  if (!items.length) return <div className="muted">No similar incidents in the knowledge base.</div>;
  return (
    <div className="incidents">
      {items.slice(0, 2).map((s) => (
        <div key={s.id} className="incident">
          <div className="incident-head"><strong>{s.id}</strong><span className="muted">{s.date} · similarity {s.score} · MTTR {s.mttr_minutes}m</span></div>
          <div>{s.title}</div>
          <div className="muted small"><b>Cause:</b> {s.root_cause}</div>
          <div className="muted small"><b>Fix:</b> {s.resolution}</div>
        </div>
      ))}
    </div>
  );
}

export function InsightView({ insight }: { insight: Insight }) {
  const { openJob } = useEstate();
  return (
    <div className="insight-view">
      <div className="insight-title-row">
        <StatusPill status={insight.severity} />
        <span className="chip">{insight.type.replace("_", " ")}</span>
        {insight.scheduler_ids.map((s) => <VendorTag key={s} schedulerId={s} full />)}
      </div>
      <h2>{insight.title}</h2>
      <p className="lead">{insight.summary}</p>

      {insight.type === "sla_risk" && insight.job_ids.length > 0 && (
        <div className="section">
          <h4>Critical path across schedulers</h4>
          <div className="path">
            {insight.job_ids.map((j, i) => (
              <span key={j} className="path-step">
                {i > 0 && <span className={`path-arrow ${vendorOf(j.split("::")[0]) !== vendorOf(insight.job_ids[i - 1].split("::")[0]) ? "cross" : ""}`}>→</span>}
                <button className="path-node" style={{ ["--vc" as string]: vendorOf(j.split("::")[0]).color }} onClick={() => openJob(j)}>
                  <span className="vendor-code">{vendorOf(j.split("::")[0]).code}</span>{shortJob(j).split(/[./]/).pop()}
                </button>
              </span>
            ))}
          </div>
        </div>
      )}

      {insight.impact?.processes && (
        <div className="section"><h4>Business impact</h4><ImpactBlock impact={insight.impact} /></div>
      )}
      {insight.root_cause.length > 0 && (
        <div className="section"><h4>Root-cause hints</h4><RootCause hyps={insight.root_cause} /></div>
      )}
      {insight.similar_incidents.length > 0 && (
        <div className="section"><h4>Similar past incidents (knowledge base)</h4><SimilarIncidents items={insight.similar_incidents} /></div>
      )}
      {insight.evidence.length > 0 && (
        <div className="section"><h4>Evidence</h4><ul className="evidence">{insight.evidence.map((e, i) => <li key={i}>{e}</li>)}</ul></div>
      )}
      {insight.recommendations.length > 0 && (
        <div className="section">
          <h4>Recommended next steps <span className="muted small">(need human approval)</span></h4>
          {insight.recommendations.map((r) => (
            <div key={r.id} className="rec">
              <div><div className="rec-title">{r.title}</div><div className="muted small">{r.rationale}</div></div>
              <ActionButton rec={r} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
