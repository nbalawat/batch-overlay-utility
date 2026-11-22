"""Demo scenarios: what goes wrong tonight, and what time it is now."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time


@dataclass(frozen=True)
class FailAndRerun:
    job: str                 # spec key
    fail_after_min: float
    error_code: str
    message: str
    rerun_at: time | None    # None = not yet rerun


@dataclass(frozen=True)
class SlowDown:
    job: str
    factor: float
    reason: str = ""


@dataclass(frozen=True)
class Scenario:
    id: str
    name: str
    summary: str
    clock: time
    failures: tuple[FailAndRerun, ...] = ()
    slowdowns: tuple[SlowDown, ...] = ()
    talking_points: tuple[str, ...] = field(default_factory=tuple)


SCENARIOS: dict[str, Scenario] = {
    s.id: s for s in (
        Scenario(
            id="gl-extract-abend",
            name="GL extract abend puts regulatory filing at risk",
            summary=("A Control-M mainframe job (CBK_GL_EXTRACT) abended with S0C7 shortly before 03:00. The rerun is "
                     "in flight. Nothing in Airflow has failed yet, but its GL and regulatory DAGs are now "
                     "projected to miss their SLAs. A treasury job in AutoSys is also running slowly, but "
                     "that one has no business impact."),
            clock=time(3, 25),
            failures=(FailAndRerun("ctm-prd::CORE_BANKING_EOD/CBK_GL_EXTRACT", 26, "S0C7",
                                   "IEA995I SYMPTOM DUMP OUTPUT  SYSTEM COMPLETION CODE=0C7 "
                                   "STEP GLX020 - DATA EXCEPTION IN PACKED DECIMAL FIELD GL-AMT",
                                   time(3, 5)),),
            slowdowns=(SlowDown("autosys-ae1::TRS_FX_RATES_LOAD", 3.2, "vendor feed latency"),),
            talking_points=(
                "Each scheduler's own console shows only part of the problem: Control-M shows one abend, "
                "and Airflow shows a sensor that is still waiting.",
                "The overlay links the abend to the Airflow sensor through the GL extract file, then on to "
                "two business processes.",
                "Monte Carlo forecasting puts the regulatory filing at high risk of missing 07:00.",
                "The knowledge base finds two past S0C7 incidents on the same job, with their fixes.",
            ),
        ),
        Scenario(
            id="warehouse-contention",
            name="Warehouse contention slows the GL close",
            summary=("Control-M finishes cleanly, but Airflow's load into Snowflake WH_FINANCE runs at 2.6 "
                     "times its normal duration. Nothing has failed, yet the SLA is drifting."),
            clock=time(4, 35),
            slowdowns=(SlowDown("airflow-dp::gl_ingest.load_raw_gl", 2.6, "warehouse contention"),),
            talking_points=(
                "No job has failed, so a traditional monitoring tool raises no alert.",
                "Anomaly detection flags the duration drift, and the forecast shows its effect on the SLA.",
                "Root-cause hints point at the shared warehouse, matching a similar incident from October.",
            ),
        ),
        Scenario(
            id="healthy-night",
            name="Healthy night (baseline)",
            summary="Everything runs within normal bounds. Use this as the baseline for the demo.",
            clock=time(4, 30),
        ),
    )
}

DEFAULT_SCENARIO = "gl-extract-abend"
