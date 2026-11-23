.PHONY: api ui lint test up down e2e k8s-render ci-status cloud-setup cloud-up cloud-stop cloud-start cloud-down cloud-status cloud-test
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
cloud-setup: ## once per AWS account (administrator credentials): state bucket, key, operator role. See infra/README.md
	python3 infra/bin/cloud.py setup
cloud-up:   ## the demo on a small AWS VM; then `ssh batchiq` and open http://localhost:8080
	python3 infra/bin/cloud.py up
cloud-stop: ## stop the VM (the disk is kept, only storage bills)
	python3 infra/bin/cloud.py stop
cloud-start:
	python3 infra/bin/cloud.py start
cloud-status:
	python3 infra/bin/cloud.py status
cloud-down: ## delete the VM and everything made for it
	python3 infra/bin/cloud.py down
cloud-test: ## unit tests of the cloud command (no account needed; CI runs them too)
	python3 -m unittest discover -s infra/cloud/tests -t infra/cloud/tests
