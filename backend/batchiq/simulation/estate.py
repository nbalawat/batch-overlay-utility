"""Ground truth for the simulated enterprise batch estate.

This module describes a fictional bank's overnight batch as it *really* runs:
which scheduler owns each job, what it reads and writes, and how long it takes.
The vendor simulators render this into each scheduler's native API format. The
overlay never reads this module directly: it only sees what the adapters
extract, exactly as it would at a client.

`hidden_after` models real-world coupling that no scheduler declares (for
example an event fired from inside a script). The correlation engine has to
infer it from run history and artifact names.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import time

from batchiq.domain.models import JobKind, Vendor


@dataclass(frozen=True)
class JobSpec:
    vendor: Vendor
    scheduler_id: str
    container: str
    name: str
    minutes: float                       # median duration
    jitter: float = 0.12                 # log-normal sigma
    after: tuple[str, ...] = ()          # same-scheduler predecessors (by name)
    produces: tuple[str, ...] = ()       # artifacts, with {date} placeholder
    consumes: tuple[str, ...] = ()
    at: time | None = None               # scheduled start
    kind: JobKind = JobKind.COMMAND
    host: str = ""
    app: str = ""
    owner: str = ""
    command: str = ""
    hidden_after: tuple[str, ...] = ()   # undeclared upstream (spec keys)
    description: str = ""

    @property
    def key(self) -> str:
        return f"{self.scheduler_id}::{self.container}/{self.name}" if self.vendor in (
            Vendor.CONTROL_M, Vendor.ADF) else (
            f"{self.scheduler_id}::{self.container}.{self.name}" if self.vendor == Vendor.AIRFLOW
            else f"{self.scheduler_id}::{self.name}")


@dataclass(frozen=True)
class SchedulerSpec:
    id: str
    vendor: Vendor
    name: str
    environment: str
    endpoint: str
    description: str


SCHEDULERS: tuple[SchedulerSpec, ...] = (
    SchedulerSpec("ctm-prd", Vendor.CONTROL_M, "Control-M (Mainframe & Core Banking)", "PROD",
                  "https://ctm-em.bank.example:8443/automation-api",
                  "Core banking end-of-day on z/OS, payments settlement"),
    SchedulerSpec("autosys-ae1", Vendor.AUTOSYS, "AutoSys AE1 (Payments & Treasury)", "PROD",
                  "https://autosys-ae1.bank.example:9443/AEWS",
                  "Distributed Linux batch for payments and treasury"),
    SchedulerSpec("airflow-dp", Vendor.AIRFLOW, "Airflow (Enterprise Data Platform)", "PROD",
                  "https://airflow.dataplatform.bank.example/api/v1",
                  "Warehouse ingestion, regulatory and risk analytics"),
    SchedulerSpec("adf-prd", Vendor.ADF, "Azure Data Factory (Customer Cloud)", "PROD",
                  "https://management.azure.com/.../factories/adf-cust-prd",
                  "Cloud-native customer communications and C360"),
)

CTM, AS, AF, ADF = Vendor.CONTROL_M, Vendor.AUTOSYS, Vendor.AIRFLOW, Vendor.ADF


def _ctm(folder: str, name: str, minutes: float, **kw) -> JobSpec:
    return JobSpec(CTM, "ctm-prd", folder, name, minutes, **kw)


def _as(box: str, name: str, minutes: float, **kw) -> JobSpec:
    return JobSpec(AS, "autosys-ae1", box, name, minutes, **kw)


def _af(dag: str, task: str, minutes: float, **kw) -> JobSpec:
    return JobSpec(AF, "airflow-dp", dag, task, minutes, **kw)


def _adf(pipe: str, activity: str, minutes: float, **kw) -> JobSpec:
    return JobSpec(ADF, "adf-prd", pipe, activity, minutes, **kw)


JOBS: tuple[JobSpec, ...] = (
    # ---------------------------------------------------------- Control-M
    _ctm("CORE_BANKING_EOD", "CBK_EOD_CUTOFF", 6, at=time(23, 30), host="zos-prd-01", app="CORE",
         owner="core-batch-ops", command="//CBKEOD01 JOB (ACCT),'EOD CUTOFF'"),
    _ctm("CORE_BANKING_EOD", "CBK_TXN_POSTING", 110, after=("CBK_EOD_CUTOFF",),
         produces=("file:/xfer/core/txn_posted_{date}.dat",), host="zos-prd-01", app="CORE",
         owner="core-batch-ops", command="//CBKTXN02 JOB (ACCT),'TXN POSTING'"),
    _ctm("CORE_BANKING_EOD", "CBK_INTEREST_ACCRUAL", 45, after=("CBK_TXN_POSTING",), host="zos-prd-01",
         app="CORE", owner="core-batch-ops", command="//CBKINT03 JOB (ACCT),'INT ACCRUAL'"),
    _ctm("CORE_BANKING_EOD", "CBK_GL_EXTRACT", 50, after=("CBK_INTEREST_ACCRUAL",),
         produces=("file:/xfer/gl/gl_extract_{date}.dat",), host="zos-prd-01", app="CORE",
         owner="core-batch-ops", command="//CBKGLX04 JOB (ACCT),'GL EXTRACT'"),
    _ctm("CORE_BANKING_EOD", "CBK_BAL_SNAPSHOT", 20, after=("CBK_TXN_POSTING",),
         produces=("file:/xfer/core/balances_{date}.dat",), host="zos-prd-01", app="CORE",
         owner="core-batch-ops", command="//CBKBAL05 JOB (ACCT),'BAL SNAPSHOT'"),
    _ctm("CORE_BANKING_EOD", "CBK_STMT_EXTRACT", 35, after=("CBK_INTEREST_ACCRUAL",),
         produces=("file:/xfer/stmt/stmt_extract_{date}.dat",), host="zos-prd-02", app="CORE",
         owner="core-batch-ops", command="//CBKSTM06 JOB (ACCT),'STMT EXTRACT'"),
    _ctm("CORE_BANKING_EOD", "CBK_DB_REORG", 25, at=time(23, 45), host="zos-prd-02", app="CORE-HK",
         owner="dba-mainframe", command="//CBKREO09 JOB (ACCT),'DB2 REORG'"),
    _ctm("PAYMENTS_SETTLEMENT", "PAY_SETTLE_NET", 25, after=(), hidden_after=(),
         consumes=("file:/xfer/core/txn_posted_{date}.dat",),
         produces=("file:/xfer/pay/settlement_{date}.dat",), host="zos-prd-01", app="PAYMENTS",
         owner="payments-ops", command="//PAYSET01 JOB (ACCT),'NET SETTLEMENT'"),
    _ctm("PAYMENTS_SETTLEMENT", "PAY_SETTLE_RECON", 20, after=("PAY_SETTLE_NET",), host="zos-prd-01",
         app="PAYMENTS", owner="payments-ops", command="//PAYREC02 JOB (ACCT),'SETTLE RECON'"),

    # ---------------------------------------------------------- AutoSys
    _as("PAY_BOX", "PAY_SWIFT_INGEST", 25, at=time(23, 0), host="pay-lnx-01", app="PAYMENTS",
        owner="payments-ops", command="/opt/pay/bin/swift_ingest.sh --channel MT103"),
    _as("PAY_BOX", "PAY_ACH_FILE_GEN", 20, after=("PAY_SWIFT_INGEST",),
        consumes=("file:/xfer/pay/settlement_{date}.dat",), produces=("file:/out/ach/nacha_{date}.ach",),
        host="pay-lnx-02", app="PAYMENTS", owner="payments-ops",
        command="/opt/pay/bin/ach_gen.sh"),
    _as("PAY_BOX", "PAY_NACHA_TRANSMIT", 10, after=("PAY_ACH_FILE_GEN",), host="pay-lnx-02",
        app="PAYMENTS", owner="payments-ops", command="/opt/pay/bin/fed_transmit.sh --rail ACH"),
    _as("TRS_BOX", "TRS_FX_RATES_LOAD", 15, at=time(23, 0), host="trs-lnx-01", app="TREASURY",
        owner="treasury-tech", command="/opt/trs/bin/fx_rates_load.sh --source REFINITIV"),
    _as("TRS_BOX", "TRS_POSITION_LOAD", 35, after=("TRS_FX_RATES_LOAD",),
        consumes=("file:/xfer/core/balances_{date}.dat",), host="trs-lnx-01", app="TREASURY",
        owner="treasury-tech", command="/opt/trs/bin/position_load.sh"),
    _as("TRS_BOX", "TRS_LIQUIDITY_CALC", 40, after=("TRS_POSITION_LOAD",),
        produces=("file:/data/treasury/liquidity_{date}.csv",), host="trs-lnx-02", app="TREASURY",
        owner="treasury-tech", command="/opt/trs/bin/liquidity_calc.sh"),
    _as("TRS_BOX", "TRS_REPORT_ARCHIVE", 8, at=time(1, 0), host="trs-lnx-02", app="TREASURY-HK",
        owner="treasury-tech", command="/opt/trs/bin/archive.sh --days 90"),

    # ---------------------------------------------------------- Airflow
    _af("gl_ingest", "wait_gl_extract", 1, kind=JobKind.SENSOR, at=time(23, 30),
        consumes=("file:/xfer/gl/gl_extract_{date}.dat",), app="finance", owner="data-eng-finance",
        host="celery-pool-finance"),
    _af("gl_ingest", "load_raw_gl", 35, after=("wait_gl_extract",), app="finance",
        owner="data-eng-finance", host="snowflake:WH_FINANCE"),
    _af("gl_ingest", "transform_gl", 70, after=("load_raw_gl",), app="finance",
        owner="data-eng-finance", host="snowflake:WH_FINANCE"),
    _af("gl_ingest", "dq_checks_gl", 15, after=("transform_gl",), app="finance",
        owner="data-eng-finance", host="snowflake:WH_FINANCE"),
    _af("gl_ingest", "publish_gl_mart", 10, after=("dq_checks_gl",),
        produces=("dataset:warehouse://finance/gl_mart",), app="finance", owner="data-eng-finance",
        host="snowflake:WH_FINANCE"),
    _af("regulatory_reporting", "wait_liquidity", 1, kind=JobKind.SENSOR,
        consumes=("file:/data/treasury/liquidity_{date}.csv", "dataset:warehouse://finance/gl_mart"),
        app="regulatory", owner="reg-reporting-tech", host="celery-pool-reg"),
    _af("regulatory_reporting", "compute_lcr", 30, after=("wait_liquidity",), app="regulatory",
        owner="reg-reporting-tech", host="snowflake:WH_REG"),
    _af("regulatory_reporting", "compute_fr2052a", 35, after=("wait_liquidity",), app="regulatory",
        owner="reg-reporting-tech", host="snowflake:WH_REG"),
    _af("regulatory_reporting", "build_reg_pack", 20, after=("compute_lcr", "compute_fr2052a"),
        app="regulatory", owner="reg-reporting-tech", host="celery-pool-reg"),
    _af("regulatory_reporting", "submit_regulator_portal", 5, after=("build_reg_pack",),
        app="regulatory", owner="reg-reporting-tech", host="celery-pool-reg"),
    _af("fraud_features", "wait_txn_file", 1, kind=JobKind.SENSOR, at=time(23, 30),
        consumes=("file:/xfer/core/txn_posted_{date}.dat",), app="risk", owner="fraud-analytics",
        host="celery-pool-risk"),
    _af("fraud_features", "build_features", 60, after=("wait_txn_file",), app="risk",
        owner="fraud-analytics", host="spark-k8s-risk"),
    _af("fraud_features", "score_model", 40, after=("build_features",), app="risk",
        owner="fraud-analytics", host="spark-k8s-risk"),
    _af("fraud_features", "publish_scores", 10, after=("score_model",),
        produces=("dataset:warehouse://risk/fraud_scores",), app="risk", owner="fraud-analytics",
        host="snowflake:WH_RISK"),
    _af("marketing_audience", "build_segments", 30, at=time(0, 30), app="marketing",
        owner="martech", host="snowflake:WH_MKT"),
    _af("marketing_audience", "sync_to_cdp", 15, after=("build_segments",), app="marketing",
        owner="martech", host="celery-pool-default"),

    # ---------------------------------------------------------- Azure Data Factory
    _adf("pl_customer_statements", "copy_stmt_to_lake", 15, kind=JobKind.TRANSFER,
         consumes=("file:landing/stmt/stmt_extract_",), app="customer-comms",
         owner="customer-comms-eng", host="ir-selfhosted-01"),
    _adf("pl_customer_statements", "render_statements", 75, after=("copy_stmt_to_lake",),
         kind=JobKind.TRANSFORM, app="customer-comms", owner="customer-comms-eng",
         host="databricks:stmt-render"),
    _adf("pl_customer_statements", "deliver_to_print_vendor", 15, after=("render_statements",),
         kind=JobKind.TRANSFER, app="customer-comms", owner="customer-comms-eng",
         host="ir-selfhosted-01"),
    _adf("pl_customer360_refresh", "c360_merge", 30, kind=JobKind.TRANSFORM,
         consumes=("table:risk.fraud_scores",), app="c360", owner="customer-data-eng",
         host="databricks:c360",
         hidden_after=("airflow-dp::fraud_features.publish_scores",)),
    _adf("pl_customer360_refresh", "c360_publish", 15, after=("c360_merge",), app="c360",
         owner="customer-data-eng", host="databricks:c360"),
    _adf("pl_hr_payroll_extract", "extract_payroll", 20, at=time(1, 30), kind=JobKind.TRANSFER,
         app="hr", owner="hr-tech", host="ir-selfhosted-02"),
)

JOBS_BY_KEY: dict[str, JobSpec] = {j.key: j for j in JOBS}


def jobs_for(scheduler_id: str) -> list[JobSpec]:
    return [j for j in JOBS if j.scheduler_id == scheduler_id]


@dataclass(frozen=True)
class IncidentSeed:
    id: str
    date: str
    title: str
    vendor: Vendor
    jobs: tuple[str, ...]
    error_code: str | None
    symptoms: str
    root_cause: str
    resolution: str
    mttr_minutes: int


INCIDENT_HISTORY: tuple[IncidentSeed, ...] = (
    IncidentSeed("INC-20260914-0412", "2026-09-14", "GL extract abend S0C7 on malformed packed decimal",
                 CTM, ("ctm-prd::CORE_BANKING_EOD/CBK_GL_EXTRACT",), "S0C7",
                 "CBK_GL_EXTRACT abended with S0C7 data exception in step GLX020. Downstream Airflow gl_ingest "
                 "sensor kept poking; regulatory reporting started 70 minutes late.",
                 "A manual journal posted via the branch adjustment screen carried a non-numeric amount "
                 "field, which broke packed-decimal conversion in the GL extract.",
                 "Corrected the journal record in DB2, restarted CBK_GL_EXTRACT from step GLX020. "
                 "Boosted Airflow pool priority for gl_ingest and regulatory_reporting to recover 25 minutes.",
                 78),
    IncidentSeed("INC-20260702-0233", "2026-07-02", "GL extract abend S0C7 after quarter-end adjustments",
                 CTM, ("ctm-prd::CORE_BANKING_EOD/CBK_GL_EXTRACT",), "S0C7",
                 "S0C7 in CBK_GL_EXTRACT during quarter-end. GL mart published late; LCR submission "
                 "needed an extension request to the regulator.",
                 "Quarter-end accrual reversal batch wrote spaces into the amount field.",
                 "Patched the record, restarted from the failed step, and filed an SLA extension. "
                 "Added a pre-validation step (now a recommended control).", 95),
    IncidentSeed("INC-20260818-0120", "2026-08-18", "Treasury FX rates load slow due to vendor feed latency",
                 AS, ("autosys-ae1::TRS_FX_RATES_LOAD",), None,
                 "TRS_FX_RATES_LOAD ran 3x its normal duration. No downstream SLA impact because "
                 "TRS_POSITION_LOAD waits on the core balances file anyway.",
                 "The market data vendor throttled the rates API during a maintenance window.",
                 "No action; monitored. Vendor maintenance calendar added to the knowledge base.", 0),
    IncidentSeed("INC-20261003-0310", "2026-10-03", "Snowflake WH_FINANCE contention slowed GL transform",
                 AF, ("airflow-dp::gl_ingest.transform_gl", "airflow-dp::gl_ingest.load_raw_gl"), None,
                 "load_raw_gl and transform_gl ran 2.4x longer than usual; GL close finished 40 minutes late.",
                 "An ad hoc analyst query was running on WH_FINANCE during the batch window.",
                 "Scaled WH_FINANCE from M to L for the batch window and moved analyst workloads to WH_ADHOC.", 45),
    IncidentSeed("INC-20261019-0145", "2026-10-19", "ACH file generation failed: settlement file not found",
                 AS, ("autosys-ae1::PAY_ACH_FILE_GEN", "ctm-prd::PAYMENTS_SETTLEMENT/PAY_SETTLE_NET"), "ERR_FNF",
                 "PAY_ACH_FILE_GEN failed with file not found. The Control-M settlement job had ended OK, "
                 "but the MFT transfer to pay-lnx-02 was delayed.",
                 "The MFT agent on pay-lnx-02 was restarted during patching and lost its queue.",
                 "Re-pushed the settlement file via MFT and force-started PAY_ACH_FILE_GEN.", 35),
    IncidentSeed("INC-20261105-0402", "2026-11-05", "Statement rendering cluster failed to start",
                 ADF, ("adf-prd::pl_customer_statements/render_statements",), "DBX_CLUSTER_LAUNCH",
                 "render_statements failed with a cluster launch failure; print vendor cut-off missed by 20 minutes.",
                 "Azure capacity shortage for the requested VM SKU in the region.",
                 "Switched the cluster policy to a fallback VM SKU and reran the activity.", 52),
    IncidentSeed("INC-20260921-0055", "2026-09-21", "Fraud scoring job OOM on Spark executors",
                 AF, ("airflow-dp::fraud_features.score_model",), "OOMKilled",
                 "score_model failed twice with OOMKilled; fraud scores published 90 minutes late and C360 "
                 "refresh used stale scores.",
                 "Transaction volume spike after a promotional campaign doubled the feature matrix.",
                 "Increased executor memory and enabled adaptive query execution; reran.", 90),
    IncidentSeed("INC-20261111-0230", "2026-11-11", "Transaction posting overran on high volume day",
                 CTM, ("ctm-prd::CORE_BANKING_EOD/CBK_TXN_POSTING",), None,
                 "CBK_TXN_POSTING ran 45 minutes longer than usual on Veterans Day volume. "
                 "Every downstream process across Control-M, AutoSys and Airflow shifted right.",
                 "Seasonal volume spike (holiday card spend).",
                 "No failure. Recommended: pre-scale and pre-alert downstream owners on known peak days.", 0),
)
