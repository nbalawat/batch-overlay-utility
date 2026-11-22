"""Change tracking: diff two knowledge graph snapshots into a readable changelog.

Each sync rebuilds the graph from definitions and code, then compares it with
the previous snapshot. The diff is grouped per job and phrased the way an
operator would say it ("condition on PAY_SETTLE_NET removed; now starts daily
02:00"), so nobody has to maintain the graph by hand to keep it current.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from batchiq.knowledge.graph import Edge, KnowledgeGraph
from batchiq.knowledge.ontology import EdgeType, NodeType

_WATCH = {EdgeType.FEEDS, EdgeType.SCHEDULED_BY, EdgeType.RUNS_ON, EdgeType.READS, EdgeType.WRITES,
          EdgeType.PUBLISHES, EdgeType.TRANSFERS_TO, EdgeType.FETCHES_FROM, EdgeType.CALLS, EdgeType.NOTIFIES,
          EdgeType.TRIGGERED_BY, EdgeType.OWNED_BY}
_VERB = {EdgeType.FEEDS: "upstream", EdgeType.SCHEDULED_BY: "schedule", EdgeType.RUNS_ON: "runs on",
         EdgeType.READS: "reads", EdgeType.WRITES: "writes", EdgeType.PUBLISHES: "publishes",
         EdgeType.TRANSFERS_TO: "sends files to", EdgeType.FETCHES_FROM: "fetches from", EdgeType.CALLS: "calls",
         EdgeType.NOTIFIES: "notifies", EdgeType.TRIGGERED_BY: "triggered by", EdgeType.OWNED_BY: "owned by"}


@dataclass
class JobChange:
    job_id: str
    name: str
    scheduler_id: str
    kind: str                                   # added | removed | modified
    details: list[str] = field(default_factory=list)
    added: list[dict[str, str]] = field(default_factory=list)
    removed: list[dict[str, str]] = field(default_factory=list)


def _edge_keys(g: KnowledgeGraph) -> dict[str, Edge]:
    return {k: e for k, e in g.edges.items() if e.type in _WATCH and g.nodes[e.source].type == NodeType.JOB}


def _describe(g: KnowledgeGraph, e: Edge, jid: str) -> str:
    if e.type == EdgeType.FEEDS:
        other = e.source if e.target == jid else e.target
        rel = "condition on" if e.target == jid else "feeds"
        return f"{rel} {g.nodes[other].label}"
    return f"{_VERB[e.type]} {g.nodes[e.target].label}"


def diff(old: KnowledgeGraph, new: KnowledgeGraph) -> list[JobChange]:
    out: dict[str, JobChange] = {}

    def change(jid: str, g: KnowledgeGraph, kind: str = "modified") -> JobChange:
        n = g.nodes[jid]
        return out.setdefault(jid, JobChange(jid, n.label, n.props.get("scheduler_id", ""), kind))

    old_jobs = {k for k, n in old.nodes.items() if n.type == NodeType.JOB}
    new_jobs = {k for k, n in new.nodes.items() if n.type == NodeType.JOB}
    for jid in sorted(new_jobs - old_jobs):
        c = change(jid, new, "added")
        n = new.nodes[jid]
        c.details.append(f"new job in {n.props.get('container')}")
    for jid in sorted(old_jobs - new_jobs):
        change(jid, old, "removed").details.append("job deleted")

    oe, ne = _edge_keys(old), _edge_keys(new)
    for k in sorted(set(ne) - set(oe)):
        e = ne[k]
        for jid in {e.source, e.target} & new_jobs:
            c = change(jid, new, "added" if jid not in old_jobs else "modified")
            c.added.append({"edge": e.type.value, "text": _describe(new, e, jid)})
    for k in sorted(set(oe) - set(ne)):
        e = oe[k]
        for jid in {e.source, e.target} & old_jobs & new_jobs:
            change(jid, new).removed.append({"edge": e.type.value, "text": _describe(old, e, jid)})
    for c in out.values():
        if c.kind == "modified":
            c.details = [f"+ {a['text']}" for a in c.added] + [f"− {r['text']}" for r in c.removed]
    return sorted(out.values(), key=lambda c: (c.kind != "added", c.scheduler_id, c.name))
