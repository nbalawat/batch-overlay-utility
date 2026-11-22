.PHONY: api ui lint test up down e2e k8s-render ci-status
api:        ## run the API with hot reload
	cd backend && uv run uvicorn batchiq.api.app:app --reload --port 8000
ui:         ## run the console (proxies /api to :8000)
	cd frontend && npm run dev
lint:       ## ruff over the backend
	cd backend && uv run --extra dev ruff check batchiq tests
test:       ## backend tests (parallel) and the frontend type check
	cd backend && LLM_PROVIDER=offline uv run --extra dev pytest -q -n auto && cd ../frontend && npm run typecheck
up:         ## full stack in containers on http://localhost:8080
	docker compose up --build -d --wait
down:
	docker compose down
e2e:        ## browser tests against a running stack: make up && make e2e (set E2E_BASE_URL to point elsewhere)
	cd e2e && npm ci && npx playwright test --trace off
k8s-render: ## render manifests for a cloud: make k8s-render CLOUD=aws|azure|gcp
	kubectl kustomize deploy/k8s/overlays/$(CLOUD)
ci-status:  ## CI runs for the current branch (tests run on GitHub's runners, not on a laptop)
	gh run list --branch "$$(git branch --show-current)" --limit 5
