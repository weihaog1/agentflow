.DEFAULT_GOAL := help

.PHONY: help sync python-quality frontend-quality eval benchmark test verify infra-check compose-config demo-up smoke demo-down

help:
	@echo "AgentFlow development commands"
	@echo "  make sync             Install locked Python and frontend dependencies"
	@echo "  make verify           Run local lint, type, test, evaluation, and benchmark gates"
	@echo "  make infra-check      Validate Terraform and the Compose model"
	@echo "  make demo-up          Build and start the complete local stack"
	@echo "  make smoke            Start the stack and run the live API smoke test"
	@echo "  make demo-down        Stop the stack without deleting volumes"

sync:
	uv sync --frozen --all-groups
	cd frontend && npm ci

python-quality:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy src

frontend-quality:
	cd frontend && npm run lint
	cd frontend && npm run test
	cd frontend && npm run build

eval:
	uv run python evals/run_smoke.py

benchmark:
	uv run python -m agentflow.benchmarks.cache --verify-committed

test:
	uv run pytest

verify: python-quality test eval benchmark frontend-quality

compose-config:
	docker compose config --quiet

infra-check: compose-config
	terraform -chdir=infra/aws/terraform fmt -check -recursive
	terraform -chdir=infra/aws/terraform init -backend=false
	terraform -chdir=infra/aws/terraform validate

demo-up:
	docker compose up -d --build --wait

smoke: demo-up
	uv run python scripts/smoke_test.py

demo-down:
	docker compose down --remove-orphans
