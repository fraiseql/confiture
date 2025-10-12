.PHONY: help build-local rebuild-local migrate-local rollback-local status-local verify-local test test-unit test-integration deploy-staging deploy-production clean

# Default target
help:
	@echo "Confiture Multi-Environment Workflow"
	@echo "───────────────────────────────────────────────────"
	@echo ""
	@echo "Local Development:"
	@echo "  make build-local        Build fresh local database"
	@echo "  make rebuild-local      Drop and rebuild (⚠️  destroys data)"
	@echo "  make migrate-local      Apply pending migrations"
	@echo "  make rollback-local     Rollback last migration"
	@echo "  make status-local       Check migration status"
	@echo "  make verify-local       Verify schema integrity"
	@echo "  make seed-local         Load sample data"
	@echo ""
	@echo "Testing:"
	@echo "  make test               Run all tests"
	@echo "  make test-unit          Run unit tests"
	@echo "  make test-integration   Run integration tests"
	@echo "  make test-watch         Run tests in watch mode"
	@echo ""
	@echo "Deployment:"
	@echo "  make deploy-staging     Deploy to staging"
	@echo "  make deploy-production  Deploy to production (requires approval)"
	@echo ""
	@echo "Utilities:"
	@echo "  make clean              Clean up temporary files"
	@echo "  make lint               Lint SQL and Python files"
	@echo ""

# Local Development
build-local:
	@echo "🏗️  Building local database..."
	confiture build --env local

rebuild-local:
	@echo "⚠️  Rebuilding local database (this will destroy all data)"
	@read -p "Are you sure? (y/N): " confirm && [ "$$confirm" = "y" ] || exit 1
	dropdb confiture_workflow || true
	createdb confiture_workflow
	confiture build --env local
	@echo "✅ Database rebuilt"

migrate-local:
	@echo "📈 Applying migrations to local database..."
	confiture migrate up --env local

rollback-local:
	@echo "📉 Rolling back last migration..."
	confiture migrate down --env local

status-local:
	@echo "📊 Migration status:"
	confiture migrate status --env local

verify-local:
	@echo "🔍 Verifying local database..."
	./scripts/verify_migration.sh local

seed-local:
	@echo "🌱 Loading sample data..."
	psql confiture_workflow < db/seeds/local/sample_users.sql

# Testing
test:
	@echo "🧪 Running all tests..."
	pytest tests/ -v --tb=short

test-unit:
	@echo "🧪 Running unit tests..."
	pytest tests/unit/ -v

test-integration:
	@echo "🧪 Running integration tests..."
	pytest tests/integration/ -v

test-watch:
	@echo "👀 Running tests in watch mode..."
	pytest-watch

test-coverage:
	@echo "📊 Running tests with coverage..."
	pytest tests/ -v --cov=db --cov-report=html --cov-report=term-missing
	@echo "📊 Coverage report generated: htmlcov/index.html"

# Deployment
deploy-staging:
	@echo "🚀 Deploying to staging..."
	@echo "⚠️  This will apply migrations to the staging database"
	@read -p "Continue? (y/N): " confirm && [ "$$confirm" = "y" ] || exit 1
	confiture migrate up --env staging --dry-run
	@echo ""
	@echo "Dry-run complete. Review the output above."
	@read -p "Apply migrations? (y/N): " confirm && [ "$$confirm" = "y" ] || exit 1
	confiture migrate up --env staging
	./scripts/verify_migration.sh staging
	@echo "✅ Staging deployment complete"

deploy-production:
	@echo "🚀 Deploying to production..."
	@echo "⚠️  WARNING: This will modify the production database"
	@echo ""
	@echo "Pre-deployment checklist:"
	@echo "  - [ ] All tests pass in CI"
	@echo "  - [ ] Staging deployed and verified"
	@echo "  - [ ] Team notified"
	@echo "  - [ ] Rollback plan ready"
	@echo ""
	@read -p "Type 'deploy-to-production' to confirm: " confirm && [ "$$confirm" = "deploy-to-production" ] || exit 1
	@echo ""
	@echo "📦 Creating backup..."
	./scripts/backup_production.sh
	@echo ""
	@echo "🔍 Dry-run migration..."
	confiture migrate up --env production --dry-run | tee dry-run.log
	@echo ""
	@echo "Review dry-run.log"
	@read -p "Apply migrations? (y/N): " confirm && [ "$$confirm" = "y" ] || exit 1
	confiture migrate up --env production
	./scripts/verify_migration.sh production
	@echo "✅ Production deployment complete"

# Utilities
clean:
	@echo "🧹 Cleaning up..."
	rm -rf __pycache__ .pytest_cache .coverage htmlcov
	rm -f *.log *.sql
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	@echo "✅ Cleanup complete"

lint:
	@echo "🔍 Linting SQL files..."
	sqlfluff lint db/schema/ --dialect postgres || true
	@echo ""
	@echo "🔍 Linting Python migrations..."
	ruff check db/migrations/ || true
	@echo ""
	@echo "🔍 Checking Python formatting..."
	ruff format --check db/migrations/ || true

format:
	@echo "✨ Formatting SQL files..."
	sqlfluff format db/schema/ --dialect postgres
	@echo ""
	@echo "✨ Formatting Python files..."
	ruff format db/migrations/
	@echo "✅ Formatting complete"

# Environment setup
setup:
	@echo "🛠️  Setting up development environment..."
	@command -v confiture >/dev/null 2>&1 || { echo "Installing confiture..."; pip install confiture; }
	@command -v pytest >/dev/null 2>&1 || { echo "Installing pytest..."; pip install pytest pytest-cov; }
	@command -v sqlfluff >/dev/null 2>&1 || { echo "Installing sqlfluff..."; pip install sqlfluff; }
	@command -v ruff >/dev/null 2>&1 || { echo "Installing ruff..."; pip install ruff; }
	@echo "✅ Development environment ready"
	@echo ""
	@echo "Next steps:"
	@echo "  1. Create local database: make rebuild-local"
	@echo "  2. Load sample data: make seed-local"
	@echo "  3. Run tests: make test"
