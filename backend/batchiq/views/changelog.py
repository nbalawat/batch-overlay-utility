"""Changelog: replay the syncs where definitions changed and diff their knowledge graphs.

Each snapshot is built exactly like a live sync (simulated connectors, adapters,
source mining, definition-level links), from the definitions as they were on
that night. Nothing is read from the ground truth's change list except the
author and ticket, which a client's scheduler audit trail (AutoSys autotrack,
Control-M audit, git history) would supply.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from batchiq.discovery.miner import SourceMiner
from batchiq.knowledge.builder import KGInputs, KnowledgeGraphBuilder
from batchiq.knowledge.changes import diff
from batchiq.knowledge.graph import KnowledgeGraph
from batchiq.linking.evidence import DefinitionArtifactMatch, LinkContext
from batchiq.linking.recommender import LinkRecommender
from batchiq.simulation.estate import CHANGES, specs_as_of

if TYPE_CHECKING:
    from batchiq.core.store import InMemoryEstate
    from batchiq.service import EstateService


def snapshot(svc: EstateService, nights_ago: int, now: datetime) -> KnowledgeGraph:
    adapters, repos = svc._connect(specs_as_of(nights_ago), [], now)
    miner = SourceMiner()
    jobs, deps, mined, schedulers = {}, [], {}, {}
    for sid, ad in adapters.items():
        snap = ad.sync(now)
        schedulers[sid] = snap.scheduler
        for j in snap.jobs:
            jobs[j.id] = j
            mined[j.id] = miner.mine(j, ad.source_refs(j), repos[sid])
        deps += snap.dependencies
    facts, cands = LinkRecommender(discovery=(DefinitionArtifactMatch(),), enrichers=()).run(
        LinkContext(jobs, deps, mined, {}, []))
    links = facts + [LinkRecommender.to_dependency(c, jobs, "auto") for c in cands if c.definitional]
    return KnowledgeGraphBuilder().build(KGInputs(schedulers, jobs, deps + links, mined))


def build_changelog(svc: EstateService, estate: InMemoryEstate, now: datetime) -> list[dict[str, Any]]:
    meta = {c.job_key: c for c in CHANGES}
    tonight = date.fromisoformat(estate.business_date)
    out = []
    for n in sorted({c.nights_ago for c in CHANGES}, reverse=True):
        old, new = snapshot(svc, n, now), snapshot(svc, n - 1, now)
        detected = tonight - timedelta(days=n - 1)
        changes = []
        for jc in diff(old, new):
            m = meta.get(jc.job_id)
            follow = [c for c in svc.candidates.values() if jc.job_id in (c.source, c.target)]
            changes.append({
                "job_id": jc.job_id, "name": jc.name, "scheduler_id": jc.scheduler_id, "kind": jc.kind,
                "details": jc.details, "added": jc.added, "removed": jc.removed,
                "change": {"id": m.id, "ticket": m.ticket, "author": m.author, "summary": m.summary}
                if m and m.nights_ago == n else None,
                "follow_ups": [{"link_id": c.id, "probability": c.probability,
                                "state": svc.reviews.records[c.id].state.value if c.id in svc.reviews.records
                                else None} for c in follow]})
        if changes:
            out.append({"sync": f"{detected.isoformat()} 19:00", "business_date": detected.isoformat(),
                        "nodes_before": len(old.nodes), "nodes_after": len(new.nodes),
                        "edges_before": len(old.edges), "edges_after": len(new.edges), "changes": changes})
    return list(reversed(out))
