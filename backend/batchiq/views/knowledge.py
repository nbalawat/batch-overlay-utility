"""Knowledge graph explorer: the ontology, search, neighbourhoods and paths."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from batchiq.knowledge.graph import KnowledgeGraph
from batchiq.knowledge.ontology import EDGES, NODES, PROVENANCE_HELP, EdgeType, NodeType
from batchiq.views.common import edge_dict, node_dict


class UnknownNode(KeyError):
    pass


def _edge_types(types: str | None) -> set[EdgeType] | None:
    if not types:
        return None
    return {EdgeType(t.strip().upper()) for t in types.split(",") if t.strip()}


def ontology(kg: KnowledgeGraph) -> dict[str, Any]:
    st = kg.stats()
    return {
        "nodes": [{"type": n.type.value, "description": n.description, "examples": n.examples,
                   "count": st["nodes_by_type"].get(n.type.value, 0)} for n in NODES],
        "edges": [{"type": e.type.value, "source": [s.value for s in e.source], "target": [t.value for t in e.target],
                   "description": e.description, "count": st["edges_by_type"].get(e.type.value, 0)} for e in EDGES],
        "provenance": [{"id": p.value, "description": d, "count": st["edges_by_provenance"].get(p.value, 0)}
                       for p, d in PROVENANCE_HELP.items()],
        "stats": {"nodes": st["nodes"], "edges": st["edges"]}}


def search(kg: KnowledgeGraph, q: str, type_: str | None = None, limit: int = 25) -> list[dict[str, Any]]:
    types = {NodeType(type_)} if type_ else None
    return [{**node_dict(n), "degree": len(kg.edges_of(n.id))} for n in kg.search(q, types, limit)]


def node(kg: KnowledgeGraph, nid: str) -> dict[str, Any]:
    if nid not in kg.nodes:
        raise UnknownNode(nid)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in kg.edges_of(nid):
        out = e.source == nid
        other = kg.nodes[e.target if out else e.source]
        groups[f"{'out' if out else 'in'}:{e.type.value}"].append({**edge_dict(e), "other": node_dict(other)})
    return {"node": node_dict(kg.nodes[nid]),
            "relations": [{"direction": k.split(":")[0], "type": k.split(":")[1], "edges": v}
                          for k, v in sorted(groups.items())]}


def neighbourhood(kg: KnowledgeGraph, nid: str, depth: int = 1, types: str | None = None,
                  max_nodes: int = 120) -> dict[str, Any]:
    if nid not in kg.nodes:
        raise UnknownNode(nid)
    nodes, edges = kg.neighbours(nid, min(depth, 4), _edge_types(types), max_nodes)
    return {"center": nid, "nodes": [node_dict(kg.nodes[n]) for n in sorted(nodes)],
            "edges": [edge_dict(e) for e in edges], "truncated": len(nodes) >= max_nodes}


def paths(kg: KnowledgeGraph, a: str, b: str, directed: bool = True, types: str | None = None,
          limit: int = 5) -> dict[str, Any]:
    for x in (a, b):
        if x not in kg.nodes:
            raise UnknownNode(x)
    found = kg.paths(a, b, types=_edge_types(types), directed=directed, limit=limit)
    out, seen = [], set()
    for p in found:
        hops, cur = [a], a
        for e in p:
            cur = e.target if e.source == cur else e.source
            hops.append(cur)
        if tuple(hops) in seen:          # parallel edges (e.g. DELIVERS and PART_OF) give the same route
            continue
        seen.add(tuple(hops))
        out.append({"hops": [node_dict(kg.nodes[h]) for h in hops], "edges": [edge_dict(e) for e in p]})
    return {"from": node_dict(kg.nodes[a]), "to": node_dict(kg.nodes[b]), "directed": directed, "paths": out}
