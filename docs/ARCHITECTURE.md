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

**The simulation is honest.** The ground truth (`simulation/estate.py`) plants what a real
estate hides: an ADF pipeline fired by an event an Airflow task publishes, an AutoSys report whose
script reads a warehouse table on its own clock, an MQ queue between Control-M and AutoSys, a job
waiting on a deleted job, a password in a script, a redundant condition, sensors that poke for
hours, a job growing slower every night, and four definition changes over the last ten nights. The
overlay never reads the ground truth. It finds each of these from definitions, code and run
history, and the tests check that it does.

**Source mining is a port.** `discovery/sources.py` defines `SourceRepository` (git, Endevor,
ARM templates at a client). Each adapter knows where its vendor keeps the code a job runs
(`source_refs`: a JCL member, a script path, a DAG task block, an ADF activity and the notebook
behind it). `discovery/miner.py` applies a catalogue of rules and keeps the file, line, rule and
snippet for every fact. Credentials are detected and masked; their values never leave the miner.

**Links are recommended, scored and reviewed.** `linking/evidence.py` holds independent
strategies: definitions name the same file or dataset, code writes what another job reads, a
queue or an event connects two jobs, one job reliably starts minutes after another, names share
business terms. Enrichers add run-history order (with the nights the downstream started first)
and incidents that name both jobs. The probability is the noisy-OR of the strongest weight per
kind of evidence. Exact definition matches inside one scheduler are facts; everything else goes
to `linking/review.py`. A link needs the owning teams at both ends (from the schedulers' owner
fields and `catalog/people.yaml`); strong definition-level matches need only the consumer. Reject
and "ask a question" need a reason. A rejected link comes back only if a new kind of evidence
appears. Only approved links enter the lineage graph that drives forecasts.

**The knowledge graph curates itself.** `knowledge/ontology.py` defines 16 node types and 18
relation types with allowed endpoints; `knowledge/graph.py` rejects edges the ontology does not
allow and records provenance on every edge. `knowledge/builder.py` rebuilds the graph on every
sync from definitions, code, runtime, the business catalogue, reviews and incidents.
`knowledge/changes.py` diffs two snapshots into "condition on PAY_SETTLE_NET removed; now starts
daily 02:00", which is how the changelog is produced. The in-memory graph is a port: Apache AGE
(openCypher on Postgres) or Neo4j behind the same interface at a client.

**Findings are small rules with evidence.** `analysis/static.py` and `analysis/runtime.py` are
lists of functions over the same inputs. Add a rule by appending a function. Static and runtime
evidence meet: a missing dependency found in code is confirmed by the nights the job raced its
upstream.

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
| Step 4B / step 5: team reviews and acts | Approve buttons, audit log, link review with owner sign-off |
| Estate visibility and static analysis | Knowledge graph, Ecosystems, Findings (static) |
| Runtime insight and improvement | Findings (runtime): sensors, trends, queueing, stale reads, critical-path leverage |
| Low-maintenance onboarding | Onboarding sandbox, nightly graph rebuild and changelog |
| AI assist tool | Ask the estate |

## Path from prototype to pilot

1. Replace a simulator with a real read-only client for one scheduler (start with the one the
   client exports most easily). The translator and everything above it stay unchanged.
2. Swap `InMemoryEstate` for a Postgres repository (Apache AGE for the graph, pgvector for the
   incident knowledge base), and run ingestion on a schedule or from event streams.
3. Load the client's process catalogue and incident history, then tune the correlation thresholds.
4. Add SSO (OIDC via Keycloak or the client's IdP), role-based actions and policy checks before
   any write-back.
