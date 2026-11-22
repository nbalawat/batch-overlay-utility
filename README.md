# Batch Intelligence Overlay (prototype)

An AI **system of engagement** that sits on top of the schedulers an enterprise already runs
(Control-M, AutoSys, Airflow, Azure Data Factory and others). It doesn't replace any of them.
It reads from all of them, puts every job into one model, finds the dependencies *between*
schedulers, maps jobs to business processes and SLAs, and adds intelligence on top:

* **Cross-scheduler correlation**: shared files and datasets, name matches and timing patterns
  reveal links that no single vendor console can show. Inferred links carry evidence and a
  confidence score, and wait for human confirmation.
* **Business process view**: each process is defined once by its outcome (anchor jobs and an
  SLA). Its full supply chain across every scheduler is derived from the lineage graph.
* **SLA forecasting**: Monte Carlo simulation over 30 nights of history, propagated through
  the cross-scheduler graph, gives P50/P90 finish times and a breach probability.
* **Anomaly detection**: robust z-scores on durations, with business-aware severity. A slow job
  that isn't on an at-risk critical path is suppressed, not paged.
* **Impact and root-cause hints**: downstream blast radius by scheduler, process and service,
  plus ranked upstream hypotheses (failures, slow jobs, shared resources).
* **Knowledge base (RAG)**: similar past incidents and their fixes.
* **Ask the estate**: natural-language Q&A, using Claude by default and grounded through tools.
* **Human-in-the-loop actions**: an approved action is translated into each scheduler's native
  command (`ctm run`, `sendevent`, `airflow tasks clear`, `az datafactory`) and audited.

> **All integrations are simulated.** Each simulator emits payloads in its scheduler's real
> API format (Control-M Automation API JSON, AutoSys JIL, Airflow REST, ADF management API).
> The adapters parse those exactly as they would at a client. There is no client data.

## Run it

**Containers (recommended)**

```bash
cp .env.example .env          # optional: add ANTHROPIC_API_KEY for conversational answers
docker compose up --build     # open http://localhost:8080
```

**Local dev**

```bash
cd backend && pip install -e ".[dev]" && uvicorn batchiq.api.app:app --reload --port 8000
cd frontend && npm install && npm run dev        # http://localhost:5173
```

## Testing (in the cloud, not on a laptop)

Every push and pull request runs the whole suite on GitHub's runners (`.github/workflows/ci.yml`), so nothing
needs to run on a local machine:

| Job | What it proves |
|---|---|
| Backend tests | ruff, then the pipeline and API tests in parallel (pytest-xdist), offline assistant, pinned date |
| Frontend | type check and production build |
| End-to-end | `docker compose up` of the real images, then Playwright in Chromium: every page renders with no console errors or 5xx, and the demo flows work |
| Image | the API image starts as the non-root user Kubernetes uses, and answers |
| Kubernetes | the base and the AWS, Azure and GCP overlays render, and the base deploys and answers on a kind cluster |
| Compose | the compose file is valid in every profile |

`make ci-status` lists the runs for your branch. To run the same things somewhere with Docker: `make test`,
`make up && make e2e`.

## Demo scenarios

Switch scenarios from the top bar. Each one is a deterministic batch night:

| Scenario | Story |
|---|---|
| `gl-extract-abend` (default) | A Control-M mainframe abend (S0C7) silently pushes two Airflow-run processes, the GL close and the regulatory liquidity filing, toward SLA breach. A slow AutoSys job is shown as harmless. |
| `warehouse-contention` | Nothing fails, but a Snowflake warehouse slowdown in Airflow drifts the SLAs. |
| `healthy-night` | Baseline. Everything is on track. |

See [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) for a 10-minute walkthrough.

## LLM providers

Set `LLM_PROVIDER`:

| Value | Behaviour |
|---|---|
| `auto` (default) | Claude if `ANTHROPIC_API_KEY` is set, otherwise offline |
| `anthropic` | Claude via the official SDK (`LLM_MODEL`, default `claude-opus-5-5`) with adaptive thinking and server-side refusal fallback. For Bedrock, Vertex AI or Foundry, swap in the SDK's platform client. |
| `openai_compatible` | Any self-hosted open-source model behind an OpenAI-compatible endpoint (vLLM, Ollama, TGI, LiteLLM). `docker compose --profile local-llm up` starts Ollama. |
| `offline` | Deterministic, rule-based answers from the same tools. No network needed. |

## Deploy (cloud-agnostic)

Plain Kubernetes manifests with Kustomize. Only the ingress differs per cloud:

```bash
kubectl apply -k deploy/k8s/overlays/aws     # EKS + ALB
kubectl apply -k deploy/k8s/overlays/azure   # AKS + app routing
kubectl apply -k deploy/k8s/overlays/gcp     # GKE + internal GCE ingress
```

## Layout

```
backend/batchiq/
  domain/          unified, vendor-neutral model (Job, Dependency, JobRun, BusinessProcess…)
  adapters/        one package per scheduler: simulator (native API) + adapter (translator)
  core/            store (repository port), correlation engine, lineage graph, business mapping, baselines
  intelligence/    live state, Monte Carlo forecast, insight engine (anomaly/impact/RCA/recs), knowledge base
  llm/             provider abstraction: Anthropic, OpenAI-compatible, factory
  assistant/       tools over the estate, offline provider, assistant orchestrator
  simulation/      ground-truth estate, scenarios, run-history generator
  catalog/         business process catalogue (client-specific config)
  api/             FastAPI app and routes
frontend/src/      React + TypeScript console (React Flow lineage, SVG charts)
deploy/k8s/        Kustomize base + AWS/Azure/GCP overlays
docs/              architecture and demo script
```

Architecture details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
