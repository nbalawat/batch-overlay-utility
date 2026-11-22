"""HTTP contract for the v2 screens. Review tests run on their own service so they do not leak state."""
from __future__ import annotations

from urllib.parse import quote

import pytest
from conftest import GL_EXTRACT, MIS_LINK
from fastapi.testclient import TestClient

from batchiq.api.app import create_app
from batchiq.api.deps import get_service
from batchiq.service import EstateService
from batchiq.views.onboarding import samples


@pytest.fixture(scope="module")
def api() -> TestClient:
    """A client over a private service instance (reviews change state)."""
    svc = EstateService()
    app = create_app()
    app.dependency_overrides[get_service] = lambda: svc
    c = TestClient(app)
    c.svc = svc  # type: ignore[attr-defined]
    return c


def link_url(lid: str, suffix: str = "") -> str:
    return f"/api/links/{quote(lid, safe='')}{suffix}"


def test_ecosystems(api):
    eco = api.get("/api/ecosystems").json()
    assert [e["id"] for e in eco] == ["ctm-prd", "autosys-ae1", "airflow-dp", "adf-prd"]
    assert sum(e["jobs"] for e in eco) == 61
    d = api.get("/api/ecosystems/autosys-ae1").json()
    assert d["container_kind"] == "box" and {c["name"] for c in d["containers"]} >= {"AML_BOX", "REPORTING_BOX"}
    ext = [n for n in d["graph"]["nodes"] if n["external"]]
    assert ext and all(n["scheduler_id"] != "autosys-ae1" for n in ext)
    assert all(f["scope"] in ("autosys-ae1", "cross") for f in d["findings"])
    assert api.get("/api/ecosystems/nope").status_code == 404


def test_knowledge_graph_endpoints(api):
    o = api.get("/api/kg/ontology").json()
    assert len(o["nodes"]) == 16 and len(o["edges"]) == 18
    assert api.get("/api/kg/search", params={"q": "zos-prd-01"}).json()[0]["id"] == "host:zos-prd-01"
    node = api.get("/api/kg/node", params={"id": "file:gl_extract_{date}.dat"}).json()
    assert {(r["direction"], r["type"]) for r in node["relations"]} == {("in", "WRITES"), ("in", "READS")}
    p = api.get("/api/kg/paths", params={"from": GL_EXTRACT, "to": "process:bp-reg-liquidity"}).json()
    assert p["paths"] and p["paths"][0]["hops"][0]["id"] == GL_EXTRACT
    assert api.get("/api/kg/node", params={"id": "nope"}).status_code == 404
    assert api.get("/api/kg/neighbourhood", params={"id": GL_EXTRACT, "types": "BOGUS"}).status_code == 400


def test_findings_and_changelog(api):
    f = api.get("/api/findings", params={"kind": "runtime", "severity": "high"}).json()
    assert f["findings"] and all(x["kind"] == "runtime" and x["severity"] == "high" for x in f["findings"])
    assert len(api.get("/api/changelog").json()) == 4


def test_link_queue_and_detail(api):
    q = api.get("/api/links", params={"state": "open"}).json()
    assert q["counts"]["approved"] == 7 and q["counts"]["rejected"] == 1
    assert all(c["state"] in ("proposed", "in_review", "needs_info") for c in q["links"])
    d = api.get(link_url(MIS_LINK)).json()
    assert d["state"] == "in_review" and d["race_nights"]["races"] == 6
    teams = {r["team"]: r for r in d["required"]}
    assert teams["data-eng-finance"]["approved"] and not teams["mis-reporting"]["approved"]
    assert teams["mis-reporting"]["members"], "the queue says who can sign off"
    assert "code-artifact-match" in {e["kind"] for e in d["evidence"]}
    assert all(e["source"] and e["detail"] for e in d["evidence"]), "every piece of evidence says where it came from"
    assert api.get(link_url("nope->nope")).status_code == 404


def test_people_inbox(api):
    people = {p["id"]: p for p in api.get("/api/people").json()}
    assert people["coe-lead"]["governance"] is True
    mine = api.get("/api/links", params={"person": "praman"}).json()["links"]
    assert mine and all("data-eng-finance" in [r["team"] for r in c["required"]] for c in mine)


def test_approving_a_link_changes_lineage_and_findings(api):
    svc: EstateService = api.svc  # type: ignore[attr-defined]
    before = {f.id for f in svc.a.findings}
    assert f"st-missing-{MIS_LINK}" in before
    member = api.get(link_url(MIS_LINK)).json()
    who = next(r for r in member["required"] if not r["approved"])["members"][0]["id"]
    r = api.post(link_url(MIS_LINK, "/review"), json={"person": who, "decision": "approve", "comment": "Confirmed"})
    assert r.status_code == 200 and r.json()["state"] == "approved"
    assert svc.a.estate.dependencies()[MIS_LINK].review_state == "confirmed"
    assert "airflow-dp::gl_ingest.publish_gl_mart" in svc.a.graph.parents("autosys-ae1::MIS_DAILY_PNL")
    gap = next(f for f in svc.a.findings if f.id == f"st-missing-{MIS_LINK}")
    assert gap.metrics["review_state"] == "approved", "confirmed in the overlay..."
    assert "scheduler still does not enforce it" in gap.recommendation, "...but the scheduler still races"
    kg_edge = svc.a.kg.edges["airflow-dp::gl_ingest.publish_gl_mart|FEEDS|autosys-ae1::MIS_DAILY_PNL"]
    assert kg_edge.props["review"] == "approved"
    audit = api.get("/api/actions").json()[0]
    assert audit["action"] == "link approve" and audit["dependency_id"] == MIS_LINK


def test_review_errors_are_400s(api):
    lid = next(c["id"] for c in api.get("/api/links", params={"state": "proposed"}).json()["links"])
    r = api.post(link_url(lid, "/review"), json={"person": "rkhan", "decision": "reject", "comment": ""})
    assert r.status_code == 400
    r = api.post(link_url(lid, "/review"), json={"person": "nobody", "decision": "approve"})
    assert r.status_code == 400 and "Unknown reviewer" in r.json()["detail"]
    r = api.post(link_url(lid, "/review"), json={"person": "rkhan", "decision": "maybe"})
    assert r.status_code == 422


def test_rejecting_removes_the_link_from_the_graph(api):
    svc: EstateService = api.svc  # type: ignore[attr-defined]
    card = next(c for c in api.get("/api/links", params={"state": "proposed"}).json()["links"])
    who = card["required"][0]["members"][0]["id"]
    r = api.post(link_url(card["id"], "/review"), json={"person": who, "decision": "reject", "comment": "Not related"})
    assert r.json()["state"] == "rejected"
    assert not any(e.props.get("link_id") == card["id"] for e in svc.a.kg.edges.values())


def test_onboarding_pipeline_and_samples(api):
    ob = api.get("/api/onboarding").json()
    assert ob["totals"]["definitions"] == 61 and ob["totals"]["source_files"] > 50
    assert [s["id"] for s in api.get("/api/onboarding/samples").json()] == ["autosys-ae2", "ctm-mtg", "airflow-reg"]


@pytest.mark.parametrize("sample", samples(), ids=lambda s: s["id"])
def test_import_sandbox_parses_each_dialect_and_links_to_the_estate(api, sample):
    r = api.post("/api/onboarding/import", json={"vendor": sample["vendor"], "content": sample["content"],
                                                  "scheduler_id": sample["scheduler_id"], "name": sample["name"]})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["jobs"] and res["graph"]["nodes"] > len(res["jobs"])
    assert res["proposed_links"], "every sample shares a file or dataset with the live estate"
    assert all((p["source"]["scheduler_id"] == sample["scheduler_id"]) != (p["target"]["scheduler_id"]
               == sample["scheduler_id"]) for p in res["proposed_links"])
    assert sample["scheduler_id"] not in api.svc.a.estate.schedulers, "the sandbox never changes the estate"  # type: ignore[attr-defined]


def test_import_sandbox_reports_problems_in_the_export(api):
    s = next(x for x in samples() if x["id"] == "autosys-ae2")
    res = api.post("/api/onboarding/import", json={"vendor": "autosys", "content": s["content"],
                                                    "scheduler_id": "ae2-test"}).json()
    assert any("WLT_PRICING_SNAPSHOT" in c["message"] for c in res["checks"])
    assert res["proposed_links"][0]["source"]["name"] == "CBK_BAL_SNAPSHOT"


@pytest.mark.parametrize("body,msg", [
    ({"vendor": "control-m", "content": "{not json", "scheduler_id": "x-1"}, "Expected JSON"),
    ({"vendor": "autosys", "content": "nothing here", "scheduler_id": "x-2"}, "No jobs"),
    ({"vendor": "airflow", "content": "{}", "scheduler_id": "x-3"}, "Could not read"),
    ({"vendor": "autosys", "content": "insert_job: A job_type: CMD", "scheduler_id": "ctm-prd"}, "already connected"),
])
def test_import_sandbox_rejects_bad_input(api, body, msg):
    r = api.post("/api/onboarding/import", json=body)
    assert r.status_code == 400 and msg in r.json()["detail"]
