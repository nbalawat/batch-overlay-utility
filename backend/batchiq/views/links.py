"""Link review queue: recommended links, their evidence, who must sign off, and what approval changes."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from batchiq.analysis.static import race_nights
from batchiq.core.business import BusinessMapper
from batchiq.core.graph import LineageGraph
from batchiq.linking.review import LinkState, ReviewError
from batchiq.views.common import VENDOR_LABEL, iso, jsonable

if TYPE_CHECKING:
    from batchiq.service import EstateService

# Where each kind of evidence comes from, in words a reviewer can check.
EVIDENCE_SOURCE = {
    "file-match": "Scheduler definitions: both jobs name the same file",
    "dataset-match": "Scheduler definitions: both jobs name the same dataset",
    "table-match": "Scheduler definitions: both jobs name the same table",
    "file-prefix-match": "Scheduler definitions: a file trigger matches the other job's output",
    "data-name-match": "Scheduler definitions: the dataset names match across naming conventions",
    "code-artifact-match": "Source code: one job writes what the other reads",
    "queue-match": "Source code: one job puts to a queue the other reads",
    "event-match": "Code and definitions: one job publishes the event that starts the other",
    "temporal": "Run history: the second job reliably starts just after the first ends",
    "name-similarity": "Job names only (weak)",
    "runtime-order": "Run history: order of the two jobs over 30 nights",
    "incident": "Incident knowledge base: both jobs named in the same incident",
}
OPEN = (LinkState.PROPOSED, LinkState.IN_REVIEW, LinkState.NEEDS_INFO)


def _job(svc: EstateService, jid: str) -> dict[str, Any]:
    j = svc.a.estate.jobs()[jid]
    team = j.team
    return {"id": jid, "name": j.name, "container": j.container, "scheduler_id": j.scheduler_id,
            "vendor": j.vendor.value, "vendor_label": VENDOR_LABEL[j.vendor.value], "team": team,
            "team_name": svc.directory.team_name(team) if team else None,
            "scheduled_time": j.scheduled_time.strftime("%H:%M") if j.scheduled_time else None,
            "processes": svc.a.mapper.processes_for(jid)}


def impact_if_approved(svc: EstateService, link_id: str) -> list[dict[str, Any]]:
    """Which business processes would gain which jobs if this link were confirmed."""
    a = svc.a
    deps = list(a.estate.dependencies().values())
    dep = a.estate.dependencies().get(link_id)
    if dep is None or dep.review_state == "confirmed":
        return []
    graph = LineageGraph([d if d.id != link_id else d.model_copy(update={"review_state": "confirmed"})
                          for d in deps])
    after = BusinessMapper(a.mapper.processes, graph).members
    out = []
    for pid, members in after.items():
        gained = sorted(members - a.mapper.members.get(pid, set()))
        if gained:
            out.append({"process_id": pid, "name": a.mapper.processes[pid].name, "jobs_gained": len(gained),
                        "jobs": [a.estate.jobs()[g].name for g in gained][:12]})
    return out


def link_card(svc: EstateService, link_id: str, detail: bool = False) -> dict[str, Any]:
    a = svc.a
    c, rec = svc.candidates[link_id], svc.reviews.records[link_id]
    dep = a.estate.dependencies()[link_id]
    required = [{"team": t, "name": svc.directory.team_name(t), "approved": t in rec.approvals,
                 "approval": jsonable(rec.approvals.get(t)),
                 "members": [p.__dict__ for p in svc.directory.members(t)]} for t in rec.required]
    out: dict[str, Any] = {
        "id": link_id, "source": _job(svc, c.source), "target": _job(svc, c.target),
        "probability": c.probability, "state": rec.state.value, "dependency_state": dep.review_state,
        "cross_scheduler": dep.cross_scheduler, "artifact": c.artifact, "definitional": c.definitional,
        "fast_track": len(rec.required) == 1 and c.definitional, "kinds": c.kinds,
        "evidence": [{**e.model_dump(), "source": EVIDENCE_SOURCE.get(e.kind, e.kind)} for e in c.evidence],
        "required": required, "proposed_at": iso(rec.proposed_at),
        "last_event": jsonable(rec.history[-1]) if rec.history else None,
        "findings": [f.id for f in a.findings if f.link_id == link_id]}
    if detail:
        races, nights, dates = race_nights(a.inputs, c.source, c.target) if a.inputs else (0, 0, [])
        out |= {"history": jsonable(rec.history), "impact": impact_if_approved(svc, link_id),
                "race_nights": {"races": races, "nights": nights, "dates": dates[-6:]}}
    return out


def link_queue(svc: EstateService, state: str | None = None, person: str | None = None,
               scope: str | None = None) -> dict[str, Any]:
    """The review queue. `person` narrows it to links that person's team must sign off and has not yet."""
    recs = svc.reviews.records
    ids = [i for i in svc.candidates if i in recs]
    if state == "open":
        ids = [i for i in ids if recs[i].state in OPEN]
    elif state:
        ids = [i for i in ids if recs[i].state.value == state]
    p = svc.directory.people.get(person) if person else None
    if p and not p.governance:
        ids = [i for i in ids if p.team in recs[i].required and p.team not in recs[i].approvals
               and recs[i].state in OPEN]
    if scope == "cross":
        ids = [i for i in ids if svc.a.estate.dependencies()[i].cross_scheduler]
    elif scope:
        jobs = svc.a.estate.jobs()
        ids = [i for i in ids if scope in (jobs[svc.candidates[i].source].scheduler_id,
                                           jobs[svc.candidates[i].target].scheduler_id)]
    counts: dict[str, int] = {s.value: 0 for s in LinkState}
    for r in recs.values():
        if r.link_id in svc.candidates:
            counts[r.state.value] += 1
    cards = sorted((link_card(svc, i) for i in ids),
                   key=lambda c: (c["state"] not in ("needs_info", "in_review", "proposed"), -c["probability"]))
    return {"links": cards, "counts": counts, "policy": svc.reviews.policy.describe(),
            "person": p.__dict__ if p else None}


def review(svc: EstateService, link_id: str, person_id: str, decision: str, comment: str) -> dict[str, Any]:
    """Record a decision, update the dependency's state, audit it, and re-run analysis."""
    with svc._lock:
        a = svc.a
        if link_id not in svc.reviews.records:
            raise ReviewError(f"Unknown link {link_id}")
        before = svc.reviews.records[link_id].state
        rec = svc.reviews.decide(link_id, person_id, decision, comment, a.estate.now)
        dep = a.estate.dependencies()[link_id]
        dep.review_state = svc.reviews.dependency_state(link_id)
        p = svc.directory.people[person_id]
        a.estate.audit.append({"at": iso(a.estate.now), "actor": p.name, "action": f"link {decision}",
                               "dependency_id": link_id, "command": f"link review: {before.value} → {rec.state.value}",
                               "note": comment, "receipt": {"accepted": True}})
        svc.reanalyse()      # lineage, process membership, the knowledge graph and findings all depend on it
        return link_card(svc, link_id, detail=True)


def people(svc: EstateService) -> list[dict[str, Any]]:
    recs = svc.reviews.records
    out = []
    for p in svc.directory.people.values():
        waiting = sum(1 for r in recs.values() if r.link_id in svc.candidates and r.state in OPEN
                      and p.team in r.required and p.team not in r.approvals)
        out.append({**p.__dict__, "team_name": svc.directory.team_name(p.team), "waiting": waiting})
    return sorted(out, key=lambda x: (x["governance"], -x["waiting"], x["name"]))
