"""Simulated review history: what the client's teams already decided before tonight.

The links scheduler definitions agree on were approved weeks ago when each
scheduler was onboarded. A few recommendations are mid-review. One weak
name-based suggestion was rejected, which is what keeps it from coming back.
Tuples are (days_ago, person_id, decision, comment).
"""
from __future__ import annotations

_CTM, _AS, _AF, _ADF = "ctm-prd::", "autosys-ae1::", "airflow-dp::", "adf-prd::"

REVIEW_HISTORY: dict[str, list[tuple[int, str, str, str]]] = {
    f"{_CTM}PAYMENTS_SETTLEMENT/PAY_SETTLE_NET->{_AS}PAY_ACH_FILE_GEN": [
        (54, "mtorres", "approve", "The settlement file is the ACH generator's input. Matches our runbook.")],
    f"{_CTM}CORE_BANKING_EOD/CBK_BAL_SNAPSHOT->{_AS}TRS_POSITION_LOAD": [
        (54, "ewalsh", "approve", "Yes, position load reads the core balances file.")],
    f"{_CTM}CORE_BANKING_EOD/CBK_GL_EXTRACT->{_AF}gl_ingest.wait_gl_extract": [
        (41, "praman", "approve", "Correct: the sensor waits for the Control-M GL extract.")],
    f"{_CTM}LOANS_EOD/LN_GL_FEED->{_AF}gl_ingest.wait_loans_feed": [
        (41, "praman", "approve", "Loans GL feed. Confirmed.")],
    f"{_AS}TRS_LIQUIDITY_CALC->{_AF}regulatory_reporting.wait_liquidity": [
        (38, "tmorgan", "approve", "Liquidity file from treasury feeds LCR and FR 2052a.")],
    f"{_CTM}CORE_BANKING_EOD/CBK_TXN_POSTING->{_AF}fraud_features.wait_txn_file": [
        (41, "kimura", "approve", "Fraud features are built from the posted transactions file.")],
    f"{_CTM}CORE_BANKING_EOD/CBK_STMT_EXTRACT->{_ADF}pl_customer_statements/copy_stmt_to_lake": [
        (33, "hpatel", "approve", "The blob trigger fires on the statement extract the mainframe pushes.")],
    # mid-review: one owner has agreed, the other has not looked yet
    f"{_AF}fraud_features.publish_scores->{_ADF}pl_customer360_refresh/c360_merge": [
        (2, "kimura", "approve", "Confirmed from our side: publish_scores fires the customer360_refresh event "
                                 "once the scores land.")],
    f"{_AF}gl_ingest.publish_gl_mart->{_AS}MIS_DAILY_PNL": [
        (1, "praman", "approve", "The P&L script queries our mart directly. It should not run before "
                                 "publish_gl_mart; see INC-20261020-0610.")],
    # a reviewer asked a question
    f"{_AF}gl_ingest.publish_gl_mart->{_AF}data_quality.dq_daily_scan": [
        (1, "bfoster", "needs_info", "The scan is meant to run at 05:00 whatever state the mart is in. Finance "
                                     "data engineering: is a scan of a half-loaded mart a problem for you?")],
    # rejected: shared words, no data flow
    f"{_CTM}PAYMENTS_SETTLEMENT/PAY_SETTLE_RECON->{_AS}PAY_FEDWIRE_RECON": [
        (6, "mtorres", "reject", "Different reconciliations (net settlement vs Fedwire). Nothing flows "
                                 "between them; the names are just similar.")],
}
