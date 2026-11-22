# Demo script (about 10 minutes)

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

## 5. Hidden dependency (1 min): Cross-scheduler lineage
- The dashed link from Airflow's `publish_scores` to ADF's `c360_merge` is declared by no
  scheduler. The overlay inferred it from a dataset/table name match plus 30 nights of timing,
  at about 94% confidence. Confirm it from Insights → Hidden links.

## 6. Ask the estate (2 min)
- "What needs my attention right now?"
- "Why is regulatory reporting at risk?"
- "What happens to payments if PAY_SETTLE_NET fails?"
- Point out the tool chips: answers come from the same grounded facts.

## 7. Under the hood (1 min): Connectors
- Show raw AutoSys JIL next to the unified model, then the Control-M JSON. "Adding a new
  scheduler means writing one adapter."

## Alternate scenarios
- **Warehouse contention**: no failures at all, yet the SLA drifts. Anomaly detection and the
  forecast catch it, and root cause points to the shared Snowflake warehouse.
- **Healthy night**: everything green. Useful to show the forecast isn't always alarming.
