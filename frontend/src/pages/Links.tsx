import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { LinkCard, LinkState, Person } from "../api/types";
import { Card, Loading, VendorTag } from "../components/ui";
import { useApi, useEstate } from "../lib/estate";

const STATE_LABEL: Record<LinkState, string> = {
  proposed: "Proposed", in_review: "In review", needs_info: "Needs information", approved: "Approved", rejected: "Rejected",
};
const TABS: [string, string][] = [["mine", "My queue"], ["open", "All open"], ["needs_info", "Needs information"],
  ["approved", "Approved"], ["rejected", "Rejected"], ["", "Everything"]];

function StateChip({ s }: { s: LinkState }) {
  const tone = { proposed: "chip-accent", in_review: "chip-warning", needs_info: "chip-warning", approved: "chip-good", rejected: "chip-critical" }[s];
  return <span className={`chip ${tone}`}>{STATE_LABEL[s]}</span>;
}

function Ends({ c }: { c: LinkCard }) {
  return (
    <div className="xlink-ends">
      <VendorTag vendor={c.source.vendor} /><span className="mono">{c.source.name}</span>
      <span className="arrow">→</span>
      <VendorTag vendor={c.target.vendor} /><span className="mono">{c.target.name}</span>
    </div>
  );
}

export function PersonaPicker({ people }: { people: Person[] }) {
  const { person, setPerson } = useEstate();
  return (
    <label className="persona">
      <span className="muted small">Viewing as</span>
      <select value={person} onChange={(e) => setPerson(e.target.value)} data-testid="persona">
        {people.map((p) => (
          <option key={p.id} value={p.id}>{p.name}, {p.team_name}{p.waiting ? ` (${p.waiting} to review)` : ""}</option>
        ))}
      </select>
    </label>
  );
}

function Decision({ c, me, onDone }: { c: LinkCard; me: Person | undefined; onDone: (c: LinkCard) => void }) {
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { setComment(""); setErr(null); }, [c.id]);
  if (!me) return null;
  const owner = c.required.some((r) => r.team === me.team);
  const mineDone = c.required.find((r) => r.team === me.team)?.approved;
  const closed = c.state === "approved" || c.state === "rejected";
  async function decide(decision: string) {
    setBusy(true); setErr(null);
    try { onDone(await api.review(c.id, { person: me!.id, decision, comment })); setComment(""); }
    catch (e) { setErr(e instanceof ApiError ? e.detail : String(e)); }
    finally { setBusy(false); }
  }
  return (
    <div className="decision" data-testid="decision">
      {!owner && !me.governance && (
        <p className="muted small">{me.name} is not on an owning team for this link. Only {c.required.map((r) => r.name).join(" and ")} can decide.
          {" "}You can still comment.</p>
      )}
      {me.governance && <p className="muted small">As the Batch CoE, {me.name} can reopen decisions but not approve on a team's behalf.</p>}
      <textarea placeholder="Comment (required to reject or ask a question)" value={comment} onChange={(e) => setComment(e.target.value)}
        aria-label="Review comment" rows={3} />
      <div className="btn-row">
        {owner && !closed && !mineDone && <button className="btn btn-primary" disabled={busy} onClick={() => decide("approve")}>Approve</button>}
        {owner && !closed && <button className="btn" disabled={busy} onClick={() => decide("needs_info")}>Ask a question</button>}
        {owner && !closed && <button className="btn btn-danger" disabled={busy} onClick={() => decide("reject")}>Reject</button>}
        <button className="btn" disabled={busy || !comment.trim()} onClick={() => decide("comment")}>Comment</button>
        {me.governance && closed && <button className="btn" disabled={busy} onClick={() => decide("reopen")}>Reopen</button>}
      </div>
      {err && <div className="tone-text-critical small" role="alert">{err}</div>}
    </div>
  );
}

function LinkDetail({ id, me, onChanged }: { id: string; me: Person | undefined; onChanged: () => void }) {
  const { openJob } = useEstate();
  const [c, setC] = useState<LinkCard | null>(null);
  const { data } = useApi(() => api.link(id), [id]);
  useEffect(() => { setC(data); }, [data]);
  if (!c) return <Loading />;
  const race = c.race_nights;
  return (
    <div className="link-detail" data-testid="link-detail">
      <div className="title-row"><Ends c={c} /><StateChip s={c.state} /></div>
      <div className="link-prob">
        <div className="link-prob-value">{Math.round(c.probability * 100)}%</div>
        <div className="muted small">probability the link is real, combining {c.evidence.length} independent pieces of evidence
          {c.fast_track && " · fast-tracked: definitions match, only the consuming team needs to approve"}</div>
      </div>
      <div className="btn-row small">
        <button className="link" onClick={() => openJob(c.source.id)}>{c.source.name}</button> in {c.source.container} ({c.source.vendor_label}, {c.source.team_name ?? "no owner"})
        <span className="arrow">→</span>
        <button className="link" onClick={() => openJob(c.target.id)}>{c.target.name}</button> in {c.target.container} ({c.target.vendor_label}, {c.target.team_name ?? "no owner"})
        {c.target.scheduled_time && <span className="muted"> · starts {c.target.scheduled_time} on its own clock</span>}
      </div>

      <h4 className="mt">Evidence</h4>
      <ul className="evidence-list">
        {c.evidence.map((e, i) => (
          <li key={i}>
            <div className="ev-head"><span className="chip mono">{e.kind}</span>
              <span className="ev-weight" title={`weight ${e.weight}`}><span style={{ width: `${e.weight * 100}%` }} /></span>
              <span className="muted small">{e.source}</span></div>
            <div className="small">{e.detail}</div>
          </li>
        ))}
      </ul>

      {race && race.nights > 0 && (
        <p className={`small ${race.races ? "tone-text-critical" : "muted"}`}>
          {race.races ? `On ${race.races} of ${race.nights} nights ${c.target.name} started before ${c.source.name} finished (${race.dates.join(", ")}).`
            : `In all ${race.nights} nights ${c.target.name} started after ${c.source.name} finished.`}
        </p>
      )}

      <h4 className="mt">Sign-off</h4>
      <div className="signoff">
        {c.required.map((r) => (
          <div key={r.team} className={`signoff-team ${r.approved ? "ok" : ""}`}>
            <div><b>{r.approved ? "✓" : "○"} {r.name}</b></div>
            <div className="muted small">{r.approved && r.approval ? `${r.approval.name}, ${r.approval.at.slice(0, 10)}${r.approval.comment ? `: “${r.approval.comment}”` : ""}`
              : `Waiting on ${r.members.map((m) => m.name).join(", ")}`}</div>
          </div>
        ))}
      </div>

      {c.impact && c.impact.length > 0 && (
        <>
          <h4 className="mt">If approved</h4>
          <ul className="small">{c.impact.map((p) => (
            <li key={p.process_id}><b>{p.name}</b> gains {p.jobs_gained} upstream job(s) in its forecast and alerts: {p.jobs.join(", ")}</li>
          ))}</ul>
        </>
      )}

      <Decision c={c} me={me} onDone={(n) => { setC(n); onChanged(); }} />

      <h4 className="mt">History</h4>
      <ol className="history">
        {(c.history ?? []).slice().reverse().map((h, i) => (
          <li key={i}><span className="mono small">{h.at.slice(0, 16).replace("T", " ")}</span> <b>{h.actor_name ?? h.actor}</b> {h.event.replace("_", " ")}
            {h.detail && <span className="muted">: {h.detail}</span>}</li>
        ))}
      </ol>
    </div>
  );
}

export function Links() {
  const [params, setParams] = useSearchParams();
  const { person, refresh } = useEstate();
  const [tab, setTab] = useState(params.get("link") ? "" : "mine");
  const [tick, setTick] = useState(0);
  const { data: people } = useApi(api.people, [tick]);
  const me = people?.find((p) => p.id === person);
  const query = tab === "mine" ? { person, state: me?.governance ? "open" : undefined } : { state: tab || undefined };
  const { data, error } = useApi(() => api.links(query), [tab, person, tick]);
  const sel = params.get("link") ?? data?.links[0]?.id ?? null;
  return (
    <div className="page">
      <div className="title-row">
        <h1>Link review</h1>
        {people && <PersonaPicker people={people} />}
      </div>
      <p className="muted">The overlay recommends links between jobs from definitions, code, queues, events, timing and incidents,
        and scores each one. Nobody's lineage changes until the owning teams agree.</p>
      {data && (
        <div className="kpis">
          {(Object.keys(STATE_LABEL) as LinkState[]).map((s) => <div key={s} className="kpi"><div className="kpi-label">{STATE_LABEL[s]}</div><div className="kpi-value">{data.counts[s]}</div></div>)}
        </div>
      )}
      <div className="tabs">{TABS.map(([k, l]) => (
        <button key={l} className={`tab ${tab === k ? "active" : ""}`} onClick={() => { setTab(k); setParams({}); }}>{l}</button>
      ))}</div>
      {!data ? <Loading error={error} /> : (
        <div className="grid-side-main">
          <Card>
            <div className="insight-list" data-testid="link-list">
              {data.links.length === 0 && <div className="muted">{tab === "mine" ? `Nothing waiting for ${me?.name ?? "you"}.` : "No links here."}</div>}
              {data.links.map((c) => (
                <button key={c.id} className={`insight-item ${sel === c.id ? "active" : ""}`} onClick={() => setParams({ link: c.id })}>
                  <div className="link-pct">{Math.round(c.probability * 100)}%</div>
                  <div>
                    <Ends c={c} />
                    <div className="small"><StateChip s={c.state} /> <span className="muted">{c.kinds.join(", ")}</span></div>
                  </div>
                </button>
              ))}
            </div>
            <div className="policy small muted mt">
              <b>Review policy</b>
              <ul>{data.policy.map((p) => <li key={p}>{p}</li>)}</ul>
            </div>
          </Card>
          <Card>{sel ? <LinkDetail id={sel} me={me} onChanged={() => { setParams({ link: sel }); setTick((t) => t + 1); refresh(); }} /> : <div className="muted">Pick a link.</div>}</Card>
        </div>
      )}
    </div>
  );
}
