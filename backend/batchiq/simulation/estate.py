"""Ground truth for the simulated enterprise batch estate.

This module describes a fictional bank's overnight batch as it *really* runs:
which scheduler owns each job, what it reads and writes, what its scripts do
behind the scheduler's back, and how long it takes. The vendor simulators
render this into each scheduler's native API format and into the source code
(JCL, shell, DAG files, pipeline JSON) that a client keeps in its repositories.
The overlay never reads this module directly: it only sees what the adapters
and the source miner extract, exactly as it would at a client.

Three kinds of truth are deliberately *not* visible in scheduler definitions:

* ``hidden_after``: coupling no scheduler declares (for example an event fired
  from inside a script). It has to be inferred.
* ``effects``: side effects buried in scripts (files read, SFTP pushes, e-mails,
  API calls, MQ messages). They have to be mined from source code.
* ``CHANGES``: definitions change over time. The overlay has to notice, diff and
  re-curate its knowledge graph on its own.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
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
    produces: tuple[str, ...] = ()       # declared artifacts, with {date} placeholder
    consumes: tuple[str, ...] = ()       # declared inputs (these gate the start)
    at: time | None = None               # scheduled start
    kind: JobKind = JobKind.COMMAND
    host: str = ""
    app: str = ""
    owner: str = ""
    command: str = ""
    hidden_after: tuple[str, ...] = ()   # undeclared upstream (spec keys)
    description: str = ""
    # Behaviour that only the job's source code reveals. Mini-language, one per entry:
    #   "read file <path>" | "write file <path>" | "read table <s.t>" | "write table <s.t>"
    #   "sftp put <host>:<path>" | "sftp get <host>:<path>" | "mail <addr> <subject>"
    #   "api <METHOD> <url>" | "mq put <queue>" | "mq get <queue>" | "event <subject>" | "secret"
    effects: tuple[str, ...] = ()
    growth: float = 0.0                  # duration growth per night (0.015 = 1.5 %)
    flaky: float = 0.0                   # extra failure probability per night
    start_lag: tuple[float, float] | None = None   # queueing delay after inputs are ready (min)
    alarm: bool = True                   # scheduler raises an alert on failure

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
    source_repo: str = ""                # where the job code lives at the client


SCHEDULERS: tuple[SchedulerSpec, ...] = (
    SchedulerSpec("ctm-prd", Vendor.CONTROL_M, "Control-M (Mainframe & Core Banking)", "PROD",
                  "https://ctm-em.bank.example:8443/automation-api",
                  "Core banking end-of-day on z/OS, cards, loans and payments settlement",
                  "Endevor PRD.JCLLIB (exported nightly to git: batch/jcl)"),
    SchedulerSpec("autosys-ae1", Vendor.AUTOSYS, "AutoSys AE1 (Payments, Treasury, AML)", "PROD",
                  "https://autosys-ae1.bank.example:9443/AEWS",
                  "Distributed Linux batch for payments, treasury, AML and MIS reporting",
                  "git: batch/unix-scripts"),
    SchedulerSpec("airflow-dp", Vendor.AIRFLOW, "Airflow (Enterprise Data Platform)", "PROD",
                  "https://airflow.dataplatform.bank.example/api/v1",
                  "Warehouse ingestion, regulatory, risk and marketing analytics",
                  "git: data-platform/airflow-dags"),
    SchedulerSpec("adf-prd", Vendor.ADF, "Azure Data Factory (Customer Cloud)", "PROD",
                  "https://management.azure.com/.../factories/adf-cust-prd",
                  "Cloud-native customer communications, C360 and CRM",
                  "git: customer-cloud/adf (ARM templates + Databricks repos)"),
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


_TXN = "file:/xfer/core/txn_posted_{date}.dat"
_SETTLE = "file:/xfer/pay/settlement_{date}.dat"

JOBS: tuple[JobSpec, ...] = (
    # ================================================================ Control-M
    # ---- core banking end of day
    _ctm("CORE_BANKING_EOD", "CBK_EOD_CUTOFF", 6, at=time(23, 30), host="zos-prd-01", app="CORE",
         owner="core-batch-ops", command="//CBKEOD01 JOB (ACCT),'EOD CUTOFF'",
         effects=("mq put CORE.EOD.CUTOFF",)),
    _ctm("CORE_BANKING_EOD", "CBK_TXN_POSTING", 110, after=("CBK_EOD_CUTOFF",),
         produces=(_TXN,), host="zos-prd-01", app="CORE",
         owner="core-batch-ops", command="//CBKTXN02 JOB (ACCT),'TXN POSTING'",
         effects=("read table core.txn_journal", f"write {_TXN.replace(':', ' ', 1)}")),
    _ctm("CORE_BANKING_EOD", "CBK_INTEREST_ACCRUAL", 45, after=("CBK_TXN_POSTING",), host="zos-prd-01",
         app="CORE", owner="core-batch-ops", command="//CBKINT03 JOB (ACCT),'INT ACCRUAL'"),
    _ctm("CORE_BANKING_EOD", "CBK_GL_EXTRACT", 50, after=("CBK_INTEREST_ACCRUAL",),
         produces=("file:/xfer/gl/gl_extract_{date}.dat",), host="zos-prd-01", app="CORE",
         owner="core-batch-ops", command="//CBKGLX04 JOB (ACCT),'GL EXTRACT'",
         effects=("read table core.gl_ledger", "write file /xfer/gl/gl_extract_{date}.dat")),
    _ctm("CORE_BANKING_EOD", "CBK_BAL_SNAPSHOT", 20, after=("CBK_TXN_POSTING",),
         produces=("file:/xfer/core/balances_{date}.dat",), host="zos-prd-01", app="CORE",
         owner="core-batch-ops", command="//CBKBAL05 JOB (ACCT),'BAL SNAPSHOT'"),
    _ctm("CORE_BANKING_EOD", "CBK_STMT_EXTRACT", 35, after=("CBK_INTEREST_ACCRUAL",),
         produces=("file:/xfer/stmt/stmt_extract_{date}.dat",), host="zos-prd-02", app="CORE",
         owner="core-batch-ops", command="//CBKSTM06 JOB (ACCT),'STMT EXTRACT'",
         effects=("sftp put adls-gw.bank.example:landing/stmt/stmt_extract_{date}.dat",)),
    _ctm("CORE_BANKING_EOD", "CBK_DB_REORG", 25, at=time(23, 45), host="zos-prd-02", app="CORE-HK",
         owner="dba-mainframe", command="//CBKREO09 JOB (ACCT),'DB2 REORG'"),
    # ---- payments settlement
    _ctm("PAYMENTS_SETTLEMENT", "PAY_SETTLE_NET", 25, consumes=(_TXN,), produces=(_SETTLE,),
         host="zos-prd-01", app="PAYMENTS", owner="payments-ops",
         command="//PAYSET01 JOB (ACCT),'NET SETTLEMENT'", effects=("mq put PAY.SETTLE.OUT",)),
    # Changed 3 nights ago (see CHANGES): the condition on PAY_SETTLE_NET was replaced by a fixed time.
    _ctm("PAYMENTS_SETTLEMENT", "PAY_SETTLE_RECON", 20, at=time(2, 0), host="zos-prd-01",
         app="PAYMENTS", owner="payments-ops", command="//PAYREC02 JOB (ACCT),'SETTLE RECON'",
         effects=(f"read {_SETTLE.replace(':', ' ', 1)}", "mail payments-ops@bank.example Settlement recon breaks")),
    # ---- cards
    _ctm("CARDS_EOD", "CRD_AUTH_EXTRACT", 30, at=time(23, 15), host="zos-prd-02", app="CARDS",
         owner="cards-batch", command="//CRDAUT01 JOB (ACCT),'AUTH EXTRACT'",
         produces=("file:/xfer/cards/auth_{date}.dat",)),
    _ctm("CARDS_EOD", "CRD_CYCLE_BILLING", 55, after=("CRD_AUTH_EXTRACT",), host="zos-prd-02", app="CARDS",
         owner="cards-batch", command="//CRDBIL02 JOB (ACCT),'CYCLE BILLING'", growth=0.006),
    _ctm("CARDS_EOD", "CRD_STMT_FEED", 15, after=("CRD_CYCLE_BILLING",), host="zos-prd-02", app="CARDS",
         owner="cards-batch", command="//CRDSTM03 JOB (ACCT),'CARD STMT FEED'",
         produces=("file:/xfer/stmt/card_stmt_{date}.dat",),
         effects=("sftp put sftp.cardprint.example:/inbound/card_stmt_{date}.dat",)),
    _ctm("CARDS_EOD", "CRD_DISPUTES_FEED", 10, after=("CRD_AUTH_EXTRACT",), host="zos-prd-02", app="CARDS",
         owner="cards-batch", command="//CRDDSP04 JOB (ACCT),'DISPUTES FEED'",
         produces=("file:/xfer/cards/disputes_{date}.dat",)),
    # ---- loans
    _ctm("LOANS_EOD", "LN_ACCRUAL", 40, at=time(0, 15), host="zos-prd-02", app="LOANS",
         owner="loans-batch", command="//LNACR001 JOB (ACCT),'LOAN ACCRUAL'"),
    _ctm("LOANS_EOD", "LN_DELINQUENCY", 25, after=("LN_ACCRUAL",), host="zos-prd-02", app="LOANS",
         owner="loans-batch", command="//LNDLQ002 JOB (ACCT),'DELINQUENCY'",
         produces=("file:/xfer/loans/delinquency_{date}.dat",)),
    _ctm("LOANS_EOD", "LN_COLLECTIONS_FEED", 10, after=("LN_DELINQUENCY",), host="zos-prd-02", app="LOANS",
         owner="loans-batch", command="//LNCOL003 JOB (ACCT),'COLLECTIONS FEED'",
         effects=("read file /xfer/loans/delinquency_{date}.dat",
                  "sftp put sftp.collectpro.example:/in/delinquent_{date}.csv",
                  "mail collections-ops@bank.example Collections file sent")),
    _ctm("LOANS_EOD", "LN_GL_FEED", 15, after=("LN_ACCRUAL",), host="zos-prd-02", app="LOANS",
         owner="loans-batch", command="//LNGLF004 JOB (ACCT),'LOANS GL FEED'",
         produces=("file:/xfer/gl/loans_gl_{date}.dat",)),
    # ---- housekeeping (one zombie: waits on an event from a job decommissioned last year)
    _ctm("CORE_HOUSEKEEPING", "HK_LOG_PURGE", 5, at=time(1, 0), host="zos-prd-02", app="CORE-HK",
         owner="dba-mainframe", command="//HKLOG001 JOB (ACCT),'LOG PURGE'"),
    _ctm("CORE_HOUSEKEEPING", "HK_ARCHIVE_TXN", 20, after=("CBK_TXN_ARCHIVE_OLD",), host="zos-prd-02",
         app="CORE-HK", owner="dba-mainframe", command="//HKARC002 JOB (ACCT),'ARCHIVE TXN'"),

    # ================================================================ AutoSys
    _as("PAY_BOX", "PAY_SWIFT_INGEST", 25, at=time(23, 0), host="pay-lnx-01", app="PAYMENTS",
        owner="payments-ops", command="/opt/pay/bin/swift_ingest.sh --channel MT103",
        effects=("sftp get swift-gw.bank.example:/out/mt103_{date}.dat",)),
    _as("PAY_BOX", "PAY_ACH_FILE_GEN", 20, after=("PAY_SWIFT_INGEST",),
        consumes=(_SETTLE,), produces=("file:/out/ach/nacha_{date}.ach",),
        host="pay-lnx-02", app="PAYMENTS", owner="payments-ops",
        command="/opt/pay/bin/ach_gen.sh", start_lag=(6, 14)),
    _as("PAY_BOX", "PAY_NACHA_TRANSMIT", 10, after=("PAY_ACH_FILE_GEN",), host="pay-lnx-02",
        app="PAYMENTS", owner="payments-ops", command="/opt/pay/bin/fed_transmit.sh --rail ACH",
        effects=("sftp put fedline.frb.example:/ach/inbound/nacha_{date}.ach",
                 "mail payments-ops@bank.example NACHA file transmitted")),
    _as("PAY_BOX", "PAY_FEDWIRE_RECON", 15, at=time(4, 0), host="pay-lnx-01", app="PAYMENTS",
        owner="payments-ops", command="/opt/pay/bin/fedwire_recon.sh", alarm=False,
        effects=("mq get PAY.SETTLE.OUT", "mail payments-ops@bank.example Fedwire recon")),
    _as("TRS_BOX", "TRS_FX_RATES_LOAD", 15, at=time(23, 0), host="trs-lnx-01", app="TREASURY",
        owner="treasury-tech", command="/opt/trs/bin/fx_rates_load.sh --source REFINITIV",
        effects=("api GET https://api.marketdata.example/v2/fx/rates",)),
    _as("TRS_BOX", "TRS_POSITION_LOAD", 35, after=("TRS_FX_RATES_LOAD",),
        consumes=("file:/xfer/core/balances_{date}.dat",), host="trs-lnx-01", app="TREASURY",
        owner="treasury-tech", command="/opt/trs/bin/position_load.sh"),
    # Redundant condition: FX_RATES_LOAD is already upstream through POSITION_LOAD.
    _as("TRS_BOX", "TRS_LIQUIDITY_CALC", 40, after=("TRS_POSITION_LOAD", "TRS_FX_RATES_LOAD"),
        produces=("file:/data/treasury/liquidity_{date}.csv",), host="trs-lnx-01", app="TREASURY",
        owner="treasury-tech", command="/opt/trs/bin/liquidity_calc.sh",
        effects=("mail treasury-alco@bank.example Liquidity position ready",)),
    _as("TRS_BOX", "TRS_REPORT_ARCHIVE", 8, at=time(1, 0), host="trs-lnx-02", app="TREASURY-HK",
        owner="treasury-tech", command="/opt/trs/bin/archive.sh --days 90",
        effects=("secret", "sftp put archive-nas-01.bank.example:/archive/treasury/")),
    # ---- AML (added 5 nights ago: reads the core transaction file from its script only)
    _as("AML_BOX", "AML_TXN_SCREEN", 35, at=time(2, 15), host="aml-lnx-01", app="AML",
        owner="aml-tech", command="/opt/aml/bin/txn_screen.sh --rules daily",
        effects=(f"read {_TXN.replace(':', ' ', 1)}", "read table aml.watchlist")),
    _as("AML_BOX", "AML_ALERT_GEN", 20, after=("AML_TXN_SCREEN",), host="aml-lnx-01", app="AML",
        owner="aml-tech", command="/opt/aml/bin/alert_gen.sh", effects=("write table aml.alerts",)),
    _as("AML_BOX", "AML_CASE_EXPORT", 10, after=("AML_ALERT_GEN",), host="aml-lnx-01", app="AML",
        owner="aml-tech", command="/opt/aml/bin/case_export.sh",
        effects=("read table aml.alerts", "sftp put sftp.casevendor.example:/inbound/alerts_{date}.xml",
                 "mail aml-ops@bank.example AML cases exported")),
    # ---- MIS reporting (time-based, reads the finance mart from SQL in its script)
    _as("REPORTING_BOX", "MIS_DAILY_PNL", 25, at=time(6, 0), host="mis-lnx-01", app="MIS",
        owner="mis-reporting", command="/opt/mis/bin/daily_pnl.sh",
        effects=("read table finance.gl_mart", "mail cfo-office@bank.example Daily P&L")),
    _as("REPORTING_BOX", "MIS_EXEC_DASH_REFRESH", 10, after=("MIS_DAILY_PNL",), host="mis-lnx-01",
        app="MIS", owner="mis-reporting", command="/opt/mis/bin/dash_refresh.sh",
        effects=("api POST https://tableau.bank.example/api/3.19/sites/exec/refresh",)),

    # ================================================================ Airflow
    _af("gl_ingest", "wait_gl_extract", 1, kind=JobKind.SENSOR, at=time(23, 30),
        consumes=("file:/xfer/gl/gl_extract_{date}.dat",), app="finance", owner="data-eng-finance",
        host="celery-pool-finance"),
    _af("gl_ingest", "wait_loans_feed", 1, kind=JobKind.SENSOR, at=time(23, 30),
        consumes=("file:/xfer/gl/loans_gl_{date}.dat",), app="finance", owner="data-eng-finance",
        host="celery-pool-finance"),
    _af("gl_ingest", "load_raw_gl", 35, after=("wait_gl_extract", "wait_loans_feed"), app="finance",
        owner="data-eng-finance", host="snowflake:WH_FINANCE",
        effects=("write table finance.raw_gl",)),
    _af("gl_ingest", "transform_gl", 70, after=("load_raw_gl",), app="finance",
        owner="data-eng-finance", host="snowflake:WH_FINANCE",
        effects=("read table finance.raw_gl", "write table finance.gl_stage")),
    _af("gl_ingest", "dq_checks_gl", 15, after=("transform_gl",), app="finance",
        owner="data-eng-finance", host="snowflake:WH_FINANCE"),
    _af("gl_ingest", "publish_gl_mart", 10, after=("dq_checks_gl",),
        produces=("dataset:warehouse://finance/gl_mart",), app="finance", owner="data-eng-finance",
        host="snowflake:WH_FINANCE", effects=("write table finance.gl_mart",)),
    _af("finance_recon", "recon_gl_vs_subledger", 25, consumes=("dataset:warehouse://finance/gl_mart",),
        app="finance", owner="data-eng-finance", host="snowflake:WH_FINANCE",
        effects=("read table finance.gl_mart", "read table finance.subledger")),
    _af("finance_recon", "notify_finance_close", 1, after=("recon_gl_vs_subledger",), kind=JobKind.NOTIFY,
        app="finance", owner="data-eng-finance", host="celery-pool-finance",
        effects=("mail finance-close@bank.example GL reconciliation complete",)),
    _af("regulatory_reporting", "wait_liquidity", 1, kind=JobKind.SENSOR,
        consumes=("file:/data/treasury/liquidity_{date}.csv", "dataset:warehouse://finance/gl_mart"),
        app="regulatory", owner="reg-reporting-tech", host="celery-pool-reg"),
    _af("regulatory_reporting", "compute_lcr", 30, after=("wait_liquidity",), app="regulatory",
        owner="reg-reporting-tech", host="snowflake:WH_REG", effects=("read table finance.gl_mart",)),
    _af("regulatory_reporting", "compute_fr2052a", 35, after=("wait_liquidity",), app="regulatory",
        owner="reg-reporting-tech", host="snowflake:WH_REG"),
    _af("regulatory_reporting", "build_reg_pack", 20, after=("compute_lcr", "compute_fr2052a"),
        app="regulatory", owner="reg-reporting-tech", host="celery-pool-reg"),
    _af("regulatory_reporting", "submit_regulator_portal", 5, after=("build_reg_pack",),
        app="regulatory", owner="reg-reporting-tech", host="celery-pool-reg",
        effects=("api POST https://regportal.fed.example/api/v1/submissions",
                 "mail reg-reporting@bank.example Regulatory pack submitted")),
    _af("fraud_features", "wait_txn_file", 1, kind=JobKind.SENSOR, at=time(23, 30),
        consumes=(_TXN,), app="risk", owner="fraud-analytics", host="celery-pool-risk"),
    _af("fraud_features", "build_features", 60, after=("wait_txn_file",), app="risk",
        owner="fraud-analytics", host="spark-k8s-risk"),
    _af("fraud_features", "score_model", 40, after=("build_features",), app="risk",
        owner="fraud-analytics", host="spark-k8s-risk", flaky=0.08),
    _af("fraud_features", "publish_scores", 10, after=("score_model",),
        produces=("dataset:warehouse://risk/fraud_scores",), app="risk", owner="fraud-analytics",
        host="snowflake:WH_RISK",
        effects=("write table risk.fraud_scores", "event customer360_refresh/fraud_scores")),
    _af("marketing_audience", "build_segments", 30, at=time(1, 30), app="marketing",
        owner="martech", host="snowflake:WH_MKT", effects=("write table mkt.segments",)),
    _af("marketing_audience", "sync_to_cdp", 15, after=("build_segments",), app="marketing",
        owner="martech", host="celery-pool-default",
        effects=("read table mkt.segments", "api POST https://api.cdp-vendor.example/v1/audiences")),
    _af("data_quality", "dq_daily_scan", 20, at=time(5, 0), app="governance", owner="data-governance",
        host="snowflake:WH_FINANCE",
        effects=("read table finance.gl_mart", "read table risk.fraud_scores",
                 "mail data-governance@bank.example Daily DQ scorecard")),

    # ================================================================ Azure Data Factory
    _adf("pl_customer_statements", "copy_stmt_to_lake", 15, kind=JobKind.TRANSFER,
         consumes=("file:landing/stmt/stmt_extract_",), app="customer-comms",
         owner="customer-comms-eng", host="ir-selfhosted-01"),
    _adf("pl_customer_statements", "render_statements", 75, after=("copy_stmt_to_lake",),
         kind=JobKind.TRANSFORM, app="customer-comms", owner="customer-comms-eng",
         host="databricks:stmt-render", growth=0.014),
    _adf("pl_customer_statements", "deliver_to_print_vendor", 15, after=("render_statements",),
         kind=JobKind.TRANSFER, app="customer-comms", owner="customer-comms-eng",
         host="ir-selfhosted-01",
         effects=("sftp put sftp.printvendor.example:/inbound/statements/",)),
    _adf("pl_customer360_refresh", "c360_merge", 30, kind=JobKind.TRANSFORM,
         consumes=("table:risk.fraud_scores",), app="c360", owner="customer-data-eng",
         host="databricks:c360",
         hidden_after=("airflow-dp::fraud_features.publish_scores",),
         effects=("read table risk.fraud_scores",)),
    _adf("pl_customer360_refresh", "c360_publish", 15, after=("c360_merge",), app="c360",
         owner="customer-data-eng", host="databricks:c360", effects=("write table c360.customer_profile",)),
    _adf("pl_crm_sync", "crm_contact_sync", 20, at=time(5, 30), kind=JobKind.TRANSFER,
         consumes=("table:c360.customer_profile",), app="crm", owner="crm-platform", host="ir-selfhosted-02",
         effects=("api POST https://bank.my.crm-vendor.example/services/data/v60.0/composite",)),
    _adf("pl_email_campaigns", "build_email_list", 10, at=time(6, 0), kind=JobKind.TRANSFORM,
         consumes=("table:mkt.segments",), app="marketing", owner="martech", host="databricks:mkt"),
    _adf("pl_email_campaigns", "send_campaign", 15, after=("build_email_list",), app="marketing",
         owner="martech", host="ir-selfhosted-02",
         effects=("api POST https://api.mailvendor.example/v3/mail/send",)),
    _adf("pl_hr_payroll_extract", "extract_payroll", 20, at=time(1, 30), kind=JobKind.TRANSFER,
         app="hr", owner="hr-tech", host="ir-selfhosted-02",
         effects=("read table hr.employees", "sftp put sftp.payroll-provider.example:/upload/")),
)

JOBS_BY_KEY: dict[str, JobSpec] = {j.key: j for j in JOBS}


# ---------------------------------------------------------------------- change history
@dataclass(frozen=True)
class ChangeSpec:
    """A definition change made by the client's teams. ``nights_ago`` = N means the
    change is live for the last N-1 history nights and tonight."""
    id: str
    nights_ago: int
    author: str
    ticket: str
    summary: str
    job_key: str
    before: JobSpec | None          # None = the job was added by this change


def _before(key: str, **changes) -> JobSpec:
    return replace(JOBS_BY_KEY[key], **changes)


CHANGES: tuple[ChangeSpec, ...] = (
    ChangeSpec("CHG-1107", 8, "treasury-tech", "CHG0041107", "Moved TRS_LIQUIDITY_CALC to trs-lnx-01",
               "autosys-ae1::TRS_LIQUIDITY_CALC", _before("autosys-ae1::TRS_LIQUIDITY_CALC", host="trs-lnx-02")),
    *(ChangeSpec("CHG-1142", 5, "aml-tech", "CHG0041142", "Onboarded AML daily transaction screening",
                 k, None) for k in ("autosys-ae1::AML_TXN_SCREEN", "autosys-ae1::AML_ALERT_GEN",
                                    "autosys-ae1::AML_CASE_EXPORT")),
    ChangeSpec("CHG-1163", 3, "payments-ops", "CHG0041163",
               "Decoupled settlement recon from net settlement (fixed 02:00 start)",
               "ctm-prd::PAYMENTS_SETTLEMENT/PAY_SETTLE_RECON",
               _before("ctm-prd::PAYMENTS_SETTLEMENT/PAY_SETTLE_RECON", at=None, after=("PAY_SETTLE_NET",))),
    ChangeSpec("CHG-1170", 2, "martech", "CHG0041170", "Moved marketing audience build from 00:30 to 01:30",
               "airflow-dp::marketing_audience.build_segments",
               _before("airflow-dp::marketing_audience.build_segments", at=time(0, 30))),
)


def specs_as_of(nights_ago: int) -> tuple[JobSpec, ...]:
    """The estate's definitions as they were on a given night (0 = tonight)."""
    reverted = {c.job_key: c.before for c in CHANGES if c.nights_ago <= nights_ago}
    if not reverted:
        return JOBS
    return tuple(reverted.get(s.key, s) for s in JOBS
                 if not (s.key in reverted and reverted[s.key] is None))


def jobs_for(scheduler_id: str, specs: tuple[JobSpec, ...] = JOBS) -> list[JobSpec]:
    return [j for j in specs if j.scheduler_id == scheduler_id]


# ---------------------------------------------------------------------- incidents
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
    IncidentSeed("INC-20261020-0610", "2026-10-20", "Daily P&L e-mailed to CFO office with stale GL figures",
                 AS, ("autosys-ae1::MIS_DAILY_PNL",), None,
                 "MIS_DAILY_PNL ran at 06:00 as scheduled, but the finance GL mart had not been refreshed. "
                 "The CFO office received the previous day's P&L and a correction went out at 08:10.",
                 "The report reads finance.gl_mart directly from SQL in its script. No scheduler links it to "
                 "the Airflow GL close, so nothing held it back when gl_ingest ran late.",
                 "Re-ran the report manually. Action raised: make the dependency explicit.", 130),
)
