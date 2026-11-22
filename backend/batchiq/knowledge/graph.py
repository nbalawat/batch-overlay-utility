"""In-memory property graph with provenance on every edge.

The port is small on purpose: add nodes and edges (validated against the
ontology), and query neighbourhoods, paths and searches. A production build
backs the same interface with Apache AGE (openCypher on Postgres) or Neo4j.
"""
from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

from batchiq.knowledge.ontology import EdgeType, NodeType, Provenance, allowed


@dataclass
class Node:
    id: str
    type: NodeType
    label: str
    props: dict[str, Any] = field(default_factory=dict)


@dataclass
class Edge:
    source: str
    type: EdgeType
    target: str
    provenance: set[Provenance] = field(default_factory=set)
    confidence: float = 1.0
    refs: list[str] = field(default_factory=list)       # where it came from: "JIL", "path:line", "link review"
    props: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return f"{self.source}|{self.type.value}|{self.target}"


class SchemaError(ValueError):
    pass


class KnowledgeGraph:
    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.edges: dict[str, Edge] = {}
        self.out: dict[str, list[str]] = defaultdict(list)
        self.inc: dict[str, list[str]] = defaultdict(list)

    # ------------------------------------------------------------------ writes
    def node(self, nid: str, type_: NodeType, label: str, **props: Any) -> Node:
        n = self.nodes.get(nid)
        if n is None:
            n = self.nodes[nid] = Node(nid, type_, label, {})
        n.props.update({k: v for k, v in props.items() if v is not None})
        return n

    def edge(self, source: str, type_: EdgeType, target: str, provenance: Provenance, *, confidence: float = 1.0,
             ref: str | None = None, **props: Any) -> Edge:
        s, t = self.nodes[source], self.nodes[target]
        if not allowed(type_, s.type, t.type):
            raise SchemaError(f"{type_} not allowed from {s.type} to {t.type}")
        key = f"{source}|{type_.value}|{target}"
        e = self.edges.get(key)
        if e is None:
            e = self.edges[key] = Edge(source, type_, target, set(), confidence)
            self.out[source].append(key)
            self.inc[target].append(key)
        else:
            e.confidence = max(e.confidence, confidence)
        e.provenance.add(provenance)
        if ref and ref not in e.refs:
            e.refs.append(ref)
        e.props.update({k: v for k, v in props.items() if v is not None})
        return e

    # ------------------------------------------------------------------ reads
    def edges_of(self, nid: str, direction: str = "both", types: set[EdgeType] | None = None) -> list[Edge]:
        keys = (self.out.get(nid, []) if direction in ("out", "both") else []) + \
               (self.inc.get(nid, []) if direction in ("in", "both") else [])
        return [self.edges[k] for k in keys if types is None or self.edges[k].type in types]

    def neighbours(self, nid: str, depth: int = 1, types: set[EdgeType] | None = None,
                   max_nodes: int = 150) -> tuple[set[str], list[Edge]]:
        seen = {nid}
        frontier = [nid]
        edges: dict[str, Edge] = {}
        for _ in range(depth):
            nxt = []
            for n in frontier:
                for e in self.edges_of(n, types=types):
                    edges[e.id] = e
                    other = e.target if e.source == n else e.source
                    if other not in seen and len(seen) < max_nodes:
                        seen.add(other)
                        nxt.append(other)
            frontier = nxt
        return seen, [e for e in edges.values() if e.source in seen and e.target in seen]

    def paths(self, a: str, b: str, max_depth: int = 12, types: set[EdgeType] | None = None,
              directed: bool = True, limit: int = 5) -> list[list[Edge]]:
        """Shortest paths first (BFS), following edge direction unless directed=False."""
        out: list[list[Edge]] = []
        q: deque[tuple[str, list[Edge]]] = deque([(a, [])])
        best: dict[str, int] = {a: 0}
        while q and len(out) < limit:
            n, path = q.popleft()
            if len(path) >= max_depth:
                continue
            for e in self.edges_of(n, "out" if directed else "both", types):
                other = e.target if e.source == n else e.source
                if any(other in (x.source, x.target) for x in path) or other == a:
                    continue
                np = path + [e]
                if other == b:
                    out.append(np)
                    continue
                if best.get(other, 1 << 30) >= len(np):
                    best[other] = len(np)
                    q.append((other, np))
        return out

    def search(self, q: str, types: set[NodeType] | None = None, limit: int = 25) -> list[Node]:
        ql = q.lower().strip()
        scored = []
        for n in self.nodes.values():
            if types and n.type not in types:
                continue
            hay = f"{n.id} {n.label}".lower()
            if ql in hay:
                scored.append((0 if n.label.lower() == ql else 1 if n.label.lower().startswith(ql) else 2, n))
        scored.sort(key=lambda x: (x[0], len(x[1].label)))
        return [n for _, n in scored[:limit]]

    def stats(self) -> dict[str, Any]:
        prov: Counter[str] = Counter()
        for e in self.edges.values():
            for p in e.provenance:
                prov[p.value] += 1
        return {"nodes": len(self.nodes), "edges": len(self.edges),
                "nodes_by_type": dict(Counter(n.type.value for n in self.nodes.values())),
                "edges_by_type": dict(Counter(e.type.value for e in self.edges.values())),
                "edges_by_provenance": dict(prov)}
