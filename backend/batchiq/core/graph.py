"""Lineage graph over the unified estate (all schedulers, one graph)."""
from __future__ import annotations

from collections import defaultdict, deque

from batchiq.config import settings
from batchiq.domain.models import Dependency


class LineageGraph:
    def __init__(self, deps: list[Dependency], min_confidence: float | None = None) -> None:
        # Facts (declared, or definition matches inside one scheduler) and links people approved. Links still in
        # review are kept out on purpose: they are shown, and flagged when they matter, but never assumed.
        threshold = settings.correlation_min_confidence if min_confidence is None else min_confidence
        self.edges = [d for d in deps if d.review_state == "confirmed"
                      or (d.review_state == "auto" and d.confidence >= threshold)]
        self.up: dict[str, list[Dependency]] = defaultdict(list)
        self.down: dict[str, list[Dependency]] = defaultdict(list)
        for d in self.edges:
            self.up[d.target].append(d)
            self.down[d.source].append(d)

    def parents(self, job_id: str) -> list[str]:
        return [d.source for d in self.up.get(job_id, [])]

    def children(self, job_id: str) -> list[str]:
        return [d.target for d in self.down.get(job_id, [])]

    def _walk(self, start: str, step) -> dict[str, int]:
        seen: dict[str, int] = {}
        q = deque([(start, 0)])
        while q:
            node, depth = q.popleft()
            for nxt in step(node):
                if nxt not in seen:
                    seen[nxt] = depth + 1
                    q.append((nxt, depth + 1))
        return seen

    def ancestors(self, job_id: str) -> dict[str, int]:
        return self._walk(job_id, self.parents)

    def descendants(self, job_id: str) -> dict[str, int]:
        return self._walk(job_id, self.children)

    def topo_order(self, nodes: set[str]) -> list[str]:
        indeg = {n: 0 for n in nodes}
        for d in self.edges:
            if d.source in nodes and d.target in nodes:
                indeg[d.target] += 1
        q = deque(sorted(n for n, k in indeg.items() if k == 0))
        out = []
        while q:
            n = q.popleft()
            out.append(n)
            for c in self.children(n):
                if c in indeg:
                    indeg[c] -= 1
                    if indeg[c] == 0:
                        q.append(c)
        return out
