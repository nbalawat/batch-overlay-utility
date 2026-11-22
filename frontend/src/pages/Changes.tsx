import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Card, Loading, VendorTag } from "../components/ui";
import { useApi, useEstate } from "../lib/estate";

export function Changes() {
  const { openJob } = useEstate();
  const { data, error } = useApi(api.changelog);
  if (!data) return <Loading error={error} />;
  return (
    <div className="page">
      <h1>What changed</h1>
      <p className="muted">Each nightly sync rebuilds the knowledge graph from the schedulers and the code, then diffs it with the
        night before. Ticket and author come from the scheduler's audit trail. When a change opens a gap, the link
        recommender proposes a fix and it goes to review.</p>
      <div className="timeline" data-testid="changelog">
        {data.map((e) => (
          <Card key={e.sync} title={<>Sync {e.sync}</>} actions={<span className="muted small">
            graph {e.nodes_before}→{e.nodes_after} nodes, {e.edges_before}→{e.edges_after} relations</span>}>
            {e.changes.map((c) => (
              <div key={c.job_id} className="change">
                <div className="title-row">
                  <div><VendorTag schedulerId={c.scheduler_id} /> <button className="link mono" onClick={() => openJob(c.job_id)}>{c.name}</button>
                    {" "}<span className={`chip ${c.kind === "added" ? "chip-good" : "chip-accent"}`}>{c.kind}</span></div>
                  {c.change && <span className="small muted">{c.change.ticket} · {c.change.author}</span>}
                </div>
                {c.change && <div className="small">{c.change.summary}</div>}
                <ul className="diff">
                  {c.details.map((d) => <li key={d} className={d.startsWith("+") ? "diff-add" : d.startsWith("−") ? "diff-del" : ""}>{d}</li>)}
                </ul>
                {c.follow_ups.filter((f) => f.state && !["approved", "rejected"].includes(f.state)).map((f) => (
                  <div key={f.link_id} className="small">⚑ Follow-up link in review ({Math.round(f.probability * 100)}%):{" "}
                    <Link to={`/links?link=${encodeURIComponent(f.link_id)}`}>{f.link_id.split("->").map((x) => x.split(/[/.:]/).pop()).join(" → ")}</Link></div>
                ))}
              </div>
            ))}
          </Card>
        ))}
      </div>
    </div>
  );
}
