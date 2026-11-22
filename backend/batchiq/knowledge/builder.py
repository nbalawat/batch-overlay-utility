"""Builds the estate knowledge graph from everything the overlay has learned.

The graph is rebuilt from source on every sync instead of being edited by hand,
which is what keeps it curated without anyone maintaining it. Definitions,
mined code, run history, the business catalogue, link reviews and incidents each
contribute edges tagged with their provenance. When a team changes a job, the
next sync rebuilds the graph and `changes.diff` reports what moved.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from batchiq.discovery.miner import MinedFact
from batchiq.domain.models import ArtifactType, Dependency, Incident, Job, JobRun, RunStatus
from batchiq.knowledge.graph import KnowledgeGraph
from batchiq.knowledge.ontology import EdgeType as E
from batchiq.knowledge.ontology import NodeType as N
from batchiq.knowledge.ontology import Provenance as P

if TYPE_CHECKING:
    from batchiq.core.business import BusinessMapper
    from batchiq.core.stats import JobBaseline
    from batchiq.domain.models import BusinessProcess, Scheduler, Service
    from batchiq.linking.review import Directory

CONTAINER_KIND = {"control-m": "folder", "autosys": "box", "airflow": "DAG", "azure-data-factory": "pipeline"}
_ART = {ArtifactType.FILE: N.FILE, ArtifactType.DATASET: N.DATASET, ArtifactType.TABLE: N.DATASET,
        ArtifactType.QUEUE: N.QUEUE, ArtifactType.EVENT: N.EVENT}
_MINED_NODE = {"file": N.FILE, "dataset": N.DATASET, "queue": N.QUEUE, "event": N.EVENT, "endpoint": N.ENDPOINT,
               "communication": N.COMMUNICATION}
_MINED_EDGE = {"reads": E.READS, "writes": E.WRITES, "publishes": E.PUBLISHES, "transfers_to": E.TRANSFERS_TO,
               "fetches_from": E.FETCHES_FROM, "calls": E.CALLS, "notifies": E.NOTIFIES}


def host_kind(h: str) -> str:
    h = h.lower()
    for prefix, kind in (("zos", "mainframe LPAR"), ("snowflake", "Snowflake warehouse"),
                         ("databricks", "Databricks cluster"), ("spark", "Spark on Kubernetes"),
                         ("celery", "Airflow worker pool"), ("worker", "Airflow worker"),
                         ("ir-", "ADF integration runtime")):
        if h.startswith(prefix):
            return kind
    return "Linux server" if "lnx" in h else "host"


def schedule_node(job: Job) -> tuple[str, str] | None:
    if job.scheduled_time:
        t = job.scheduled_time.strftime("%H:%M")
        return f"schedule:time:{t}", f"Daily {t}"
    s = job.schedule or ""
    if s.startswith(("On blob", "On custom event")) or s == "Triggered by datasets":
        return f"schedule:{s.lower()}", s
    return None


@dataclass
class KGInputs:
    schedulers: dict[str, Scheduler]
    jobs: dict[str, Job]
    dependencies: list[Dependency]
    mined: dict[str, list[MinedFact]]
    runs: dict[str, list[JobRun]] = field(default_factory=dict)
    business_date: str | None = None
    baselines: dict[str, JobBaseline] = field(default_factory=dict)
    processes: dict[str, BusinessProcess] = field(default_factory=dict)
    services: dict[str, Service] = field(default_factory=dict)
    mapper: BusinessMapper | None = None
    incidents: list[Incident] = field(default_factory=list)
    directory: Directory | None = None
    link_states: dict[str, str] = field(default_factory=dict)   # dependency id -> review state for the UI


class KnowledgeGraphBuilder:
    def build(self, x: KGInputs) -> KnowledgeGraph:
        g = KnowledgeGraph()
        self._definitions(g, x)
        self._code(g, x)
        self._links(g, x)
        if x.runs:
            self._runtime(g, x)
        if x.processes:
            self._business(g, x)
        for inc in x.incidents:
            iid = f"incident:{inc.id}"
            g.node(iid, N.INCIDENT, inc.id, title=inc.title, date=inc.date, error_code=inc.error_code,
                   mttr_minutes=inc.mttr_minutes)
            for jid in inc.jobs:
                if jid in g.nodes:
                    g.edge(iid, E.AFFECTED, jid, P.INCIDENT, ref=inc.id)
        return g

    # ------------------------------------------------------------------ definitions
    def _definitions(self, g: KnowledgeGraph, x: KGInputs) -> None:
        for sid, s in x.schedulers.items():
            g.node(f"scheduler:{sid}", N.SCHEDULER, s.name, vendor=s.vendor.value, environment=s.environment)
        for j in x.jobs.values():
            cid = f"container:{j.scheduler_id}:{j.container}"
            g.node(cid, N.CONTAINER, j.container, kind=CONTAINER_KIND[j.vendor.value], scheduler_id=j.scheduler_id,
                   vendor=j.vendor.value)
            g.edge(f"scheduler:{j.scheduler_id}", E.CONTAINS, cid, P.DEFINITION)
            g.node(j.id, N.JOB, j.name, scheduler_id=j.scheduler_id, vendor=j.vendor.value, container=j.container,
                   kind=j.kind.value, schedule=j.schedule, command=j.command, alerting=j.alerting,
                   unresolved_conditions=list(j.unresolved_conditions) or None)
            g.edge(cid, E.CONTAINS, j.id, P.DEFINITION)
            sch = schedule_node(j)
            if sch:
                g.node(sch[0], N.SCHEDULE, sch[1])
                g.edge(j.id, E.SCHEDULED_BY, sch[0], P.DEFINITION)
            if j.host:
                g.node(f"host:{j.host}", N.HOST, j.host, kind=host_kind(j.host))
                g.edge(j.id, E.RUNS_ON, f"host:{j.host}", P.DEFINITION)
            if j.application:
                g.node(f"app:{j.application}", N.APPLICATION, j.application)
                g.edge(j.id, E.BELONGS_TO, f"app:{j.application}", P.DEFINITION)
            if j.team:
                team = j.team
                label = x.directory.team_name(team) if x.directory else team
                g.node(f"team:{team}", N.TEAM, label, team_id=team)
                g.edge(j.id, E.OWNED_BY, f"team:{team}", P.DEFINITION)
            for a in j.produces:
                g.node(a.canonical, _ART[a.type], a.canonical.split(":", 1)[1], raw=a.raw)
                g.edge(j.id, E.WRITES, a.canonical, P.DEFINITION, ref=a.raw)
        files = [n for n in g.nodes.values() if n.type == N.FILE]
        for j in x.jobs.values():
            for a in j.consumes:
                if a.type == ArtifactType.EVENT:
                    g.node(a.canonical, N.EVENT, a.raw, trigger_prefix=True)
                    g.edge(j.id, E.TRIGGERED_BY, a.canonical, P.DEFINITION, ref=f"subject begins with '{a.raw}'")
                elif a.match == "prefix":
                    hits = [f for f in files if f.id.startswith(a.canonical)]
                    for f in hits or [g.node(a.canonical, N.FILE, a.canonical.split(":", 1)[1] + "*", raw=a.raw)]:
                        g.edge(j.id, E.TRIGGERED_BY, f.id, P.DEFINITION, ref=f"blob path begins with {a.raw}")
                else:
                    g.node(a.canonical, _ART[a.type], a.canonical.split(":", 1)[1], raw=a.raw)
                    g.edge(j.id, E.READS, a.canonical, P.DEFINITION, ref=a.raw)

    # ------------------------------------------------------------------ code
    def _code(self, g: KnowledgeGraph, x: KGInputs) -> None:
        for jid, facts in x.mined.items():
            if jid not in g.nodes:
                continue
            for f in facts:
                ref = f"{f.path}:{f.line}"
                if f.object_type == "secret":
                    g.nodes[jid].props["plaintext_credential"] = ref
                    continue
                props: dict[str, Any] = {}
                if f.object_type == "endpoint":
                    props = {"host": f.detail.get("host"), "internal": f.detail.get("internal") == "true"}
                g.node(f.key, _MINED_NODE[f.object_type], f.label, **props)
                g.edge(jid, _MINED_EDGE[f.relation], f.key, P.CODE, ref=ref, rule=f.rule, snippet=f.snippet,
                       path=f.detail.get("path"), method=f.detail.get("method"), subject=f.detail.get("subject"))

    # ------------------------------------------------------------------ links
    def _links(self, g: KnowledgeGraph, x: KGInputs) -> None:
        for d in x.dependencies:
            if d.source not in g.nodes or d.target not in g.nodes or d.review_state == "rejected":
                continue
            prov = {"auto": P.DEFINITION, "confirmed": P.APPROVED, "suggested": P.PROPOSED}[d.review_state]
            g.edge(d.source, E.FEEDS, d.target, prov, confidence=d.confidence,
                   ref=d.artifact or d.origin.value, origin=d.origin.value, link_id=d.id,
                   cross_scheduler=d.cross_scheduler, review=x.link_states.get(d.id))

    # ------------------------------------------------------------------ runtime
    def _runtime(self, g: KnowledgeGraph, x: KGInputs) -> None:
        for jid, runs in x.runs.items():
            if jid not in g.nodes:
                continue
            hist = [r for r in runs if x.business_date and r.business_date < x.business_date]
            ok = [r for r in hist if r.status == RunStatus.SUCCEEDED]
            props = g.nodes[jid].props
            props["runs_30d"] = len({r.business_date for r in hist})
            props["failures_30d"] = sum(r.status == RunStatus.FAILED for r in hist)
            b = x.baselines.get(jid)
            if b and b.samples_min:
                props["p50_min"], props["p90_min"] = round(b.p50, 1), round(b.p90, 1)
            hosts = Counter(r.host for r in ok if r.host)
            for h, n in hosts.items():
                if f"host:{h}" not in g.nodes:
                    g.node(f"host:{h}", N.HOST, h, kind=host_kind(h))
                g.edge(jid, E.RUNS_ON, f"host:{h}", P.RUNTIME, ref=f"{n} runs in 30 nights", runs=n)
        per_host: dict[str, int] = defaultdict(int)
        for e in g.edges.values():
            if e.type == E.RUNS_ON:
                per_host[e.target] += 1
        for h, n in per_host.items():
            g.nodes[h].props["jobs"] = n

    # ------------------------------------------------------------------ business
    def _business(self, g: KnowledgeGraph, x: KGInputs) -> None:
        for sid, s in x.services.items():
            g.node(f"service:{sid}", N.SERVICE, s.name, tier=s.tier, owner=s.owner)
        for pid, bp in x.processes.items():
            bid = f"process:{pid}"
            g.node(bid, N.BUSINESS_PROCESS, bp.name, criticality=bp.criticality, regulatory=bp.regulatory,
                   sla=bp.sla_deadline.strftime("%H:%M"), owner=bp.owner)
            for s in bp.services:
                g.edge(bid, E.SUPPORTS, f"service:{s}", P.CATALOG)
            for a in bp.anchor_jobs:
                if a in g.nodes:
                    g.edge(a, E.DELIVERS, bid, P.CATALOG)
            if x.mapper:
                for m in x.mapper.members.get(pid, ()):
                    if m in g.nodes:
                        g.edge(m, E.PART_OF, bid, P.DERIVED, ref="upstream of an anchor job")
