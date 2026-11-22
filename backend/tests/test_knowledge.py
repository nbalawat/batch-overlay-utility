"""Knowledge graph: schema, provenance, what each layer contributes, queries, and change tracking."""
from __future__ import annotations

import re

import pytest
from conftest import GL_EXTRACT, MIS_LINK, MIS_PNL, PUBLISH_GL_MART

from batchiq.knowledge.changes import diff
from batchiq.knowledge.graph import KnowledgeGraph, SchemaError
from batchiq.knowledge.ontology import EDGE_SPECS, EdgeType, NodeType, Provenance, allowed
from batchiq.views import knowledge as kgv

E, N, P = EdgeType, NodeType, Provenance


def test_schema_rejects_edges_the_ontology_does_not_allow():
    g = KnowledgeGraph()
    g.node("j", N.JOB, "J")
    g.node("h", N.HOST, "H")
    g.edge("j", E.RUNS_ON, "h", P.DEFINITION)
    with pytest.raises(SchemaError):
        g.edge("h", E.FEEDS, "j", P.DEFINITION)


def test_every_edge_in_the_live_graph_is_valid_and_has_provenance(estate):
    kg = estate.a.kg
    assert set(EDGE_SPECS) == set(E)
    for e in kg.edges.values():
        assert allowed(e.type, kg.nodes[e.source].type, kg.nodes[e.target].type), e.id
        assert e.provenance, e.id
    st = kg.stats()
    assert set(st["nodes_by_type"]) == {t.value for t in N}, "every node type is populated"
    assert set(st["edges_by_provenance"]) == {p.value for p in P}, "every provenance is populated"


def test_edges_merge_provenance_from_several_layers(estate):
    kg = estate.a.kg
    # Declared machine and observed runtime host agree: one edge, two provenances.
    e = kg.edges[f"{GL_EXTRACT}|RUNS_ON|host:zos-prd-01"]
    assert {P.DEFINITION, P.RUNTIME} <= e.provenance and e.props["runs"] >= 25


def test_code_layer_reveals_what_definitions_do_not(estate):
    kg = estate.a.kg
    code = [e for e in kg.edges.values() if P.CODE in e.provenance]
    assert {e.type for e in code} >= {E.READS, E.WRITES, E.TRANSFERS_TO, E.NOTIFIES, E.CALLS, E.PUBLISHES}
    assert all(any(re.search(r":\d+$", r) for r in e.refs) for e in code), "code edges cite path:line"
    # MIS_DAILY_PNL's definition only names a script; its SQL is what reads finance.gl_mart.
    reads = kg.edges[f"{MIS_PNL}|READS|data:finance.gl_mart"]
    assert reads.provenance == {P.CODE}
    secret = [n for n in kg.nodes.values() if n.props.get("plaintext_credential")]
    assert [n.label for n in secret] == ["TRS_REPORT_ARCHIVE"]


def test_links_carry_review_state(estate):
    kg = estate.a.kg
    mis = kg.edges[f"{PUBLISH_GL_MART}|FEEDS|{MIS_PNL}"]
    assert mis.provenance == {P.PROPOSED} and mis.props["review"] == "in_review" and mis.props["link_id"] == MIS_LINK
    assert not any(e.props.get("review") == "rejected" for e in kg.edges.values()), "rejected links are left out"
    approved = [e for e in kg.edges.values() if P.APPROVED in e.provenance]
    assert len(approved) == 7


def test_business_layer_connects_jobs_to_processes_and_services(estate):
    kg = estate.a.kg
    assert any(e.type == E.DELIVERS and e.target == "process:bp-reg-liquidity" for e in kg.edges.values())
    assert any(e.type == E.SUPPORTS for e in kg.edges_of("process:bp-reg-liquidity", "out"))
    assert kg.edges.get(f"{GL_EXTRACT}|PART_OF|process:bp-reg-liquidity")


def test_paths_cross_ecosystems_to_a_business_process(estate):
    res = kgv.paths(estate.a.kg, GL_EXTRACT, "process:bp-reg-liquidity", types="FEEDS,DELIVERS")
    longest = max(res["paths"], key=lambda p: len(p["hops"]))
    vendors = {h["props"].get("vendor") for h in longest["hops"] if h["type"] == "Job"}
    assert len(vendors) >= 2 and longest["hops"][-1]["type"] == "BusinessProcess"
    assert all(e["type"] in ("FEEDS", "DELIVERS") for p in res["paths"] for e in p["edges"])


def test_host_neighbourhood_lists_what_runs_there(estate):
    nb = kgv.neighbourhood(estate.a.kg, "host:zos-prd-01", types="RUNS_ON")
    jobs = [n for n in nb["nodes"] if n["type"] == "Job"]
    assert len(jobs) >= 5 and all(n["props"]["vendor"] == "control-m" for n in jobs)


def test_search_and_unknown_nodes(estate):
    hits = kgv.search(estate.a.kg, "gl_extract")
    assert hits[0]["id"] == "file:gl_extract_{date}.dat"
    with pytest.raises(kgv.UnknownNode):
        kgv.node(estate.a.kg, "nope")


def test_ontology_counts_match_the_graph(estate):
    o = kgv.ontology(estate.a.kg)
    assert sum(n["count"] for n in o["nodes"]) == len(estate.a.kg.nodes)
    assert sum(e["count"] for e in o["edges"]) == len(estate.a.kg.edges)


# ---------------------------------------------------------------------- change tracking
def _tiny(host: str, extra_job: bool = False) -> KnowledgeGraph:
    g = KnowledgeGraph()
    g.node("j", N.JOB, "J", scheduler_id="s", container="C")
    g.node(f"host:{host}", N.HOST, host)
    g.edge("j", E.RUNS_ON, f"host:{host}", P.DEFINITION)
    if extra_job:
        g.node("k", N.JOB, "K", scheduler_id="s", container="C")
        g.edge("j", E.FEEDS, "k", P.DEFINITION)
    return g


def test_diff_reports_moves_additions_and_new_links():
    changes = {c.name: c for c in diff(_tiny("a"), _tiny("b", extra_job=True))}
    assert changes["K"].kind == "added"
    assert changes["J"].details == ["+ feeds K", "+ runs on b", "− runs on a"]


def test_changelog_replays_each_change_with_its_ticket(estate):
    log = estate.changelog_entries
    assert [e["business_date"] for e in log] == ["2026-11-20", "2026-11-19", "2026-11-17", "2026-11-14"]
    by_ticket = {c["change"]["id"]: c for e in log for c in e["changes"] if c["change"]}
    assert by_ticket["CHG-1107"]["details"] == ["+ runs on trs-lnx-01", "− runs on trs-lnx-02"]
    assert by_ticket["CHG-1163"]["details"] == ["+ schedule Daily 02:00", "− condition on PAY_SETTLE_NET"]
    assert by_ticket["CHG-1142"]["kind"] == "added"
    assert by_ticket["CHG-1170"]["details"] == ["+ schedule Daily 01:30", "− schedule Daily 00:30"]
    # The removed condition left a gap the recommender now proposes to close.
    assert any(f["link_id"].endswith("PAY_SETTLE_RECON") for f in by_ticket["CHG-1163"]["follow_ups"])
