# Demo script (about 20 minutes)

**Setup:** `docker compose up --build`, open http://localhost:8080. The default scenario is
"GL extract abend puts regulatory filing at risk". The simulated clock reads 03:25 ET.

## 1. The problem (Command center, 1 min)
- "This bank runs four schedulers. Each has its own console, and none of them knows about the others."
- Point at the connector cards: Control-M, AutoSys, Airflow, ADF, all normalised into 38 jobs.
- KPI: **7 cross-scheduler links**, one of them inferred by AI. "This is the part nobody has today."

## 2. What a traditional console shows vs. what we show (1 min)
- Control-M's view: one abend on CBK_GL_EXTRACT. Airflow's view: a sensor that is still waiting.
  Neither raises a business alarm.
- Our view: **two tier-1 processes are likely to breach**, including the regulatory liquidity filing.

## 3. Business process view (3 min): open "Regulatory liquidity reporting"
- Supply chain: 18 jobs across **Control-M, AutoSys and Airflow**, derived automatically from the
  process outcome.
- Timeline: the red failed attempt, the rerun in flight, the striped Airflow sensor waiting on
  Control-M's file, and dashed projections crossing the 07:00 SLA line.
- Lineage swimlanes: the critical path runs from the Control-M lane into the Airflow lane.
- Forecast: P50 around 07:20 and a **breach probability of about 95%**, against a usual finish around 06:30.
- Root cause: CBK_GL_EXTRACT is the likely origin. The slow AutoSys FX job is shown as
  **off the critical path**, so it isn't blamed for the delay.
- Knowledge base: two prior S0C7 incidents on the same job, with the fix that recovered 25 minutes.

## 4. Act, with a human in the loop (1 min)
- Click **Approve boost**. The toast shows the native Airflow command the overlay would issue.
  Every action is recorded in the audit log on the Insights page.

## 5. The secret sauce: recommended links, reviewed by their owners (4 min): Link review
- Pick **Ana Garcia, MIS Reporting** in "Viewing as". Her queue has one link:
  Airflow `publish_gl_mart` → AutoSys `MIS_DAILY_PNL`, 88%.
- Walk the evidence: the P&L script's SQL reads `finance.gl_mart` (file and line), run history
  shows the report started before the mart was ready on 6 of 30 nights, and incident
  INC-20261020-0610 names both jobs. Finance Data Engineering already approved, with a comment.
- Approve it. The lineage, forecasts, the knowledge graph and the findings all update. The
  finding stays, rephrased: the overlay now watches the dependency, but the scheduler still
  doesn't enforce it.
- Switch to **Marco Torres** to show a rejected link (name similarity only) and the policy box:
  rejected links come back only with new kinds of evidence.

## 6. What the code does that no console shows (3 min)
- **Ecosystems → AutoSys AE1**: boxes and jobs, a "silent" job with no alert, its graph with the
  other schedulers in their own lanes, hosts, and the data it reads and writes.
- **Knowledge graph**: search `finance.gl_mart`. Readers come from definitions and from code.
  Find the path from `CBK_GL_EXTRACT` to `MIS_DAILY_PNL`: Control-M → Airflow → AutoSys.
- **Findings**: static (a job waiting on a deleted job, a password in a script, a redundant
  condition, data leaving the bank) and runtime (sensors poking for hours, `render_statements`
  getting slower every night with weeks to SLA, queueing delay, stale reads).
- **What changed**: four syncs replayed. CHG0041163 replaced a condition with a 02:00 start; the
  next night the recon ran before its input. The recommender already proposed the link back.

## 6. Ask the estate (2 min)
- "What needs my attention right now?"
- "Why is regulatory reporting at risk?"
- "What happens to payments if PAY_SETTLE_NET fails?"
- Layered: "What would break if zos-prd-01 went down?", "What data leaves the bank?",
  "What does AutoSys depend on outside itself?", "What changed this week?"
- Point out the tool chips: answers come from the same grounded facts.

## 7. Under the hood (2 min): Connectors and Onboarding
- Show raw AutoSys JIL next to the unified model, then the Control-M JSON. "Adding a new
  scheduler means writing one adapter."
- **Onboarding**: the pipeline from definitions to findings, with per-connector timings. Load the
  "AutoSys AE2 (Wealth)" sample and Analyse: four jobs understood, a condition nothing provides,
  and a link into the live Control-M estate proposed from a shared file.

## Alternate scenarios
- **Warehouse contention**: no failures at all, yet the SLA drifts. Anomaly detection and the
  forecast catch it, and root cause points to the shared Snowflake warehouse.
- **Healthy night**: everything green. Useful to show the forecast isn't always alarming.
