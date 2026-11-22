"""Static and runtime findings: each rule finds what was planted in the estate, with its evidence."""
from __future__ import annotations

from conftest import MIS_LINK

from batchiq.analysis.findings import CATEGORY_TITLES
from batchiq.views.findings import findings as filter_findings


def _by_id(estate):
    return {f.id: f for f in estate.a.findings}


def test_every_category_fires_and_has_a_title(estate):
    cats = {f.category for f in estate.a.findings}
    assert cats == set(CATEGORY_TITLES)


def test_dead_condition_on_a_job_that_was_deleted(estate):
    f = _by_id(estate)["st-dead-ctm-prd::CORE_HOUSEKEEPING/HK_ARCHIVE_TXN"]
    assert "CBK_TXN_ARCHIVE_OLD" in f.detail
    assert not estate.a.estate.history_runs(f.job_ids[0]), "a zombie job never runs"


def test_missing_dependency_found_from_code_and_confirmed_by_run_history(estate):
    by = _by_id(estate)
    static = by[f"st-missing-{MIS_LINK}"]
    runtime = by[f"rt-stale-{MIS_LINK}"]
    assert static.severity == runtime.severity == "high"
    assert static.link_id == runtime.link_id == MIS_LINK
    assert runtime.metrics["race_nights"] == 6 and runtime.metrics["nights"] == 30


def test_unmonitored_secret_and_redundant_condition(estate):
    by = _by_id(estate)
    assert "st-unmonitored-autosys-ae1::PAY_FEDWIRE_RECON" in by
    secret = by["st-secret-autosys-ae1::TRS_REPORT_ARCHIVE"]
    assert secret.evidence == ["/opt/trs/bin/archive.sh:7 (plaintext-secret)"]
    leaked = [m.snippet for m in estate.mined["autosys-ae1::TRS_REPORT_ARCHIVE"] if m.object_type == "secret"]
    assert leaked == ['DB_PASSWORD="********"   # TODO move to vault'], "the credential never leaves the miner"
    assert "st-redundant-autosys-ae1::TRS_FX_RATES_LOAD->autosys-ae1::TRS_LIQUIDITY_CALC" in by


def test_single_points_of_failure_and_host_concentration(estate):
    by = _by_id(estate)
    assert by["st-spof-ctm-prd::CORE_BANKING_EOD/CBK_EOD_CUTOFF"].severity == "high"
    assert "zos-prd-01" in by["st-host-zos-prd-01"].title


def test_egress_lists_external_endpoints_only(estate):
    egress = [f for f in estate.a.findings if f.category == "external-egress"]
    assert egress and all(".bank.example" not in e for f in egress for e in f.evidence if "→" in e)


def test_runtime_rules_quantify_what_they_find(estate):
    by = _by_id(estate)
    sensor = by["rt-sensor-airflow-dp::gl_ingest.wait_gl_extract"]
    assert sensor.metrics["median_wait_min"] > 180 and "reschedule" in sensor.recommendation
    trend = by["rt-trend-adf-prd::pl_customer_statements/render_statements"]
    assert trend.metrics["weekly_growth"] > 0.05 and trend.metrics["weeks_to_sla"] is not None
    assert len(trend.metrics["series"]) >= 20
    assert by["rt-fail-airflow-dp::fraud_features.score_model"].metrics["failed_nights"] >= 2
    assert by["rt-queue-autosys-ae1::PAY_ACH_FILE_GEN"].metrics["median_delay_min"] > 5


def test_a_recent_change_shows_up_as_a_race_the_night_after(estate):
    f = _by_id(estate)["rt-stale-ctm-prd::PAYMENTS_SETTLEMENT/PAY_SETTLE_NET->ctm-prd::PAYMENTS_SETTLEMENT/PAY_SETTLE_RECON"]
    assert f.metrics["dates"] == ["2026-11-20"], "only after CHG-1163 removed the condition"


def test_findings_are_sorted_by_severity_within_kind(estate):
    order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    for kind in ("static", "runtime"):
        sev = [order[f.severity] for f in estate.a.findings if f.kind == kind]
        assert sev == sorted(sev)


def test_filters(estate):
    res = filter_findings(estate.a.findings, kind="static", scope="autosys-ae1")
    assert res["findings"] and all(f["kind"] == "static" and f["scope"] == "autosys-ae1" for f in res["findings"])
    assert res["summary"]["total"] == len(estate.a.findings)
    assert filter_findings(estate.a.findings, job="autosys-ae1::MIS_DAILY_PNL")["summary"]["shown"] >= 2


def test_stale_data_insight_for_tonight(estate):
    ins = next(i for i in estate.a.insights if i.id == f"ins-stale-{MIS_LINK}")
    assert ins.type == "stale_data" and ins.severity == "high"
    assert any(r.get("action", {}).get("link_id") == MIS_LINK for r in ins.recommendations)
