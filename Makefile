.DEFAULT_GOAL := help
SHELL := /bin/bash
UV ?= uv
WEB := web
VIDEO := video

.PHONY: help
help: ## Show the available targets
	@grep -hE '^[a-zA-Z0-9_.-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# --- setup -------------------------------------------------------------------
.PHONY: install
install: ## Install Python (all groups and extras) and web/video dependencies
	$(UV) sync --all-groups --all-extras
	@if [ -f $(WEB)/package.json ]; then pnpm --dir $(WEB) install --frozen-lockfile; fi
	@if [ -f $(VIDEO)/package.json ]; then pnpm --dir $(VIDEO) install --frozen-lockfile; fi

.PHONY: skills
skills: ## Reinstall the pinned agent skills used to build ARIA
	./scripts/install-agent-skills.sh

# --- quality -----------------------------------------------------------------
.PHONY: lint
lint: ## Lint and format-check Python, then type-check src/
	$(UV) run ruff format --check
	$(UV) run ruff check
	$(UV) run mypy

.PHONY: format
format: ## Auto-format and auto-fix Python
	$(UV) run ruff format
	$(UV) run ruff check --fix

.PHONY: test
test: ## Run the Python test suite with the 80% coverage gate
	$(UV) run pytest --cov --cov-report=term --cov-report=xml --cov-fail-under=80

.PHONY: test-fast
test-fast: ## Run the Python tests without slow tests or coverage
	$(UV) run pytest -m "not slow" -q

.PHONY: audit
audit: ## Scan dependencies and workflows for known issues
	$(UV) run pip-audit --strict --progress-spinner off
	$(UV) run actionlint
	$(UV) run zizmor .github/workflows

# --- data, models and evaluation ----------------------------------------------
.PHONY: data
data: ## Download the datasets listed in data/manifest.yaml and verify checksums
	$(UV) run aria data download

.PHONY: seed
seed: ## Migrate the database and load datasets, windows, runbooks and memory
	$(UV) run aria db upgrade
	$(UV) run aria data ingest
	$(UV) run aria seed

.PHONY: train
train: ## Train and export the severity and ticket models
	$(UV) run aria train

.PHONY: eval
eval: ## Run every evaluation suite and regenerate docs/evaluation.md
	$(UV) run aria eval run --suite all

.PHONY: eval-smoke
eval-smoke: ## Fast offline evaluation used by CI as a regression gate
	$(UV) run aria eval run --suite smoke --gate

# --- run -----------------------------------------------------------------------
.PHONY: api
api: ## Run the API with auto-reload on :8000
	$(UV) run aria serve --reload

.PHONY: worker
worker: ## Run a background worker that executes queued triage runs
	$(UV) run aria worker

.PHONY: mcp
mcp: ## Run the ARIA MCP server over stdio
	$(UV) run aria mcp --transport stdio

.PHONY: web
web: ## Run the web app dev server on :3000
	pnpm --dir $(WEB) dev

.PHONY: dev
dev: ## Migrate the database, then run API and web together (Ctrl-C stops both)
	@$(UV) run aria db upgrade
	@trap 'kill 0' INT TERM EXIT; $(UV) run aria serve --reload & pnpm --dir $(WEB) dev & wait

.PHONY: openapi
openapi: ## Export docs/openapi.json and regenerate the web client types from it
	pnpm --dir $(WEB) gen:api --refresh

# --- web app -------------------------------------------------------------------
.PHONY: web-check
web-check: ## Format-check, lint, type-check and unit-test the web app
	pnpm --dir $(WEB) format:check
	pnpm --dir $(WEB) lint
	pnpm --dir $(WEB) typecheck
	pnpm --dir $(WEB) test

.PHONY: web-e2e
web-e2e: ## Build the web app and run the Playwright and axe suite against an offline API
	pnpm --dir $(WEB) build
	pnpm --dir $(WEB) test:e2e

.PHONY: web-lighthouse
web-lighthouse: ## Build the web app and check every page against the Lighthouse bars
	pnpm --dir $(WEB) build
	cd $(WEB) && ./scripts/lighthouse-ci.sh

.PHONY: video
video: ## Render the demo video to video/out/aria-demo.mp4
	pnpm --dir $(VIDEO) render

# --- containers and infrastructure -------------------------------------------
.PHONY: docker
docker: ## Build the api, worker and web images
	docker compose build

.PHONY: up
up: ## Start the full stack with docker compose
	docker compose up -d --wait

.PHONY: down
down: ## Stop the docker compose stack
	docker compose down

.PHONY: smoke
smoke: ## Triage, review and publish one run through the running stack (make up first)
	./scripts/compose-smoke.sh

.PHONY: bicep
bicep: ## Compile the Bicep templates to catch errors (bicep, or the Azure CLI's copy)
	@if command -v bicep >/dev/null; then bicep build infra/main.bicep --stdout >/dev/null; \
	else az bicep build --file infra/main.bicep --stdout >/dev/null; fi

.PHONY: clean
clean: ## Remove caches and build output
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage coverage.xml htmlcov dist build
