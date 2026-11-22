"""End-to-end tests over the simulated estate (no network, no LLM)."""
from __future__ import annotations

import os

os.environ.setdefault("BATCHIQ_TODAY", "2026-11-22")
os.environ["LLM_PROVIDER"] = "offline"

import pytest
from fastapi.testclient import TestClient

from batchiq.adapters.autosys.adapter import parse_jil
from batchiq.api.app import create_app
from batchiq.core.artifacts import file_artifact
from batchiq.service import EstateService


@pytest.fixture(scope="module")
def svc() -> EstateService:
    return EstateService()


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


def test_canonical_artifacts_match_across_dialects():
    ctm = file_artifact("/xfer/gl/gl_extract_%%ODATE.dat")
    af = file_artifact("/xfer/gl/gl_extract_{{ ds_nodash }}.dat")
    asys = file_artifact("/xfer/gl/gl_extract_$$(BUSDATE).dat")
    assert ctm.canonical == af.canonical == asys.canonical == "file:gl_extract_{date}.dat"


def test_jil_parser():
    jobs = parse_jil("insert_job: A   job_type: CMD\ncommand: run.sh --out /x/a.dat\ncondition: s(B)\n")
    assert jobs[0]["insert_job"] == "A" and jobs[0]["condition"] == "s(B)"


def test_all_connectors_normalise(svc):
    vendors = {j.vendor.value for j in svc.a.estate.jobs().values()}
    assert vendors == {"control-m", "airflow", "autosys", "azure-data-factory"}
    assert len(svc.a.estate.jobs()) >= 35


def test_cross_scheduler_links_found(svc):
    deps = svc.a.estate.dependencies()
    assert "ctm-prd::CORE_BANKING_EOD/CBK_GL_EXTRACT->airflow-dp::gl_ingest.wait_gl_extract" in deps
    assert deps["ctm-prd::PAYMENTS_SETTLEMENT/PAY_SETTLE_NET->autosys-ae1::PAY_ACH_FILE_GEN"].origin == "artifact"
    hidden = deps["airflow-dp::fraud_features.publish_scores->adf-prd::pl_customer360_refresh/c360_merge"]
    assert hidden.origin == "inferred" and hidden.review_state == "suggested"
    assert {e.kind for e in hidden.evidence} == {"data-name-match", "temporal"}


def test_process_spans_schedulers(svc):
    brief = svc.process_brief("bp-reg-liquidity")
    assert set(brief["jobs_by_scheduler"]) == {"ctm-prd", "airflow-dp", "autosys-ae1"}


def test_default_scenario_flags_sla_risk_and_root_cause(svc):
    fc = svc.a.proc_fc["bp-reg-liquidity"]
    assert fc.status == "breach-likely"
    sla = next(i for i in svc.a.insights if i.id == "ins-sla-bp-reg-liquidity")
    assert sla.root_cause[0]["job_id"] == "ctm-prd::CORE_BANKING_EOD/CBK_GL_EXTRACT"
    assert sla.similar_incidents[0]["id"] == "INC-20260914-0412"
    assert svc.a.proc_fc["bp-payments-settlement"].status == "done"


def test_harmless_anomaly_is_low_severity(svc):
    fx = next(i for i in svc.a.insights if i.id.startswith("ins-anom-TRS_FX_RATES_LOAD"))
    assert fx.severity == "low"


def test_healthy_night_has_no_risk():
    s = EstateService()
    s.load("healthy-night")
    assert all(f.status in ("done", "on-track") for f in s.a.proc_fc.values())


def test_api_roundtrip(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    ov = client.get("/api/overview").json()
    assert ov["kpis"]["cross_scheduler_links"] >= 6
    job = client.get("/api/jobs/airflow-dp::gl_ingest.wait_gl_extract").json()
    assert job["upstream"][0]["dependency"]["cross_scheduler"] is True
    r = client.post("/api/actions", json={"action": "boost_priority",
                                          "job_id": "airflow-dp::gl_ingest.load_raw_gl"}).json()
    assert r["receipt"]["simulated"] is True and "airflow pools set" in r["command"]
    ans = client.post("/api/assistant/ask", json={"question": "Why is regulatory reporting at risk?"}).json()
    assert "Regulatory" in ans["answer"] and ans["tool_trace"]


def test_native_payloads_exposed(client):
    jil = client.get("/api/connectors/autosys-ae1/native").json()["definitions"]
    assert "insert_job: PAY_ACH_FILE_GEN" in jil
