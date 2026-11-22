"""Link recommender: turns evidence into scored link candidates.

Discovery strategies propose pairs, enrichers add corroborating evidence, and
the probability is the noisy-OR of the evidence weights: independent reasons
to believe a link each shrink the chance that it is wrong. Declared
intra-scheduler links, and dataset links inside one Airflow, are facts and skip
the review queue. Everything else is a candidate for people to review.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from batchiq.domain.models import Dependency, DependencyOrigin, Evidence
from batchiq.linking.evidence import DISCOVERY, ENRICHERS, Enricher, LinkContext, Signal, Strategy


def noisy_or(weights: list[float]) -> float:
    q = 1.0
    for w in weights:
        q *= 1 - w
    return round(1 - q, 3)


@dataclass
class Candidate:
    source: str
    target: str
    evidence: list[Evidence] = field(default_factory=list)
    artifact: str | None = None
    definitional: bool = False

    @property
    def id(self) -> str:
        return f"{self.source}->{self.target}"

    @property
    def probability(self) -> float:
        # one weight per evidence kind (the strongest), so repeated hits of one kind are not double counted
        best: dict[str, float] = {}
        for e in self.evidence:
            best[e.kind] = max(best.get(e.kind, 0.0), e.weight)
        return noisy_or(list(best.values()))

    @property
    def kinds(self) -> list[str]:
        return sorted({e.kind for e in self.evidence if e.weight > 0})


class LinkRecommender:
    def __init__(self, discovery: tuple[Strategy, ...] = DISCOVERY, enrichers: tuple[Enricher, ...] = ENRICHERS,
                 min_probability: float = 0.3) -> None:
        self.discovery, self.enrichers, self.min_probability = discovery, enrichers, min_probability

    def run(self, ctx: LinkContext) -> tuple[list[Dependency], list[Candidate]]:
        """Return (facts that need no review, candidates for review)."""
        ctx.known = defaultdict(set)
        for d in ctx.declared:
            ctx.known[d.source].add(d.target)
        jobs = ctx.jobs
        # Pass 1: definitions. Exact matches inside one scheduler are native (e.g. Airflow datasets) = facts.
        defs = list(self.discovery[0].signals(ctx))
        facts: dict[str, Dependency] = {}
        for s in defs:
            if s.definitional:
                ctx.known[s.source].add(s.target)
                if jobs[s.source].scheduler_id == jobs[s.target].scheduler_id:
                    facts[f"{s.source}->{s.target}"] = Dependency(
                        id=f"{s.source}->{s.target}", source=s.source, target=s.target,
                        origin=DependencyOrigin.ARTIFACT, cross_scheduler=False, confidence=1.0,
                        artifact=s.artifact, evidence=[s.evidence], review_state="auto")
        # Pass 2: every other strategy, then enrichment of whatever was proposed.
        cands: dict[str, Candidate] = {}

        def add(s: Signal) -> None:
            if f"{s.source}->{s.target}" in facts:
                return
            c = cands.setdefault(f"{s.source}->{s.target}", Candidate(s.source, s.target))
            if not any(e.kind == s.evidence.kind and e.detail == s.evidence.detail for e in c.evidence):
                c.evidence.append(s.evidence)
            c.artifact = c.artifact or s.artifact
            c.definitional = c.definitional or s.definitional

        for s in defs:
            add(s)
        for strat in self.discovery[1:]:
            for s in strat.signals(ctx):
                add(s)
        # Name similarity only stands if nothing stronger already links the pair.
        for c in cands.values():
            if len(c.kinds) > 1 and "name-similarity" in c.kinds:
                c.evidence = [e for e in c.evidence if e.kind != "name-similarity"]
        pairs = {(c.source, c.target) for c in cands.values()}
        for enr in self.enrichers:
            for s in enr.enrich(ctx, pairs):
                if f"{s.source}->{s.target}" in cands:
                    add(s)
        kept = [c for c in cands.values() if c.probability >= self.min_probability]
        kept.sort(key=lambda c: -c.probability)
        return list(facts.values()), kept

    @staticmethod
    def to_dependency(c: Candidate, jobs: dict, review_state: str) -> Dependency:
        return Dependency(
            id=c.id, source=c.source, target=c.target,
            origin=DependencyOrigin.ARTIFACT if c.definitional else DependencyOrigin.INFERRED,
            cross_scheduler=jobs[c.source].scheduler_id != jobs[c.target].scheduler_id,
            confidence=c.probability, artifact=c.artifact, evidence=list(c.evidence), review_state=review_state)
