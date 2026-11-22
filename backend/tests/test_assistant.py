"""Offline assistant: layered and ecosystem-scoped questions route to the right tools and cite facts."""
from __future__ import annotations

import json

import pytest

from batchiq.assistant.agent import Assistant
from batchiq.assistant.tools import TOOLS, ToolBox


@pytest.fixture(scope="module")
def assistant(estate) -> Assistant:
    return Assistant(estate)


@pytest.mark.parametrize("question,tool,must", [
    ("What would break if zos-prd-01 went down?", "host_outage_impact", ["CBK_GL_EXTRACT", "Regulatory liquidity"]),
    ("Which jobs send emails?", "find_communications", ["cfo-office@bank.example", "daily_pnl.sh:"]),
    ("What data leaves the bank?", "find_communications", ["fedline.frb.example", "(external)"]),
    ("Which AutoSys jobs fail silently?", "list_findings", ["PAY_FEDWIRE_RECON"]),
    ("What does MIS_DAILY_PNL depend on?", "trace_lineage", ["no confirmed jobs upstream", "publish_gl_mart (88%)"]),
    ("What depends on CBK_GL_EXTRACT downstream?", "trace_lineage", ["wait_gl_extract (Airflow)"]),
    ("How does CBK_GL_EXTRACT connect to regulatory reporting?", "find_path",
     ["wait_gl_extract (Airflow)", "submit_regulator_portal"]),
    ("Which links are waiting for review?", "list_link_candidates", ["publish_scores (Airflow) → c360_merge (ADF)"]),
    ("What changed this week?", "list_changes", ["CHG0041163", "PAY_SETTLE_RECON"]),
    ("Who reads finance.gl_mart?", "describe_entity", ["MIS_DAILY_PNL (AutoSys) [code]"]),
    ("What does AutoSys depend on outside itself?", "get_ecosystem", ["Links across its boundary", "4 boxes"]),
    ("Where can we improve runtime in Airflow?", "list_findings", ["pokes for 3.8 hours"]),
    ("Which jobs does the fraud team own?", "describe_entity", ["score_model", "People:"]),
    ("Why is regulatory reporting at risk?", "get_root_cause", ["CBK_GL_EXTRACT", "S0C7"]),
])
def test_offline_routes(assistant, question, tool, must):
    r = assistant.ask(question)
    assert tool in [t["tool"] for t in r.tool_trace], r.tool_trace
    for m in must:
        assert m in r.answer, f"{m!r} missing from: {r.answer}"


def test_every_tool_is_exposed_to_the_llm_with_a_valid_schema(estate):
    names = [t.name for t in TOOLS]
    assert len(names) == len(set(names)) == 17
    for t in TOOLS:
        assert t.parameters["type"] == "object" and set(t.parameters["required"]) <= set(t.parameters["properties"])


def test_tools_return_json_and_errors_not_exceptions(estate):
    tb = ToolBox(estate)
    assert "error" in json.loads(tb.execute("host_outage_impact", {"host": "no-such-host"}))
    assert "error" in json.loads(tb.execute("find_path", {"source": "nope", "target": "nope2"}))
    assert "error" in json.loads(tb.execute("get_ecosystem", {"scheduler": "tidal"}))
    eco = json.loads(tb.execute("get_ecosystem", {"scheduler": "Control-M"}))
    assert eco["id"] == "ctm-prd" and "HK_ARCHIVE_TXN" in json.dumps(eco["unresolved"])
