.PHONY: dev api ui test up k8s-render
api:        ## run the API with hot reload
	cd backend && uvicorn batchiq.api.app:app --reload --port 8000
ui:         ## run the console (proxies /api to :8000)
	cd frontend && npm run dev
test:
	cd backend && pytest -q && cd ../frontend && npm run typecheck
up:         ## full stack in containers on http://localhost:8080
	docker compose up --build
k8s-render: ## render manifests for a cloud: make k8s-render CLOUD=aws|azure|gcp
	kubectl kustomize deploy/k8s/overlays/$(CLOUD)
