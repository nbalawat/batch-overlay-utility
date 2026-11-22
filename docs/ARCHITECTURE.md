# Architecture

## Positioning

The overlay is a layer **on top of** the client's existing control and monitoring tools. It reads
from them, never replaces them, and writes back only through a client's own scheduler APIs, and
only after a human approves. That is what lets a delivery team take it into a client without a
migration.

```
 ┌───────────── Web console (React/TS) ─────────────┐   ┌── Ask the estate (LLM + tools) ──┐
 │ Command center · Processes · Lineage · Insights  │   │ Claude / open-source / offline    │
 └───────────────────────┬──────────────────────────┘   └────────────────┬─────────────────┘
                         │ REST (FastAPI)                                 │
 ┌───────────────────────▼────────────────────────────────────────────────▼────────────────┐
 │ Intelligence: live state · Monte Carlo SLA forecast · anomalies · impact · RCA · recs    │
 │ Knowledge base (incident RAG)                                                            │
 ├──────────────────────────────────────────────────────────────────────────────────────────┤
 │ Business mapping: process catalogue + anchors → full cross-scheduler supply chain        │
 ├──────────────────────────────────────────────────────────────────────────────────────────┤
 │ Correlation engine: artifact match · data-name match · temporal evidence → one graph     │
 ├──────────────────────────────────────────────────────────────────────────────────────────┤
 │ Unified model + repository port (in-memory now; Postgres + AGE + pgvector later)         │
 ├──────────────┬──────────────┬──────────────┬──────────────┬─────────────────────────────┤
 │ Control-M    │ AutoSys      │ Airflow      │ Azure DF     │ … Step Functions, Composer,  │
 │ adapter      │ adapter      │ adapter      │ adapter      │   Tidal, Stonebranch …       │
 │ (Autom. API) │ (JIL + AEWS) │ (REST v1)    │ (Mgmt API)   │                              │
 └──────────────┴──────────────┴──────────────┴──────────────┴─────────────────────────────┘
```

## Key design decisions

**Adapter = client + translator.** `SchedulerAdapter` (in `adapters/base.py`) separates the
transport (`NativeClient`: simulated here, HTTP/CLI at a client) from normalisation. The
simulators produce each vendor's native shapes: Control-M folders with `eventsToWaitFor`,
AutoSys JIL text with `condition: s(...)`, Airflow `downstream_task_ids` and datasets, and ADF
`dependsOn` and blob triggers. They also use each vendor's own date tokens and time formats
(UTC in Airflow and ADF, local time in Control-M and AutoSys), so the translators do real work. New
schedulers register with `@register("<vendor>")`.

**The simulation is honest.** The ground truth (`simulation/estate.py`) includes a coupling that
no scheduler declares: an ADF pipeline fired by a custom event after an Airflow task. The
overlay never reads the ground truth. It has to *infer* that link from a dataset/table name match
plus timing evidence across 30 nights, and it surfaces the link for human confirmation.

**Correlation evidence is explicit.** Every dependency carries `origin` (declared, artifact or
inferred), `confidence`, and a list of `evidence`. The graph uses a configurable confidence
threshold, and operators can confirm or reject inferred links. The overlay learns the client's
estate instead of relying on documentation that is often wrong.

**Business processes are defined by outcome, not by job lists.** The catalogue
(`catalog/business_processes.yaml`) names a process's anchor jobs, SLA and services. Its
membership is every ancestor in the correlated graph, so it stays correct as jobs change.

**Intelligence is deterministic and explainable. The LLM narrates it.** Forecasts, anomalies,
impact and root-cause hints are computed in code with evidence attached. The assistant reaches
them through read-only tools, so its answers stay grounded and auditable. With no LLM
configured, the offline provider answers from the same tools.

**No lock-in.** Python and TypeScript, open-source libraries only (FastAPI, React, React Flow,
dagre). The LLM sits behind a provider interface: Claude by default, any OpenAI-compatible
open-source model, or offline. The repository and knowledge base are ports. Containers run on
Docker Compose or any Kubernetes cluster, and only the ingress overlay changes per cloud.

## How this maps to the design flows

| Design flow step | Where it lives |
|---|---|
| Monitoring step 1: batch runs and real-time data captured | Adapters + `EstateService.load` |
| Step 3A: AI monitor tool (flag anomalies) | `InsightEngine.anomalies` |
| Step 3B: performance optimisation (trends, risk trajectories) | Baselines, Monte Carlo forecast, SLA history |
| Step 4A: situational analysis (severity, dependent jobs) | `impact_of`, severity from process status |
| Step 4A: predictive analytics (delay magnitude, SLA breach probability) | `Forecaster` |
| Step 4A: remediation tool (proposals, low-priority actions) | Recommendations + native action translation |
| RAG knowledge base layer | `intelligence/knowledge.py` (TF-IDF now, pgvector later) |
| Step 4B / step 5: team reviews and acts | Approve buttons, audit log, link confirmation |
| AI assist tool | Ask the estate |

## Path from prototype to pilot

1. Replace a simulator with a real read-only client for one scheduler (start with the one the
   client exports most easily). The translator and everything above it stay unchanged.
2. Swap `InMemoryEstate` for a Postgres repository (Apache AGE for the graph, pgvector for the
   incident knowledge base), and run ingestion on a schedule or from event streams.
3. Load the client's process catalogue and incident history, then tune the correlation thresholds.
4. Add SSO (OIDC via Keycloak or the client's IdP), role-based actions and policy checks before
   any write-back.
