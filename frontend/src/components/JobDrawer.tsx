import { api } from "../api/client";
import type { JobDetail } from "../api/types";
import { useApi, useEstate } from "../lib/estate";
import { hhmm, mins, shortJob } from "../lib/format";
import { RunHistoryChart } from "./charts";
import { ActionButton, ImpactBlock, RootCause } from "./InsightView";
import { StatusPill, VendorTag } from "./ui";

function DepList({ title, items }: { title: string; items: JobDetail["upstream"] }) {
  const { openJob } = useEstate();
  return (
    <div className="section">
      <h4>{title}</h4>
      {!items.length && <div className="muted">None</div>}
      {items.map(({ dependency: d, job }) => (
        <div key={d.id} className="dep">
          <VendorTag vendor={job.vendor} />
          <button className="link" onClick={() => openJob(job.id)}>{shortJob(job.id)}</button>
          <StatusPill status={job.status} compact />
          {d.cross_scheduler && <span className="chip chip-accent">cross-scheduler</span>}
          <span className="muted small">{d.origin}{d.origin !== "declared" ? ` · ${Math.round(d.confidence * 100)}%` : ""}
            {d.artifact ? ` · ${d.artifact}` : ""}</span>
        </div>
      ))}
    </div>
  );
}

export function JobDrawer() {
  const { jobId, openJob } = useEstate();
  const { data: job } = useApi(() => (jobId ? api.job(jobId) : Promise.resolve(null)), [jobId]);
  if (!jobId) return null;
  const def = job?.definition;
  return (
    <aside className="drawer" aria-label="Job detail">
      <button className="drawer-close" onClick={() => openJob(null)} aria-label="Close">✕</button>
      {!job ? <div className="loading">Loading…</div> : (
        <>
          <div className="insight-title-row"><VendorTag vendor={job.vendor} full /><StatusPill status={job.status} />
            {job.anomalous && <span className="chip chip-warning">anomalous duration</span>}</div>
          <h2>{job.name}</h2>
          <div className="muted mono small">{job.id}</div>
          <div className="facts">
            <div><span>Container</span>{job.container}</div>
            <div><span>Owner</span>{def?.owner ?? "—"}</div>
            <div><span>Runs on</span>{def?.host ?? "—"}</div>
            <div><span>Schedule</span>{def?.schedule ?? "—"}</div>
            <div><span>Tonight</span>{job.start ? `${hhmm(job.start)} → ${job.end ? hhmm(job.end) : "running"}` : "not started"}</div>
            <div><span>Projected end</span>{job.projected_end ? `${hhmm(job.projected_end)} (P90 ${hhmm(job.projected_end_p90)})` : "—"}</div>
            <div><span>Usual duration</span>{mins(job.baseline.p50)} (P95 {mins(job.baseline.p95)})</div>
            <div><span>30-night failure rate</span>{Math.round(job.baseline.failure_rate * 100)}%</div>
          </div>
          {(def?.produces.length || def?.consumes.length) ? (
            <div className="section"><h4>Artifacts (normalised)</h4>
              {def?.consumes.map((a) => <div key={a.raw} className="small mono">reads&nbsp; {a.raw} <span className="muted">→ {a.canonical}</span></div>)}
              {def?.produces.map((a) => <div key={a.raw} className="small mono">writes {a.raw} <span className="muted">→ {a.canonical}</span></div>)}
            </div>) : null}
          <div className="section"><h4>Duration, last {job.runs.length} runs</h4><RunHistoryChart runs={job.runs} p50={job.baseline.p50} /></div>
          <DepList title="Upstream" items={job.upstream} />
          <DepList title="Downstream" items={job.downstream} />
          {job.impact.processes.length > 0 && <div className="section"><h4>Business impact</h4><ImpactBlock impact={job.impact} /></div>}
          {(job.status === "failed" || job.failed_attempts > 0 || job.anomalous || job.status === "waiting") && (
            <div className="section"><h4>Root-cause hints</h4><RootCause hyps={job.root_cause} /></div>
          )}
          <div className="section"><h4>Operator actions <span className="muted small">(translated to {job.vendor} commands)</span></h4>
            <div className="btn-row wrap">
              {["rerun", "hold", "release", "boost_priority"].map((a) => (
                <ActionButton key={a} subtle rec={{ id: a, title: `${a} ${job.name}`, rationale: "", action: { action: a, job_id: job.id } }} />
              ))}
            </div>
          </div>
        </>
      )}
    </aside>
  );
}
