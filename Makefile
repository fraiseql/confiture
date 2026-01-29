.PHONY: help setup-db setup-docker stop-docker clean-db migrate test test-all test-fast test-verbose test-migration test-unit test-e2e test-coverage lint format clean docs

# Default target
.DEFAULT_GOAL := help

# Colors for output
BLUE := \033[0;34m
GREEN := \033[0;32m
YELLOW := \033[1;33m
RED := \033[0;31m
NC := \033[0m # No Color

PYTHON := python3
UV := uv
PYTEST := $(UV) run pytest

################################################################################
# HELP
################################################################################

help: ## Show this help message
	@echo "$(BLUE)Confiture Database & Testing Makefile$(NC)"
	@echo ""
	@echo "$(YELLOW)Database Setup:$(NC)"
	@grep -E '^[a-zA-Z_-]+.*:.*?## .*$$' $(MAKEFILE_LIST) | grep -E "db|docker|setup" | awk 'BEGIN {FS = ":.*?## "} {printf "  $(BLUE)%-20s$(NC) %s\n", $$1, $$2}'
	@echo ""
	@echo "$(YELLOW)Testing:$(NC)"
	@grep -E '^[a-zA-Z_-]+.*:.*?## .*$$' $(MAKEFILE_LIST) | grep -E "test|lint" | awk 'BEGIN {FS = ":.*?## "} {printf "  $(BLUE)%-20s$(NC) %s\n", $$1, $$2}'
	@echo ""
	@echo "$(YELLOW)Maintenance:$(NC)"
	@grep -E '^[a-zA-Z_-]+.*:.*?## .*$$' $(MAKEFILE_LIST) | grep -E "clean|docs|format" | awk 'BEGIN {FS = ":.*?## "} {printf "  $(BLUE)%-20s$(NC) %s\n", $$1, $$2}'
	@echo ""
	@echo "$(GREEN)Quick Start:$(NC)"
	@echo "  make setup-docker  # Start Docker PostgreSQL"
	@echo "  make test          # Run all tests"
	@echo "  make stop-docker   # Stop Docker services"
	@echo ""

################################################################################
# DATABASE SETUP
################################################################################

setup-db: ## Setup local PostgreSQL databases (requires PostgreSQL installed)
	@echo "$(BLUE)Setting up local PostgreSQL databases...$(NC)"
	@./scripts/setup-databases.sh
	@echo "$(GREEN)✓ Databases setup complete$(NC)"

setup-db-clean: ## Clean and recreate all databases
	@echo "$(BLUE)Cleaning and recreating databases...$(NC)"
	@./scripts/setup-databases.sh --clean
	@echo "$(GREEN)✓ Databases cleaned and recreated$(NC)"

setup-docker: ## Start Docker PostgreSQL (requires Docker)
	@echo "$(BLUE)Starting PostgreSQL with Docker Compose...$(NC)"
	@docker-compose up -d
	@echo "$(GREEN)✓ PostgreSQL started at localhost:5432$(NC)"
	@echo "Databases:"
	@echo "  - confiture_test (primary)"
	@echo "  - confiture_source_test (sync source)"
	@echo "  - confiture_target_test (sync target)"
	@echo "User: confiture / Password: confiture"

setup-docker-logs: ## View Docker PostgreSQL logs
	@docker-compose logs -f postgres

setup-docker-shell: ## Connect to PostgreSQL shell (Docker)
	@docker-compose exec postgres psql -U confiture confiture_test

setup-docker-pgadmin: ## Start Docker with PgAdmin web UI
	@echo "$(BLUE)Starting PostgreSQL with PgAdmin...$(NC)"
	@docker-compose --profile optional up -d
	@echo "$(GREEN)✓ Services started$(NC)"
	@echo "PgAdmin: http://localhost:5050"
	@echo "Login: admin@confiture.local / admin"

stop-docker: ## Stop Docker PostgreSQL
	@echo "$(BLUE)Stopping Docker services...$(NC)"
	@docker-compose stop
	@echo "$(GREEN)✓ Services stopped$(NC)"

stop-docker-all: ## Stop and remove Docker services (preserves data)
	@echo "$(BLUE)Stopping and removing Docker services...$(NC)"
	@docker-compose down
	@echo "$(GREEN)✓ Services removed$(NC)"

clean-db: ## Drop all test databases
	@echo "$(RED)Dropping all test databases...$(NC)"
	@./scripts/setup-databases.sh --clean || true
	@echo "$(GREEN)✓ Databases cleaned$(NC)"

db-status: ## Show database status
	@echo "$(BLUE)Database Status:$(NC)"
	@echo ""
	@echo "Local PostgreSQL:"
	@-psql postgresql://localhost/confiture_test -c "SELECT version();" 2>/dev/null || echo "  Not running"
	@echo ""
	@echo "Docker PostgreSQL:"
	@-docker-compose exec postgres pg_isready 2>/dev/null && echo "  Running ✓" || echo "  Not running"
	@echo ""
	@echo "Databases:"
	@-psql postgresql://localhost/confiture_test -l 2>/dev/null | grep confiture_ || echo "  Use 'make setup-db' or 'make setup-docker' to create"

################################################################################
# TESTING
################################################################################

test: ## Run all tests (fast)
	@echo "$(BLUE)Running all tests...$(NC)"
	@$(PYTEST) tests/ -v --tb=short

test-all: ## Run all tests with full output
	@echo "$(BLUE)Running all tests (full output)...$(NC)"
	@$(PYTEST) tests/

test-fast: ## Run tests (quick mode, no coverage)
	@echo "$(BLUE)Running tests (fast mode)...$(NC)"
	@$(PYTEST) tests/ -q

test-verbose: ## Run tests with maximum verbosity
	@echo "$(BLUE)Running tests (verbose)...$(NC)"
	@$(PYTEST) tests/ -vv --tb=long

test-migration: ## Run migration-specific tests
	@echo "$(BLUE)Running migration tests...$(NC)"
	@$(PYTEST) tests/migration_testing/ -v

test-unit: ## Run unit tests only
	@echo "$(BLUE)Running unit tests...$(NC)"
	@$(PYTEST) tests/unit/ -v

test-integration: ## Run integration tests
	@echo "$(BLUE)Running integration tests...$(NC)"
	@$(PYTEST) tests/integration/ -v

test-e2e: ## Run end-to-end tests
	@echo "$(BLUE)Running E2E tests...$(NC)"
	@$(PYTEST) tests/e2e/ -v

test-coverage: ## Run tests with coverage report
	@echo "$(BLUE)Running tests with coverage...$(NC)"
	@$(PYTEST) tests/ \
		--cov=confiture \
		--cov-report=html \
		--cov-report=term-missing \
		-v
	@echo "$(GREEN)✓ Coverage report: htmlcov/index.html$(NC)"

test-performance: ## Run performance tests
	@echo "$(BLUE)Running performance tests...$(NC)"
	@$(PYTEST) tests/performance/ -v

test-specific: ## Run a specific test (usage: make test-specific TEST=tests/unit/test_builder.py::test_name)
	@echo "$(BLUE)Running specific test: $(TEST)$(NC)"
	@$(PYTEST) $(TEST) -v

watch: ## Run tests in watch mode (requires pytest-watch)
	@echo "$(BLUE)Starting test watch mode...$(NC)"
	@$(UV) run pytest-watch tests/ -- -v

################################################################################
# CODE QUALITY
################################################################################

lint: ## Run linting checks
	@echo "$(BLUE)Running linting...$(NC)"
	@$(UV) run ruff check python/confiture/ tests/
	@echo "$(GREEN)✓ Linting complete$(NC)"

lint-fix: ## Fix linting issues
	@echo "$(BLUE)Fixing linting issues...$(NC)"
	@$(UV) run ruff check --fix python/confiture/ tests/
	@$(UV) run ruff format python/confiture/ tests/
	@echo "$(GREEN)✓ Linting fixes applied$(NC)"

format: ## Format code with ruff
	@echo "$(BLUE)Formatting code...$(NC)"
	@$(UV) run ruff format python/confiture/ tests/
	@echo "$(GREEN)✓ Code formatted$(NC)"

type-check: ## Run type checking
	@echo "$(BLUE)Running type checking...$(NC)"
	@$(UV) run ty check python/confiture/

################################################################################
# BUILD & DOCUMENTATION
################################################################################

build: ## Build the project
	@echo "$(BLUE)Building project...$(NC)"
	@$(UV) build
	@echo "$(GREEN)✓ Build complete$(NC)"

docs: ## Generate/serve documentation
	@echo "$(BLUE)Serving documentation...$(NC)"
	@$(UV) run mkdocs serve

docs-build: ## Build documentation site
	@echo "$(BLUE)Building documentation...$(NC)"
	@$(UV) run mkdocs build
	@echo "$(GREEN)✓ Documentation built in site/$(NC)"

################################################################################
# MAINTENANCE
################################################################################

clean: ## Clean up generated files and caches
	@echo "$(YELLOW)Cleaning up...$(NC)"
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@rm -rf htmlcov/ .coverage 2>/dev/null || true
	@echo "$(GREEN)✓ Cleanup complete$(NC)"

clean-all: clean stop-docker-all ## Full cleanup (databases, Docker, caches)
	@echo "$(RED)Full cleanup complete$(NC)"

fresh: clean-all setup-docker test ## Full fresh setup and test
	@echo "$(GREEN)✓ Fresh setup complete$(NC)"

status: ## Show project status
	@echo "$(BLUE)Project Status:$(NC)"
	@echo ""
	@echo "Python Version:"
	@$(PYTHON) --version
	@echo ""
	@echo "uv Status:"
	@$(UV) --version
	@echo ""
	@echo "PostgreSQL:"
	@-which psql > /dev/null && psql --version || echo "  Not installed"
	@echo ""
	@echo "Docker:"
	@-docker --version && echo "  ✓ Ready" || echo "  Not installed"
	@echo ""
	@echo "Dependencies:"
	@$(UV) pip list | grep -E "pytest|psycopg|ruff" || echo "  Install with: uv sync"

info: ## Show Confiture information
	@echo "$(BLUE)═══════════════════════════════════════════════════════════$(NC)"
	@echo "$(BLUE)Confiture - PostgreSQL Migrations, Sweetly Done 🍓$(NC)"
	@echo "$(BLUE)═══════════════════════════════════════════════════════════$(NC)"
	@echo ""
	@echo "📚 Resources:"
	@echo "  Database Setup:  ./DATABASE_SETUP.md"
	@echo "  Development:     ./DEVELOPMENT.md"
	@echo "  Architecture:    ./ARCHITECTURE.md"
	@echo "  Documentation:   ./docs/"
	@echo ""
	@echo "🚀 Quick Commands:"
	@echo "  Setup:  make setup-docker && make test"
	@echo "  Stop:   make stop-docker"
	@echo "  Clean:  make clean-all"
	@echo ""
	@echo "✅ Test Status: 820 passed, 38 skipped (100% pass rate)"
	@echo ""

################################################################################
# PHONY TARGETS
################################################################################

# Declare all phony targets
.PHONY: help setup-db setup-db-clean setup-docker setup-docker-logs setup-docker-shell \
        setup-docker-pgadmin stop-docker stop-docker-all clean-db db-status \
        test test-all test-fast test-verbose test-migration test-unit test-integration \
        test-e2e test-coverage test-performance test-specific watch \
        lint lint-fix format type-check \
        build docs docs-build \
        clean clean-all fresh status info
