"""Ecosystem explorer: one scheduler at a time, as its own teams see it, plus its edges to the others."""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import TYPE_CHECKING, Any

from batchiq.analysis.findings import SEVERITY_ORDER
from batchiq.knowledge.builder import CONTAINER_KIND
from batchiq.knowledge.ontology import EdgeType
from batchiq.views.common import VENDOR_LABEL

if TYPE_CHECKING:
    from batchiq.service import EstateService


def _severity_counts(findings) -> dict[str, int]:
    c = Counter(f.severity for f in findings)
    return {s: c.get(s, 0) for s in SEVERITY_ORDER}


def ecosystems(svc: EstateService) -> list[dict[str, Any]]:
    a = svc.a
    jobs = a.estate.jobs()
    out = []
    for sid, s in a.estate.schedulers.items():
        mine = [j for j in jobs.values() if j.scheduler_id == sid]
        ids = {j.id for j in mine}
        deps = list(a.estate.dependencies().values())
        intra = [d for d in deps if d.source in ids and d.target in ids and d.review_state != "rejected"]
        cross = [d for d in deps if d.cross_scheduler and (d.source in ids) != (d.target in ids)
                 and d.review_state != "rejected"]
        out.append({
            "id": sid, "name": s.name, "vendor": s.vendor.value, "vendor_label": VENDOR_LABEL[s.vendor.value],
            "environment": s.environment, "description": s.description,
            "container_kind": CONTAINER_KIND[s.vendor.value],
            "containers": len({j.container for j in mine}), "jobs": len(mine),
            "hosts": len({j.host for j in mine if j.host}), "teams": len({j.team for j in mine if j.team}),
            "intra_links": len(intra), "cross_links": len(cross),
            "cross_pending": sum(1 for d in cross if d.review_state == "suggested"),
            "processes": len({p for j in mine for p in a.mapper.processes_for(j.id)}),
            "findings": _severity_counts([f for f in a.findings if f.scope == sid]),
            "pipeline": svc.pipeline.get(sid, {})})
    return out


def ecosystem(svc: EstateService, sid: str) -> dict[str, Any]:
    a = svc.a
    jobs = a.estate.jobs()
    mine = {jid: j for jid, j in jobs.items() if j.scheduler_id == sid}
    deps = [d for d in a.estate.dependencies().values() if d.review_state != "rejected"]
    containers: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for jid, j in mine.items():
        containers[j.container].append({**svc.job_brief(jid), "team": j.team, "host": j.host,
                                        "schedule": j.schedule, "alerting": j.alerting,
                                        "unresolved_conditions": j.unresolved_conditions,
                                        "mined_facts": len(svc.mined.get(jid, []))})
    intra = [d for d in deps if d.source in mine and d.target in mine]
    boundary = [d for d in deps if d.cross_scheduler and (d.source in mine) != (d.target in mine)]
    externals = {d.source for d in boundary if d.source not in mine} | {d.target for d in boundary
                                                                        if d.target not in mine}
    kg = a.kg
    hosts: Counter[str] = Counter()
    data_out: Counter[str] = Counter()
    data_in: Counter[str] = Counter()
    for jid in mine:
        for e in kg.edges_of(jid, "out"):
            if e.type == EdgeType.RUNS_ON:
                hosts[kg.nodes[e.target].label] += 1
            elif e.type in (EdgeType.WRITES, EdgeType.PUBLISHES):
                data_out[e.target] += 1
            elif e.type in (EdgeType.READS, EdgeType.TRIGGERED_BY):
                data_in[e.target] += 1
    s = a.estate.schedulers[sid]
    findings = [f for f in a.findings if f.scope == sid or (f.scope == "cross" and set(f.job_ids) & set(mine))]
    return {
        "id": sid, "name": s.name, "vendor": s.vendor.value, "vendor_label": VENDOR_LABEL[s.vendor.value],
        "environment": s.environment, "description": s.description,
        "container_kind": CONTAINER_KIND[s.vendor.value],
        "containers": [{"name": c, "jobs": sorted(v, key=lambda x: x["name"])} for c, v in sorted(containers.items())],
        "graph": {
            "nodes": [{"id": jid, "name": j.name, "container": j.container, "scheduler_id": sid,
                       "status": a.states[jid].status.value, "kind": j.kind.value, "external": False}
                      for jid, j in mine.items()]
            + [{"id": x, "name": jobs[x].name, "container": jobs[x].container, "scheduler_id": jobs[x].scheduler_id,
                "status": a.states[x].status.value, "kind": jobs[x].kind.value, "external": True}
               for x in sorted(externals)],
            "edges": [{"id": d.id, "source": d.source, "target": d.target, "origin": d.origin.value,
                       "review_state": d.review_state, "confidence": d.confidence, "artifact": d.artifact,
                       "cross_scheduler": d.cross_scheduler} for d in intra + boundary]},
        "stats": {"jobs": len(mine), "containers": len(containers), "intra_links": len(intra),
                  "boundary_links": len(boundary),
                  "pending_boundary_links": sum(1 for d in boundary if d.review_state == "suggested"),
                  "unmonitored": sum(1 for j in mine.values() if j.alerting is False),
                  "unresolved_conditions": sum(len(j.unresolved_conditions) for j in mine.values()),
                  "mined_facts": sum(len(svc.mined.get(j, [])) for j in mine)},
        "hosts": [{"host": h, "jobs": n} for h, n in hosts.most_common()],
        "outputs": [{"id": k, "label": kg.nodes[k].label, "type": kg.nodes[k].type.value, "writers": n}
                    for k, n in data_out.most_common(15)],
        "inputs": [{"id": k, "label": kg.nodes[k].label, "type": kg.nodes[k].type.value, "readers": n}
                   for k, n in data_in.most_common(15)],
        "findings": [f.__dict__ for f in findings],
        "pipeline": svc.pipeline.get(sid, {}),
        "suggested_questions": [
            f"What does {s.name} depend on outside itself?",
            f"Which {s.name} jobs fail silently?",
            f"Which hosts does {s.name} run on, and what runs there?",
            f"What would break in {s.name} if {next(iter(hosts), 'its main host')} went down?",
        ]}
