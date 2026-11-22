"""Assistant tools over the knowledge graph, findings, link reviews and changes.

Each tool is a `GraphTool`: a spec the LLM sees, and a pure function of the
service and its arguments. They answer layered questions (job → file → host →
process), questions scoped to one ecosystem, and questions about what the code
does that no scheduler console shows (e-mails, external transfers, API calls).
"""
from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from batchiq.knowledge.ontology import EdgeType, NodeType
from batchiq.llm.base import ToolSpec
from batchiq.views import ecosystems as eco
from batchiq.views import knowledge as kgv
from batchiq.views import links as lnk
from batchiq.views.common import VENDOR_LABEL

if TYPE_CHECKING:
    from batchiq.service import EstateService

_OBJ = {"type": "object", "additionalProperties": False}
E, N = EdgeType, NodeType

SCHEDULER_WORDS = {"control-m": "ctm-prd", "controlm": "ctm-prd", "ctm": "ctm-prd", "mainframe": "ctm-prd",
                   "autosys": "autosys-ae1", "airflow": "airflow-dp", "adf": "adf-prd", "data factory": "adf-prd",
                   "azure": "adf-prd"}


def _schema(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {**_OBJ, "properties": props, "required": required or []}


@dataclass(frozen=True)
class GraphTool:
    spec: ToolSpec
    run: Callable[[EstateService, dict[str, Any]], Any]


# ---------------------------------------------------------------------- resolution
def resolve_scheduler(svc: EstateService, text: str | None) -> str | None:
    if not text:
        return None
    t = text.lower().strip()
    if t in svc.a.estate.schedulers:
        return t
    for word, sid in SCHEDULER_WORDS.items():
        if word in t and sid in svc.a.estate.schedulers:
            return sid
    return None


def resolve_entity(svc: EstateService, text: str, types: set[NodeType] | None = None) -> str | None:
    """A node id from an id, a job name, a host, a file or table name, an e-mail address or a process name."""
    kg = svc.a.kg
    if text in kg.nodes:
        return text
    t = text.strip().strip("'\"`")
    for prefix in ("host:", "mail:", "endpoint:", "queue:", "data:", "file:", "process:"):
        if prefix + t.lower() in kg.nodes:
            return prefix + t.lower()
    hits = kg.search(t, types, limit=5)
    if hits:
        jobs = [h for h in hits if h.type == N.JOB]
        exact = [h for h in hits if h.label.lower() == t.lower()]
        return (exact or jobs or hits)[0].id
    return None


def _brief(svc: EstateService, nid: str) -> dict[str, Any]:
    n = svc.a.kg.nodes[nid]
    out = {"id": nid, "type": n.type.value, "label": n.label}
    if n.type == N.JOB:
        out["scheduler"] = VENDOR_LABEL.get(n.props.get("vendor", ""), n.props.get("vendor"))
        out["container"] = n.props.get("container")
    return out


# ---------------------------------------------------------------------- tools
def describe_entity(svc: EstateService, args: dict[str, Any]) -> Any:
    nid = resolve_entity(svc, args["entity"])
    if not nid:
        return {"error": f"Nothing in the knowledge graph matches '{args['entity']}'"}
    d = kgv.node(svc.a.kg, nid)
    rels = []
    for r in d["relations"]:
        if args.get("relation") and r["type"] != args["relation"].upper():
            continue
        rels.append({"direction": r["direction"], "type": r["type"],
                     "items": [{**_brief(svc, e["other"]["id"]), "provenance": e["provenance"], "refs": e["refs"][:2],
                                "confidence": e["confidence"], "review": e["props"].get("review")}
                               for e in r["edges"][:25]]})
    out = {"node": d["node"], "relations": rels}
    if d["node"]["type"] == N.TEAM.value:
        out["people"] = [{"name": p.name, "title": p.title}
                         for p in svc.directory.members(d["node"]["props"].get("team_id", ""))]
    return out


def find_path(svc: EstateService, args: dict[str, Any]) -> Any:
    a, b = resolve_entity(svc, args["source"]), resolve_entity(svc, args["target"])
    if not a or not b:
        return {"error": f"Could not resolve {'source' if not a else 'target'}"}
    res = kgv.paths(svc.a.kg, a, b, directed=True, types=args.get("relations"))
    directed = True
    if not res["paths"]:
        res, directed = kgv.paths(svc.a.kg, a, b, directed=False, types=args.get("relations")), False
    return {"from": _brief(svc, a), "to": _brief(svc, b), "directed": directed,
            "paths": [{"hops": [_brief(svc, h["id"]) for h in p["hops"]],
                       "via": [{"type": e["type"], "provenance": e["provenance"], "review": e["props"].get("review")}
                               for e in p["edges"]]} for p in res["paths"][:3]]}


def trace_lineage(svc: EstateService, args: dict[str, Any]) -> Any:
    """Every job upstream (or downstream) of a job, by depth, with the scheduler and what links each hop."""
    from batchiq.assistant.tools import ToolBox
    jid = ToolBox(svc).resolve_job(args["job"])
    if not jid:
        return {"error": f"No job matches '{args['job']}'"}
    g, jobs = svc.a.graph, svc.a.estate.jobs()
    up = args.get("direction", "up") != "down"
    reach = g.ancestors(jid) if up else g.descendants(jid)
    deps = svc.a.estate.dependencies()
    active = {(d.source, d.target): d for d in g.edges}
    inside = set(reach) | {jid}
    by_depth: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for other, depth in sorted(reach.items(), key=lambda x: x[1]):
        via = [d for (s, t), d in active.items() if (s == other and t in inside if up else t == other and s in inside)]
        by_depth[depth].append({"job": jobs[other].name, "scheduler": VENDOR_LABEL[jobs[other].vendor.value],
                                "container": jobs[other].container,
                                "links": sorted({d.origin.value + (f" ({d.artifact})" if d.artifact else "")
                                                 for d in via})[:3]})
    pending = [d for d in deps.values() if d.review_state == "suggested" and (d.target == jid if up else d.source == jid)]
    return {"job": _brief(svc, jid), "direction": "upstream" if up else "downstream", "count": len(reach),
            "schedulers": sorted({VENDOR_LABEL[jobs[o].vendor.value] for o in reach}),
            "by_depth": [{"depth": k, "jobs": v} for k, v in sorted(by_depth.items())],
            "pending_links_not_counted": [{"id": d.id, "other": jobs[d.source if up else d.target].name,
                                           "probability": d.confidence} for d in pending]}


def ecosystem_summary(svc: EstateService, args: dict[str, Any]) -> Any:
    sid = resolve_scheduler(svc, args["scheduler"])
    if not sid:
        return {"error": f"No scheduler matches '{args['scheduler']}'", "schedulers": list(svc.a.estate.schedulers)}
    d = eco.ecosystem(svc, sid)
    return {k: d[k] for k in ("id", "name", "vendor_label", "container_kind", "stats", "hosts")} | {
        "containers": [{"name": c["name"], "jobs": [j["name"] for j in c["jobs"]]} for c in d["containers"]],
        "boundary_links": [e for e in d["graph"]["edges"] if e["cross_scheduler"]][:20],
        "findings": [{k: f[k] for k in ("severity", "category", "title")} for f in d["findings"]][:15],
        "unmonitored": [j["name"] for c in d["containers"] for j in c["jobs"] if j["alerting"] is False],
        "unresolved": [{"job": j["name"], "waits_on": j["unresolved_conditions"]} for c in d["containers"]
                       for j in c["jobs"] if j["unresolved_conditions"]]}


def list_findings(svc: EstateService, args: dict[str, Any]) -> Any:
    sid = resolve_scheduler(svc, args.get("scheduler"))
    out = [f for f in svc.a.findings
           if (not args.get("kind") or f.kind == args["kind"]) and (not args.get("category")
                                                                     or f.category == args["category"])
           and (not sid or f.scope == sid or (f.scope == "cross" and any(
               svc.a.estate.jobs()[j].scheduler_id == sid for j in f.job_ids if j in svc.a.estate.jobs())))]
    return [{k: getattr(f, k) for k in ("id", "kind", "severity", "category", "title", "detail", "recommendation",
                                        "scope", "link_id")} for f in out[:15]]


def link_candidates(svc: EstateService, args: dict[str, Any]) -> Any:
    q = lnk.link_queue(svc, args.get("state") or "open")
    rows = q["links"]
    if args.get("job"):
        t = args["job"].lower()
        rows = [c for c in rows if t in c["source"]["name"].lower() or t in c["target"]["name"].lower()]
    return {"counts": q["counts"], "policy": q["policy"],
            "links": [{"id": c["id"], "from": f"{c['source']['name']} ({c['source']['vendor_label']})",
                       "to": f"{c['target']['name']} ({c['target']['vendor_label']})", "probability": c["probability"],
                       "state": c["state"], "evidence": [e["kind"] for e in c["evidence"]],
                       "waiting_on": [r["name"] for r in c["required"] if not r["approved"]]} for c in rows[:12]]}


def host_outage(svc: EstateService, args: dict[str, Any]) -> Any:
    nid = resolve_entity(svc, args["host"], {N.HOST})
    if not nid or svc.a.kg.nodes[nid].type != N.HOST:
        return {"error": f"No host matches '{args['host']}'"}
    kg, eng = svc.a.kg, svc.a.engine
    on = sorted({e.source for e in kg.edges_of(nid, "in", {E.RUNS_ON})})
    hit: set[str] = set(on)
    for j in on:
        hit |= set(svc.a.graph.descendants(j))
    procs = sorted({p for j in hit for p in svc.a.mapper.processes_for(j)})
    jobs = svc.a.estate.jobs()
    return {"host": kg.nodes[nid].label, "kind": kg.nodes[nid].props.get("kind"),
            "jobs_on_host": [jobs[j].name for j in on],
            "downstream_jobs": len(hit) - len(on),
            "schedulers_affected": sorted({VENDOR_LABEL[jobs[j].vendor.value] for j in hit}),
            "processes": [{"name": svc.a.mapper.processes[p].name, "criticality": svc.a.mapper.processes[p].criticality,
                           "sla": svc.a.mapper.processes[p].sla_deadline.strftime("%H:%M")} for p in procs],
            "services": sorted({s for j in on for s in eng.impact_of(j)["services"]})}


_COMM = {"email": {E.NOTIFIES}, "egress": {E.TRANSFERS_TO}, "api": {E.CALLS}, "inbound": {E.FETCHES_FROM}}


def communications(svc: EstateService, args: dict[str, Any]) -> Any:
    """What the code does outside the scheduler: e-mails, file transfers, API calls."""
    kind = args.get("kind", "all")
    types = set().union(*_COMM.values()) if kind == "all" else _COMM.get(kind, set())
    sid = resolve_scheduler(svc, args.get("scheduler"))
    external_only = args.get("external_only", kind == "egress")
    kg = svc.a.kg
    rows = []
    for e in kg.edges.values():
        if e.type not in types:
            continue
        src, tgt = kg.nodes[e.source], kg.nodes[e.target]
        if sid and src.props.get("scheduler_id") != sid:
            continue
        internal = tgt.props.get("internal")
        if external_only and tgt.type == N.ENDPOINT and internal:
            continue
        rows.append({"job": src.label, "scheduler": VENDOR_LABEL.get(src.props.get("vendor", ""), ""),
                     "what": e.type.value, "to": tgt.label,
                     "external": (not internal) if tgt.type == N.ENDPOINT else None,
                     "subject": e.props.get("subject"), "path": e.props.get("path"),
                     "method": e.props.get("method"), "source": e.refs[0] if e.refs else None})
    return sorted(rows, key=lambda r: (r["what"], r["scheduler"], r["job"]))


def changes(svc: EstateService, args: dict[str, Any]) -> Any:
    out = []
    for e in svc.changelog_entries or []:
        for c in e["changes"]:
            out.append({"detected": e["business_date"], "job": c["name"], "scheduler": c["scheduler_id"],
                        "kind": c["kind"], "details": c["details"],
                        "ticket": c["change"]["ticket"] if c["change"] else None,
                        "author": c["change"]["author"] if c["change"] else None,
                        "summary": c["change"]["summary"] if c["change"] else None,
                        "follow_ups": c["follow_ups"]})
    if args.get("job"):
        out = [c for c in out if args["job"].lower() in c["job"].lower()]
    return out


GRAPH_TOOLS: tuple[GraphTool, ...] = (
    GraphTool(ToolSpec("describe_entity", "Everything the knowledge graph knows about one thing and how it relates: "
                       "a job, file, table, queue, host, e-mail address, external endpoint, team, application or "
                       "business process. Each relation says where it was learned (definition, code, runtime, ...).",
                       _schema({"entity": {"type": "string"}, "relation": {"type": "string", "enum": [t.value for t in E]}},
                               ["entity"])), describe_entity),
    GraphTool(ToolSpec("find_path", "How two things are connected in the knowledge graph (e.g. a job and a business "
                       "process, a file and a report job). Optionally restrict to relation types, comma separated.",
                       _schema({"source": {"type": "string"}, "target": {"type": "string"},
                                "relations": {"type": "string"}}, ["source", "target"])), find_path),
    GraphTool(ToolSpec("trace_lineage", "All jobs upstream (direction=up) or downstream (down) of a job, by depth, "
                       "across schedulers, plus links still awaiting review that are not counted.",
                       _schema({"job": {"type": "string"}, "direction": {"type": "string", "enum": ["up", "down"]}},
                               ["job"])), trace_lineage),
    GraphTool(ToolSpec("get_ecosystem", "One scheduler's own view: containers, jobs, hosts, findings, unmonitored "
                       "jobs, conditions nothing satisfies, and links to other schedulers. Use for questions scoped to "
                       "Control-M, AutoSys, Airflow or ADF.",
                       _schema({"scheduler": {"type": "string"}}, ["scheduler"])), ecosystem_summary),
    GraphTool(ToolSpec("list_findings", "Static (definitions and code) and runtime (30 nights of history) findings, "
                       "optionally for one scheduler, kind or category.",
                       _schema({"kind": {"type": "string", "enum": ["static", "runtime"]}, "category": {"type": "string"},
                                "scheduler": {"type": "string"}})), list_findings),
    GraphTool(ToolSpec("list_link_candidates", "Links the overlay recommends between jobs, with probability, evidence "
                       "and which owners still need to review. state: open, proposed, in_review, needs_info, approved, "
                       "rejected.", _schema({"state": {"type": "string"}, "job": {"type": "string"}})), link_candidates),
    GraphTool(ToolSpec("host_outage_impact", "What breaks if a host or cluster goes down: jobs on it, everything "
                       "downstream across schedulers, business processes and services.",
                       _schema({"host": {"type": "string"}}, ["host"])), host_outage),
    GraphTool(ToolSpec("find_communications", "What jobs do outside the scheduler, mined from their code: e-mails "
                       "(kind=email), files sent out (egress), API calls (api), files pulled in (inbound).",
                       _schema({"kind": {"type": "string", "enum": ["all", "email", "egress", "api", "inbound"]},
                                "scheduler": {"type": "string"}, "external_only": {"type": "boolean"}})), communications),
    GraphTool(ToolSpec("list_changes", "Recent definition changes detected between syncs, with ticket and author, and "
                       "the link reviews they triggered.", _schema({"job": {"type": "string"}})), changes),
)
GRAPH_TOOL_INDEX = {t.spec.name: t for t in GRAPH_TOOLS}


def mentioned_scheduler(q: str) -> str | None:
    for word, sid in SCHEDULER_WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", q):
            return sid
    return None
