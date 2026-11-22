from __future__ import annotations

import os

os.environ.setdefault("BATCHIQ_TODAY", "2026-11-22")
os.environ["LLM_PROVIDER"] = "offline"

import pytest

from batchiq.service import EstateService


@pytest.fixture(scope="session")
def estate() -> EstateService:
    """A read-only service shared by tests that do not change state. Tests that review links build their own."""
    return EstateService()


GL_EXTRACT = "ctm-prd::CORE_BANKING_EOD/CBK_GL_EXTRACT"
PUBLISH_GL_MART = "airflow-dp::gl_ingest.publish_gl_mart"
MIS_PNL = "autosys-ae1::MIS_DAILY_PNL"
MIS_LINK = f"{PUBLISH_GL_MART}->{MIS_PNL}"
