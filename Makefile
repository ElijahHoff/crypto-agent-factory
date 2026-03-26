.PHONY: help install dev lint format test run api docker clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Install production dependencies
	pip install -e .

dev: ## Install all dependencies (dev included)
	pip install -e ".[dev]"
	pre-commit install

lint: ## Run linter
	ruff check src/ tests/
	mypy src/ --ignore-missing-imports

format: ## Auto-format code
	ruff format src/ tests/
	ruff check --fix src/ tests/

test: ## Run tests with coverage
	pytest tests/ -v --cov=src --cov-report=term-missing

run: ## Run full pipeline (use STRATEGY=name)
	python -m src.main run --strategy $(or $(STRATEGY),unnamed)

ideate: ## Generate strategy ideas
	python -m src.main ideate --n 5

agents: ## List all agents
	python -m src.main agents

pipeline: ## Show pipeline visualization
	python -m src.main pipeline-viz

api: ## Start the FastAPI server
	uvicorn src.server:app --reload --host 0.0.0.0 --port 8000

docker: ## Build and run with Docker Compose
	docker compose up -d --build

docker-down: ## Stop Docker Compose
	docker compose down

clean: ## Clean build artifacts
	rm -rf __pycache__ .pytest_cache .mypy_cache .ruff_cache
	rm -rf dist build *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
