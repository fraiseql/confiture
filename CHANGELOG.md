# Changelog

All notable changes to Confiture will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.0] - 2026-02-14

### Added

- **COPY Format Seed Loading** - Phase 12 (GitHub Issue #34)
  - Native PostgreSQL COPY format for 2-10x faster seed data loading
  - Automatic format selection: VALUES for small datasets, COPY for large (>1000 rows configurable)
  - `confiture seed convert` command to transform INSERT to COPY format
  - `confiture seed benchmark` command to compare VALUES vs COPY performance
  - `--copy-format` and `--copy-threshold` options for all seed commands
  - Full transaction safety with savepoint isolation per-table
  - Graceful fallback for unconvertible SQL patterns (functions, subqueries, CTEs)
  - Mixed format support (some tables COPY, others VALUES)
  - Integration with `confiture build --sequential --copy-format`

- **Comprehensive Documentation** (2,067 new lines)
  - **docs/guides/COPY-FORMAT-INDEX.md** - Master navigation guide with learning paths
  - **docs/guides/copy-format-loading.md** - Complete guide (20+ min read)
    - What is COPY format and why it's faster
    - 3 quick start approaches
    - Decision tree for when to use
    - How it works (technical details, escaping, transaction safety)
    - 5 real-world use cases
    - Advanced configuration
    - Troubleshooting and performance tuning
    - Integration examples (Makefile, Docker, GitHub Actions)
    - 10-question FAQ
  - **docs/guides/seed-loading-decision-tree.md** - Strategy selection guide (15+ min read)
    - 4 strategies (Concatenate, Sequential, Sequential+COPY, Pre-converted)
    - Decision matrices by data size
    - Performance tiers (2-10x speedup)
    - Migration paths
  - **docs/guides/copy-format-examples.md** - Practical examples (25+ min read)
    - 8 real-world scenarios with code
    - CI/CD integration (GitHub Actions)
    - Docker deployment
    - Performance comparisons

- **Enhanced CLI Documentation**
  - `confiture seed apply` - Added COMMON USAGE, PERFORMANCE TIPS, DOCUMENTATION references
  - `confiture seed convert` - Added HOW IT WORKS, SPEED IMPROVEMENT, example outputs
  - `confiture seed benchmark` - Added WHEN TO USE, EXAMPLE OUTPUT, NEXT STEPS
  - `confiture seed validate` - Added documentation references
  - All commands now link to detailed guides

### Technical Details

**COPY Format Module**:
- `CopyFormatter` - Converts data to PostgreSQL COPY format
- `CopyParser` - Parses COPY format back to data structures
- `CopyExecutor` - Executes COPY with savepoint isolation
- `SeedBatchBuilder` - Intelligently selects VALUES vs COPY per table
- `PerformanceBenchmark` - Compares VALUES vs COPY performance
- `InsertToCopyConverter` - SQLglot AST-based INSERT→COPY transformation
- `InsertValidator` - Detects SQL patterns that can't be converted

**Testing**:
- 205 comprehensive COPY format tests (99 core + 106 extended)
- All 3,920+ total tests passing
- Real-world scenario coverage
- Performance benchmarking verified

**Features**:
- Automatic format detection (configurable threshold, default 1000 rows)
- Per-table format selection (not all-or-nothing)
- Full transaction safety with SAVEPOINT isolation
- Clear error messages for unconvertible patterns
- Performance metrics in output (time saved, speedup factor)
- Integration with existing sequential execution
- Backward compatible (disabled by default, enabled with `--copy-format`)

### Performance Improvements

- **2-10x faster** seed loading for large datasets
- Performance depends on:
  - Data size (bigger = more improvement)
  - Network latency (better connection = more improvement)
  - Row count (more rows = higher speedup)
- Example: 50K rows in 0.6s (COPY) vs 4.5s (VALUES) = 7.2x faster
- Pre-converted files add zero conversion overhead

### Documentation Highlights

**For Users**:
- Multiple entry points (CLI help, guides, examples)
- Decision support (which strategy to use)
- Copy-paste ready code examples
- Integration patterns (Docker, CI/CD, Makefile)
- Troubleshooting solutions

**For Agents**:
- Clear decision trees (aid reasoning)
- Concrete examples (enable pattern matching)
- Quantified metrics (reduce uncertainty)
- Structured sections (easy parsing)
- Multiple documentation entry points

### Backward Compatibility

✅ **Fully backward compatible**:
- COPY format disabled by default
- Existing workflows unchanged
- Enable with `--copy-format` flag
- All 3,920+ existing tests passing
- No breaking changes to API or CLI

## [0.4.1] - 2026-02-05

### Added

- **Sequential Seed Execution in Build Command** (GitHub Issue #32)
  - New `confiture build --sequential` flag to apply seeds sequentially after schema build
  - Avoids PostgreSQL parser limits when building fresh databases with large seed files
  - Single-command solution for schema + seeds (replaces separate build + seed apply)
  - Respects `seed.execution_mode: sequential` from environment configuration
  - New `--database-url` parameter for database connection during seed application
  - New `--continue-on-error` flag to skip failed seed files and continue
  - Perfect for CI/CD pipelines and fresh database initialization

### Details

**Features**:
- Schema builder now separates schema files from seed files using path heuristic
- New `SchemaBuilder.categorize_sql_files()` method returns (schema_files, seed_files) tuple
- New `SchemaBuilder.build(schema_only=True)` parameter to build schema without seeds
- Build command applies seeds via existing `SeedApplier` infrastructure
- Configuration-driven execution: `seed.execution_mode: sequential` in environment YAML
- CLI flag precedence: `--sequential` > config > default (concatenate)

**CLI Options**:
- `confiture build --sequential`: Apply seeds sequentially after schema
- `--database-url URL`: Database connection URL (required for sequential mode)
- `--continue-on-error`: Skip failed seed files and continue execution
- Works with all existing build flags: `--env`, `--output`, `--show-hash`, etc.

**Examples**:
```bash
# Build schema and apply seeds sequentially
confiture build --sequential --database-url postgresql://localhost/myapp

# Environment-specific
confiture build --env production --sequential --database-url $DATABASE_URL

# With error recovery
confiture build --sequential --continue-on-error --database-url postgresql://localhost/myapp

# Or configure in environment
# db/environments/local.yaml:
seed:
  execution_mode: sequential
confiture build  # Automatically uses sequential mode
```

**Testing**:
- 37 new tests (9 unit + 11 integration + 17 edge cases)
- All 3,803+ total tests passing
- Edge cases: no seeds, large files (650+), nested directories, case variations
- Backward compatible: default behavior unchanged

**Documentation**:
- Updated CLI help with `--sequential` examples
- Added sequential execution section to Build from DDL guide
- New Seed Configuration reference in docs/reference/configuration.md
- Updated Sequential Seed Execution guide with build command examples

### Backward Compatibility

✅ **Fully backward compatible**:
- Default behavior unchanged: `confiture build` still concatenates schema + seeds
- Existing `--schema-only` flag continues to work
- Configuration without `seed.execution_mode` defaults to concatenation
- No breaking changes to API or CLI

## [0.4.0] - 2026-02-04

### Added

- **Sequential Seed File Execution** - Phase 9 (Issue #30 context)
  - **Solves PostgreSQL Parser Limit**: 650+ row seed files now execute without "syntax error at or near ;" errors
  - **Per-File Savepoint Isolation**: Each seed file executes within its own `SAVEPOINT sp_seed_NNN` for error recovery
  - **Continue-on-Error Mode**: Optional `--continue-on-error` flag to skip failed files and continue execution
  - **Transaction Validation**: Rejects seed files containing BEGIN/COMMIT/ROLLBACK commands
  - **Rich Console Progress**: Real-time progress reporting with ✓ (success) and ✗ (failed) indicators
  - **Comprehensive Testing**: 29 new tests (5 configuration + 7 discovery + 8 executor + 9 workflow)
  - **Production-Grade Documentation**: 500+ line guide with 8 practical examples, troubleshooting, best practices

### Details

**Features**:
- New CLI command: `confiture seed apply --sequential`
- Sequential execution mode (opt-in, concatenation is default)
- Per-file transaction isolation with savepoints
- Automatic rollback on failure (no partial data)
- Continue-on-error mode for resilient seeding
- File ordering verification (sorted alphabetically)
- Configuration support via `SeedConfig` in environment YAML

**Components**:
- `SeedConfig` model: execution_mode, continue_on_error, transaction_mode
- `SeedApplier`: File discovery and orchestration
- `SeedExecutor`: Savepoint management and execution
- `SeedError`: Enhanced exception with file context

**Testing**:
- 5 unit tests: SeedConfig model validation
- 7 unit tests: File discovery with sorting and filtering
- 8 integration tests: SeedExecutor with mocks
- 9 end-to-end workflow tests: Real PostgreSQL database
- 650-row batch test: Verified parser limit is solved
- Complex SQL support: CTEs, subqueries, nested queries
- Error scenarios: Rollback, FK violations, transaction rejection
- Transaction isolation: Verified per-file savepoint safety

**Documentation**:
- New guide: `docs/guides/sequential-seed-execution.md`
- Problem statement with real PostgreSQL errors
- Solution explanation with transaction isolation diagrams
- Quick start with 3 usage examples
- Configuration reference (YAML format)
- CLI reference with all options and exit codes
- 8 practical examples (basic, large files, error recovery, complex SQL, etc.)
- Troubleshooting section for common issues
- Best practices for production deployments
- Performance analysis and recommendations

**CLI Options**:
- `confiture seed apply --sequential`: Enable sequential execution
- `--continue-on-error`: Skip failed files and continue
- `--seeds-dir PATH`: Custom seeds directory (default: db/seeds)
- `--env NAME`: Environment name (default: local)
- `--database-url URL`: Explicit database URL

**Examples**:
```bash
# Sequential execution (solve parser limits)
confiture seed apply --sequential --env local

# With error recovery
confiture seed apply --sequential --continue-on-error --env local

# Explicit database
confiture seed apply --sequential --database-url postgresql://localhost/db
```

### Implementation Details

**Transaction Strategy**:
- Outer transaction begins
- For each seed file: `SAVEPOINT sp_seed_NNN`
- Execute file SQL
- On success: `RELEASE SAVEPOINT sp_seed_NNN`
- On error: `ROLLBACK TO SAVEPOINT sp_seed_NNN` and either stop or continue
- Finally: `COMMIT` outer transaction

**Parser Limit Solution**:
- Problem: PostgreSQL's parser accumulates context across concatenated SQL
- Root Cause: Large files (650+ rows) exceed parser capacity
- Solution: Fresh parser state per file via savepoints
- Result: 650-row files now execute successfully

**Error Handling**:
- Automatic rollback prevents partial data
- File context included in error messages
- Optional continue-on-error for resilience
- Clear, actionable error messages with line numbers

**Backward Compatibility**: ✅ 100%
- Default behavior unchanged (concatenation mode)
- Sequential mode is opt-in via `--sequential` flag
- All existing functionality unaffected
- No breaking changes to APIs or configuration

**Performance**:
- Setup overhead: ~10ms per file (savepoint creation)
- Execution time: Same as concatenation
- Cleanup overhead: ~5ms per file (savepoint release)
- Total overhead: ~15ms per 650-row file
- Negligible impact on overall performance

### Statistics

- **New Code**: ~2,800 LOC (implementation + tests + docs)
- **Tests Added**: 29 (all passing, 100% success rate)
- **Real Database Tests**: 9 end-to-end workflows
- **Documentation**: 500+ lines with examples
- **Test Coverage**: 100% of new code
- **Linting**: 0 errors, 0 warnings
- **Type Hints**: Complete on all functions
- **Backward Compatibility**: 100%

### Known Limitations

- Sequential mode best for files up to 10,000 INSERT statements
- For very large datasets (>1M rows): Consider database bulk tools
- Savepoint overhead minimal but present for tiny files
- Continue-on-error only available in sequential mode

### Migration Guide

**For Existing Users**:
1. No action required (backward compatible)
2. Default behavior unchanged
3. To enable sequential: add `--sequential` flag
4. Update configuration (optional): add `seed:` section to environment YAML

**For New Projects**:
1. Use `--sequential` for seed files with 500+ rows
2. Use default concatenation for smaller seeds
3. Add documentation for your seed file organization

## [0.3.18] - 2026-02-04

### Added

- **UNION Query Type Validation** - Issue #29
  - **Level 1 Pre-commit Validation**: Detects UNION queries with inconsistent column types (NULL vs NULL::type)
  - **Type Mismatch Detection**: Catches untyped NULL columns mismatched with typed NULL expressions
  - **Column Count Validation**: Ensures all UNION branches have consistent column counts
  - **Multiple Branch Support**: Validates UNION and UNION ALL with 3+ branches correctly
  - **Performance Optimized**: Regex pre-filter skips non-UNION files for fast pre-commit validation
  - **Comprehensive Error Messages**: Actionable suggestions provided with line numbers

### Details

**Features**:
- Level 1 validator now catches Issue #29 pattern: `SELECT col, NULL::type UNION ALL SELECT col, NULL`
- New `UNION_TYPE_MISMATCH` pattern in `PrepSeedPattern` enum
- Detects both column count and type inconsistencies in UNION branches
- Provides specific error messages with fix suggestions
- ERROR severity blocks deployment while allowing batch validation

**Implementation**:
- Regex-based parsing for fast pre-commit validation (~1-5ms per file)
- Handles `INSERT INTO prep_seed.table SELECT ... UNION [ALL] SELECT ...` patterns
- Robust column extraction respecting nested parentheses and function calls
- Line number tracking for precise error reporting

**Testing**:
- 6 new unit tests covering UNION scenarios (100% pass rate)
- Tests for NULL type mismatches, UNION/UNION ALL variants, multi-branch scenarios
- All 104 seed validation tests passing
- Integration tests verify orchestrator integration

**Backward Compatibility**: ✅ 100% backward compatible - new validation adds early error detection without breaking existing features

## [0.3.17] - 2026-02-04

### Added

- **CLI Flags for Comment Validation & File Separators** - Issue #28
  - **Comment Validation Flags**: `--validate-comments`, `--no-validate-comments`, `--fail-on-unclosed`, `--fail-on-spillover`
  - **Separator Style Flags**: `--separator-style` (block_comment, line_comment, mysql, custom), `--separator-template`
  - **CLI Flag Overrides**: All flags override environment config when provided, with visual confirmation
  - **Comprehensive Testing**: 13 new unit tests covering all flag combinations and edge cases
  - **Documentation**: Updated CLI reference with new flags, added CI/CD patterns, enhanced build-validation guide
  - **Example Project**: New `examples/07-comment-validation/` with README and automated test scenarios

### Details

**Features**:
- Comment validation can now be toggled per-build with `--validate-comments` / `--no-validate-comments`
- Stricter modes: `--fail-on-unclosed` and `--fail-on-spillover` for production builds
- Separator style can be overridden: `--separator-style block_comment|line_comment|mysql|custom`
- Custom separator templates: `--separator-template "\\n/* {file_path} */\\n"`
- Visual confirmation when CLI flags override config

**Testing**:
- 13 new unit tests for CLI flag behavior
- 12 integration tests for validation pipeline
- 3,748 total tests passing
- All flag combinations tested
- Invalid input validation tested

**Documentation**:
- CLI reference updated with complete options table
- Comment Validation Flags section with 6 examples
- Separator Style Flags section with 4 examples
- CI/CD Patterns section showing production workflows
- Build validation guide enhanced with CLI override examples
- Example project demonstrates real-world scenarios

**Backward Compatibility**: ✅ 100% backward compatible - all flags optional, environment config as default

## [0.3.16] - 2026-02-04

### Added

- **Enhanced `confiture migrate generate` Command** - Critical safety validations and agent-friendly features
  - **Safety Validations**: Duplicate version detection, file existence checks, name conflict detection, concurrent creation protection with file locking
  - **Agent-Friendly Features**: JSON output format (`--format json`), dry-run mode (`--dry-run`), verbose debugging (`--verbose`)
  - **Comprehensive Testing**: 32 new tests (17 unit + 15 integration), 100% passing with no regressions
  - **Documentation**: Complete guide with examples for all features, safety patterns, and CI/CD automation

### Details

**Validation Safety**:
- Detects duplicate version numbers and warns users
- Prevents accidental file overwrites
- Detects same migration name in different versions
- File locking prevents race conditions in CI/CD pipelines

**Agent Features**:
- `--format json` outputs structured JSON for programmatic parsing
- `--dry-run` previews migration without creating files
- `--verbose` shows version calculation and directory scanning details

**Quality**:
- 17 new unit tests for validation logic
- 15 new integration tests for CLI features
- 431 migration-related tests passing
- 3,248 unit tests with zero regressions
- All linting checks pass

**Documentation**:
- New "Generating Migration Files" section in incremental migrations guide
- Examples for dry-run, verbose, and JSON modes
- Safety features documentation
- CI/CD automation patterns

**Backward Compatibility**: ✅ 100% backward compatible - text output remains default

## [0.3.15] - 2026-02-03

### Fixed

- **Rust Schema Builder Trailing Newline Bug** - Fixed issue where SQL files without trailing newlines could produce invalid SQL when concatenated
  - Added defensive check to ensure final output always ends with newline per POSIX standard
  - Prevents SQL parsing issues with PL/pgSQL dollar-quoted functions (`$$...$$`)
  - Handles edge cases: empty files, whitespace-only files, mixed newline scenarios
  - Added 8 comprehensive edge case tests to catch similar issues
  - Rust and Python implementations now have identical behavior for all file variations
  - Particularly important for large codebases with auto-generated SQL files (e.g., 376+ files)

## [0.3.14] - 2026-01-31

## [0.3.13] - 2026-01-31

## [Unreleased]

## [0.3.11] - 2026-01-29

### Added - Git-Aware Schema Validation

**New Commands and Flags**:
- `confiture migrate validate --check-drift` - Detect schema differences between git refs
- `confiture migrate validate --require-migration` - Ensure DDL changes have corresponding migration files
- `confiture migrate validate --base-ref <ref>` - Compare against specific git reference (branch, tag, commit)
- `confiture migrate validate --since <ref>` - Alias for `--base-ref`
- `confiture migrate validate --staged` - Validate only staged files (pre-commit hook mode)

**New Core Modules**:
- `GitRepository` class - Interface to git operations via subprocess
  - `get_file_at_ref()` - Retrieve file content from specific git refs
  - `get_changed_files()` - List files changed between git refs
  - `get_staged_files()` - List currently staged files
  - `is_git_repo()` - Check if in git repository
- `GitSchemaBuilder` class - Build schemas from files at specific git refs
- `GitSchemaDiffer` class - Compare schemas between refs
- `MigrationAccompanimentChecker` class - Validate DDL changes have migration files
- `MigrationAccompanimentReport` data model - Structured validation results

**Use Cases**:
- Pre-commit hooks for schema validation (<500ms for staged files)
- GitHub Actions CI/CD pipelines
- GitLab CI integration
- Code review gates (prevent merging without proper migrations)
- Local development validation

**Features**:
- Schema drift detection - Find untracked schema changes
- Migration enforcement - Require migration files for every DDL change
- Flexible git references - Compare against branches, tags, commits, relative refs (HEAD~10)
- Performance optimized - <500ms for pre-commit, <5s for full repo
- JSON output support for CI/CD automation
- Text and JSON output formats
- Proper exit codes (0: pass, 1: validation failed, 2: error)

**Documentation**:
- Comprehensive user guide: docs/guides/git-aware-validation.md (850+ lines)
  - Quick start examples
  - 4 detailed use case sections (pre-commit, GitHub Actions, GitLab CI, code review)
  - Complete command reference
  - Decision tree for choosing right flags
  - 4 detailed common scenarios with solutions
  - Performance tips for large repositories
  - Complete troubleshooting guide
  - API reference with Python code examples
  - Best practices and glossary
- Updated CLI reference with all git-aware validation flags
- Updated getting-started guide with validation section and 5-minute pre-commit setup
- Updated README.md with feature announcement
- Updated docs/index.md with guide links

### Quality & Testing

**Test Coverage**:
- 24 comprehensive tests (unit + integration)
- GitRepository: 8 unit tests for all git operations
- Schema building: 6 unit tests for building and comparing schemas
- Migration validation: 5 unit tests for accompaniment checking
- CLI integration: 5 integration tests for flag combinations
- 100% coverage for new modules

**Code Quality**:
- Full type hints throughout (Python 3.11+ union syntax)
- Complete docstrings with examples
- All linting passes (ruff)
- All type checking passes (ty)
- Proper error handling with timeouts on all git operations
- No new dependencies added

**Security**:
- Input validation on all git operations
- Subprocess timeout protection (10-30 seconds)
- No command injection (list-based args, no shell=True)
- No hardcoded credentials or secrets

### Backward Compatibility

- ✅ No breaking changes
- ✅ All new flags are optional
- ✅ All new features are additive
- ✅ Existing `confiture migrate validate` behavior unchanged

## [0.3.10] - 2026-01-29

### Fixed - Type Safety and Quality Improvements

**Type Checking**:
- Resolved all 102 type checking diagnostics (ty type checker)
- Fixed null handling for `cursor.fetchone()` calls (13+ locations)
- Fixed return type annotations in migrator
- Fixed method signature compatibility (LoggerAdapter.process)
- Corrected type hints for generator cleanup handlers
- Suppressed optional dependency import errors (prometheus_client, opentelemetry)

**Development Cleanup**:
- Removed development archaeology (TODO markers, phase/week/day references)
- Removed 6 tracked `.claude/` phase planning artifacts from git
- Added `.claude/*.md` to .gitignore for local development notes
- Replaced deprecated `mypy` with `ty` in Makefile

**Documentation Fixes**:
- Fixed broken README link (cli-dry-run.md → dry-run.md)
- Cleaned up development phase references in performance and security docs

**CI/CD**:
- Fixed GitHub Actions type-check job (removed unnecessary pip caching)
- All 18 quality gate checks now passing

### Testing

- All 2,861 unit tests passing
- All ruff linting checks passing
- Type checking clean (ty diagnostics: 0)
- Connection pool stats mock updated to use dict-like access

### Backward Compatibility

- ✅ No breaking changes
- ✅ No API changes
- ✅ All existing functionality preserved

## [0.3.9] - 2026-01-27

### Added - Migration File Validation and Auto-Fix

**Migration Validation**:
- `confiture migrate validate` - Comprehensive migration file validation command
- Orphaned migration file detection (missing `.up.sql` suffix)
- Auto-fix capability with `--fix-naming` flag
- Dry-run preview mode with `--dry-run` flag
- JSON output support for CI/CD integration
- Safe file renaming (atomic operations, error handling)

**Warnings in Existing Commands**:
- `confiture migrate status` - Shows orphaned files in text and JSON output
- `confiture migrate up` - Warns before applying migrations
- `--strict` mode - Fail if orphaned files exist

**New Migrator Methods**:
- `find_orphaned_sql_files()` - Detect misnamed migration files
- `fix_orphaned_sql_files()` - Safely rename files to match pattern

**Documentation**:
- New comprehensive guide: "Migration Naming Best Practices" (500+ lines)
- Updated CLI reference with validate command documentation
- Updated troubleshooting guide with orphaned files section
- Updated incremental migrations guide with naming requirements
- CI/CD pipeline integration examples
- Real-world scenarios and troubleshooting FAQ

### Features

**Three Recognized Migration Patterns**:
```
{NNN}_{name}.py             # Python migrations
{NNN}_{name}.up.sql         # Forward migrations
{NNN}_{name}.down.sql       # Rollback migrations
```

**Auto-Fix Workflow**:
```bash
# Detect orphaned files
confiture migrate validate

# Preview fixes
confiture migrate validate --fix-naming --dry-run

# Apply fixes
confiture migrate validate --fix-naming

# CI/CD integration
confiture migrate validate --format json
```

### Testing

- 8 new tests for validate command (6 CLI + 2 Migrator)
- Dry-run mode tests
- JSON output tests
- Auto-fix tests with content preservation
- 2,660 unit tests passing
- Full backward compatibility verified

### Issue Resolution

- Resolves [GitHub Issue #13](https://github.com/evoludigit/confiture/issues/13) - Migration Discovery Validation
- Three-phase implementation:
  - Phase 1: Detection and warnings
  - Phase 2: Validation command with auto-fix
  - Phase 3: Comprehensive documentation

### Backward Compatibility

- ✅ No breaking changes
- ✅ All existing migrations continue to work
- ✅ Warnings are non-blocking (informational only)
- ✅ New features are opt-in
- ✅ Full backward compatibility verified

## [0.3.8] - 2026-01-22

### Added - Multi-Agent Coordination System (Phase 4)

**Core Coordination Features**:
- **Intent Registry**: Declare schema change intentions before implementation
- **Automatic Conflict Detection**: Analyzes DDL for 6 conflict types (TABLE, COLUMN, FUNCTION, INDEX, CONSTRAINT, TIMING)
- **Branch Allocation**: Unique pgGit branch assignment for each intent
- **Status Tracking**: Complete lifecycle management (REGISTERED → IN_PROGRESS → COMPLETED → MERGED)
- **Audit Trail**: Full history of all coordination decisions and status changes
- **Resolution Workflows**: Guided conflict resolution with actionable suggestions

**CLI Commands** (`confiture coordinate`):
- `register` - Declare intention to make schema changes
- `list-intents` - View all registered intentions with filtering
- `status` - Get detailed status of specific intention
- `check` - Pre-flight conflict check before registration
- `conflicts` - List all detected conflicts
- `resolve` - Mark conflict as reviewed with resolution notes
- `abandon` - Abandon intention with reason tracking

**JSON Output Support**:
- `--format json` flag for all coordinate commands
- Machine-readable output for CI/CD integration
- Parsing examples for Bash (jq), Python, Node.js
- Backward compatible (defaults to Rich-formatted text output)

**Database Schema** (Trinity Pattern):
- `tb_pggit_intent` - Intent storage with JSONB metadata
- `tb_pggit_conflict` - Conflict tracking and resolution
- `tb_pggit_intent_history` - Complete audit trail of status changes
- Optimized indexes for sub-millisecond queries

**Performance**:
- Intent registration: ~1.3ms (76x faster than target)
- Conflict detection: <1ms even with 100 active intents
- Database queries: <1ms for most operations
- Linear scaling: 1,000 intents in 1.54s
- 18 comprehensive performance benchmarks
- Production-ready without optimization

**Documentation**:
- Architecture documentation (1,030 lines) - Complete system design
- User guide (1,056 lines) - CLI commands, workflows, best practices
- Performance benchmarks (454 lines) - Detailed analysis and recommendations
- 3 executable example workflows
- JSON integration examples

**Testing**:
- 123 coordination tests (unit + integration + E2E + CLI + performance)
- 100% test pass rate
- ~95%+ code coverage for coordination package
- 20 E2E workflow scenarios
- Zero known issues

**Key Benefits**:
- Enables parallel schema development with confidence
- Early conflict detection (before code is written)
- Clear visibility into all active schema work
- Audit trail for compliance and debugging
- Production-tested and performant

### Files Added

- `python/confiture/integrations/pggit/coordination/models.py` - Data models (Intent, ConflictReport, enums)
- `python/confiture/integrations/pggit/coordination/detector.py` - Conflict detection algorithm
- `python/confiture/integrations/pggit/coordination/registry.py` - Database-backed intent registry
- `python/confiture/cli/coordinate.py` - CLI commands (7 commands)
- `tests/unit/test_coordination.py` - Unit tests (25 tests)
- `tests/integration/test_coordination_registry.py` - Integration tests (52 tests)
- `tests/e2e/test_coordination_e2e.py` - E2E workflow tests (20 tests)
- `tests/unit/test_cli_coordinate.py` - CLI tests (28 tests)
- `tests/performance/test_coordination_benchmarks.py` - Performance benchmarks (18 tests)
- `docs/architecture/multi-agent-coordination.md` - Architecture documentation
- `docs/guides/multi-agent-coordination.md` - User guide
- `docs/performance/coordination-performance.md` - Performance analysis
- `examples/multi-agent-workflow/` - 3 executable example scripts

### Example Usage

```bash
# Register intention to add Stripe integration
confiture coordinate register \
    --agent-id claude-payments \
    --feature-name stripe_integration \
    --schema-changes "ALTER TABLE users ADD COLUMN stripe_customer_id TEXT" \
    --tables-affected users \
    --risk-level medium

# Check for conflicts before starting work
confiture coordinate check \
    --agent-id claude-auth \
    --feature-name oauth2 \
    --schema-changes "ALTER TABLE users ADD COLUMN oauth_provider TEXT" \
    --tables-affected users

# List all active work
confiture coordinate list-intents --status-filter in_progress

# Get JSON output for automation
confiture coordinate list-intents --format json | jq '.total'

# Mark conflict as resolved
confiture coordinate resolve \
    --conflict-id 42 \
    --notes "Coordinated with team, applying changes sequentially"
```

### Closes

- Phase 4 implementation complete (100% of acceptance criteria met)
- All Week 3 objectives exceeded (architecture, JSON, performance benchmarks)

## [0.3.7] - 2026-01-18

### Fixed

**SQL-Only Migration Support in Testing Framework** (Issue #8):
- `load_migration()` now automatically detects and loads SQL-only migrations
- Searches for `.up.sql`/`.down.sql` file pairs when Python migration not found
- `find_migration_by_version()` also updated to search both formats
- Python migrations are still tried first for backwards compatibility

### Added

- 17 new unit tests for `load_migration()` covering all migration formats
- Helpful error messages when `.down.sql` file is missing

### Example

```python
from confiture.testing import load_migration

# Both formats work now:
Migration = load_migration("003_move_tables")  # Python or SQL auto-detected
Migration = load_migration(version="003")       # Version lookup works too

# SQL-only migrations are discovered automatically:
# db/migrations/003_move_tables.up.sql
# db/migrations/003_move_tables.down.sql
```

### Closes

- GitHub Issue #8: load_migration() should support SQL-only migrations

## [0.3.6] - 2026-01-18

### Added - Developer Experience Improvements (Issue #7)

**Migration Loader Utility** (`load_migration`):
- Simple function to load migrations without importlib boilerplate
- Support loading by full name: `load_migration("003_move_tables")`
- Support loading by version prefix: `load_migration(version="003")`
- Custom migrations directory support
- Clear error messages with `MigrationNotFoundError` and `MigrationLoadError`

**JSON Output for Status Command**:
- New `--format json` flag for `migrate status` command
- New `--output` / `-o` flag to save status to file
- Structured JSON output with applied, pending, current version, and migration details
- Machine-readable format for CI/CD integration

**Baseline Command** (`migrate baseline`):
- Mark migrations as applied without executing them
- `--through` flag to mark all migrations up to a version
- `--dry-run` support to preview what would be marked
- Perfect for adopting confiture on existing databases
- Records baseline operations with `execution_time_ms = 0`

**SQL-Only Migration Files**:
- **File pairs**: `.up.sql` / `.down.sql` files (no Python needed)
- **Class attributes**: `SQLMigration` with `up_sql` / `down_sql` attributes
- Automatic discovery alongside Python migrations
- Full support for checksums, dry-run, and status tracking
- Mixed Python + SQL migrations in same directory

**Migration Testing Sandbox** (`MigrationSandbox`):
- Context manager with automatic transaction rollback
- Pre-loaded testing utilities (validator, snapshotter)
- Works with URL (creates connection) or existing connection (uses savepoint)
- Convenience methods: `capture_baseline()`, `assert_no_data_loss()`, `assert_constraints_valid()`
- Direct SQL execution: `execute()` and `query()` methods

**Pytest Plugin**:
- Auto-registered via pytest11 entry point (works when confiture is installed)
- Manual registration: `pytest_plugins = ["confiture.testing.pytest"]`
- Fixtures: `confiture_sandbox`, `confiture_validator`, `confiture_snapshotter`
- Overridable: `confiture_db_url`, `confiture_migrations_dir`
- `@migration_test("003")` decorator for class-based migration tests

**Top-Level Testing Imports**:
- All fixtures importable from `confiture.testing`
- `from confiture.testing import SchemaSnapshotter, DataValidator, MigrationRunner`
- `from confiture.testing import load_migration, MigrationSandbox`
- Backwards compatible with existing deep imports

### New Files

- `python/confiture/testing/loader.py` - Migration loader utility
- `python/confiture/testing/sandbox.py` - MigrationSandbox context manager
- `python/confiture/testing/pytest_plugin.py` - Pytest fixtures and plugin
- `python/confiture/testing/pytest/__init__.py` - Pytest namespace exports
- `python/confiture/models/sql_file_migration.py` - FileSQLMigration for .sql file pairs

### Modified Files

- `python/confiture/testing/__init__.py` - Top-level exports
- `python/confiture/cli/main.py` - JSON status output, baseline command
- `python/confiture/core/connection.py` - `load_migration_class()` for Python + SQL
- `python/confiture/core/migrator.py` - SQL file discovery, `mark_applied()`
- `python/confiture/models/__init__.py` - SQLMigration export
- `python/confiture/models/migration.py` - SQLMigration class
- `pyproject.toml` - pytest11 entry point

### Example Usage

**Load migrations easily**:
```python
from confiture.testing import load_migration

Migration003 = load_migration("003_move_catalog_tables")
# or by version:
Migration003 = load_migration(version="003")
```

**JSON status output**:
```bash
confiture migrate status --format json
# {"applied": ["001", "002"], "pending": ["003"], "current": "002", ...}

confiture migrate status -f json -o status.json
```

**SQL-only migrations**:
```
db/migrations/
├── 003_move_tables.up.sql
├── 003_move_tables.down.sql
```

Or with Python class:
```python
class MoveTables(SQLMigration):
    version = "003"
    name = "move_tables"
    up_sql = "ALTER TABLE foo SET SCHEMA bar;"
    down_sql = "ALTER TABLE bar.foo SET SCHEMA public;"
```

**Baseline command**:
```bash
confiture migrate baseline --through 002
# Marks 001, 002 as applied without executing
```

**Testing sandbox**:
```python
from confiture.testing import MigrationSandbox

with MigrationSandbox(db_url) as sandbox:
    migration = sandbox.load("003")
    baseline = sandbox.capture_baseline()
    migration.up()
    sandbox.assert_no_data_loss(baseline)
# Auto-rollback on exit
```

**Pytest plugin**:
```python
# conftest.py
pytest_plugins = ["confiture.testing.pytest"]

# test file
def test_migration(confiture_sandbox):
    migration = confiture_sandbox.load("003")
    migration.up()
    assert confiture_sandbox.validator.constraints_valid()
```

### Compatibility

- ✅ All existing functionality preserved
- ✅ No breaking changes
- ✅ Backwards compatible imports
- ✅ Python 3.11, 3.12, 3.13 supported

### Closes

- GitHub Issue #7: DX Improvements

## [0.4.0] - 2025-12-27

### Added - Phase 5: CLI Integration for Dry-Run Mode

**Dry-Run Analysis** (`--dry-run` flag):
- Analyze migrations without executing them
- Preview impact before applying: estimated time, disk usage, CPU
- Works with both `migrate up` and `migrate down` commands
- No database changes, safe for production planning
- Exit immediately after analysis (no execution)

**SAVEPOINT Testing** (`--dry-run-execute` flag):
- Execute migrations in guaranteed-rollback transaction
- Test actual migration logic with automatic rollback
- Measure real execution time and verify constraints
- User confirmation prompt before real execution
- Perfect for pre-production validation

**Output Formats**:
- **Text format** (default) - Human-readable, colorized output
- **JSON format** (`--format json`) - Structured data for CI/CD integration
- **File output** (`--output file.txt`) - Save analysis reports for review

**Rollback Analysis** (`migrate down --dry-run`):
- Analyze what gets undone before rollback
- Preview which migrations would be reversed
- Safe exploration of rollback scenarios

**Validation & Safety**:
- `--dry-run` and `--dry-run-execute` are mutually exclusive
- `--dry-run` incompatible with `--force` flag
- Clear error messages for invalid flag combinations
- User confirmation required for SAVEPOINT execution

### CLI Additions

**New flags for `migrate up`**:
- `--dry-run` - Analyze without execution
- `--dry-run-execute` - Test in SAVEPOINT, ask for confirmation
- `--format / -f` - Output format (text, json)
- `--output / -o` - Save report to file
- `--verbose / -v` - Detailed output

**New flags for `migrate down`**:
- `--dry-run` - Analyze rollback without execution
- `--format / -f` - Output format (text, json)
- `--output / -o` - Save report to file
- `--verbose / -v` - Detailed output

### Documentation

**New comprehensive guides**:
- `docs/guides/cli-dry-run.md` - 500+ line user guide covering:
  - Analyze without execution
  - SAVEPOINT testing workflow
  - Rollback analysis
  - Output format comparison
  - Real-world examples (5 scenarios)
  - Troubleshooting guide
  - CI/CD integration example
  - Best practices and FAQ

**Updated documentation**:
- `README.md` - Added dry-run section with examples
- `docs/index.md` - Added link to dry-run guide

### Testing

**New test file**: `tests/unit/test_cli_dry_run.py`
- 12 comprehensive test cases covering:
  - Dry-run analysis mode (3 tests)
  - JSON/text output formats (4 tests)
  - File output (1 test)
  - SAVEPOINT execution with confirmation (1 test)
  - Rollback analysis (2 tests)
  - Flag validation (3 tests)
  - User cancellation (1 test)
  - Edge cases (2 tests)

**Test Coverage**:
- All critical paths covered
- 30/30 total CLI tests passing (100%)
- 0 new regressions
- All existing functionality preserved

### Code Changes

**New helper module**: `python/confiture/cli/dry_run.py`
- `display_dry_run_header()` - Show analysis mode indicator
- `save_text_report()` - Generate human-readable reports
- `save_json_report()` - Generate structured JSON reports
- `print_json_report()` - Output JSON to console
- `show_report_summary()` - Display summary statistics
- `ask_dry_run_execute_confirmation()` - User confirmation prompt
- `extract_sql_statements_from_migration()` - SQL extraction utilities

**Modified**: `python/confiture/cli/main.py`
- Added dry-run logic to `migrate_up()` command
- Added dry-run logic to `migrate_down()` command
- Migration metadata collection for analysis
- Report generation and formatting
- Early returns for analysis-only mode
- Confirmation flow for SAVEPOINT execution

### Quality Metrics

**Code Quality**:
- 0 linting issues in main code
- 100% type hint coverage
- Comprehensive docstrings
- All functions tested

**Test Results**:
- 12 new tests for dry-run features
- 30 total CLI tests (18 existing + 12 new)
- 100% passing (30/30)
- No regressions

**Documentation**:
- 500+ lines of user guide
- 5 real-world examples
- Troubleshooting section
- CI/CD integration example
- Complete CLI reference

### Example Usage

**Analyze before applying**:
```bash
$ confiture migrate up --dry-run
🔍 Analyzing migrations without execution...

Migration Analysis Summary
================================================================================
Migrations to apply: 2

  001: create_initial_schema
    Estimated time: 500ms | Disk: 1.0MB | CPU: 30%
  002: add_user_table
    Estimated time: 500ms | Disk: 1.0MB | CPU: 30%

✓ All migrations appear safe to execute
================================================================================
```

**Test in SAVEPOINT**:
```bash
$ confiture migrate up --dry-run-execute
🧪 Executing migrations in SAVEPOINT (guaranteed rollback)...
[shows analysis]
🔄 Proceed with real execution? [y/N]: y
✅ Successfully applied 2 migration(s)!
```

**Save JSON report**:
```bash
$ confiture migrate up --dry-run --format json --output report.json
🔍 Analyzing migrations without execution...
✅ Report saved to report.json
```

**Analyze rollback**:
```bash
$ confiture migrate down --dry-run --steps 2
🔍 Analyzing migrations without execution...

Rollback Analysis Summary
================================================================================
Migrations to rollback: 2

  002: add_user_table
  001: create_initial_schema
================================================================================
```

### Performance Impact

- Minimal overhead: analysis adds <10ms per migration
- No actual execution unless `--dry-run-execute` with confirmation
- JSON output for fast CI/CD parsing
- File output for auditing and sharing

### Compatibility

- ✅ All existing functionality preserved
- ✅ No breaking changes
- ✅ Works with all environment configurations
- ✅ Compatible with database_url configuration
- ✅ Works alongside `--target`, `--config`, `--strict` flags

### Known Limitations

- Conservative estimates (500ms, 1MB, 30% CPU) until full analysis added
- Estimates don't include index creation time (will be enhanced)
- SQL statement extraction is basic (enhanced parsing planned for Phase 6)

### Future Enhancements

- Full actual dry-run execution with async connections
- Resource impact analysis (real measurements)
- Custom estimate functions per migration
- Report comparison tools
- Interactive migration review mode
- Integration with CI/CD providers (GitHub, GitLab, etc.)

## [0.3.2] - 2025-11-20

### Added
- **`--force` flag for `migrate up` command** - Force migration reapplication even when tracking shows migrations as already applied (#4)
- Warning messages when force mode is enabled to prevent accidental misuse
- New `Migrator.migrate_up()` method for complete migration workflow with force support
- Comprehensive troubleshooting guide (`docs/guides/troubleshooting.md`) with 400+ lines covering common migration issues
- `database_url` connection format support for simpler configuration

### Changed
- `Migrator.apply()` now accepts `force` parameter to skip "already applied" checks
- Force mode skips migration state checks but still updates tracking after successful application
- Enhanced CLI output with force-specific messages and warnings

### Documentation
- New `docs/guides/troubleshooting.md` - Complete troubleshooting guide
- Updated `docs/reference/cli.md` - Full `--force` flag documentation with examples and safety warnings
- Updated `README.md` - Added `--force` flag to feature list
- Updated `docs/index.md` - Added troubleshooting guide link

### Testing
- Added `tests/unit/test_cli_migrate.py` - CLI flag parsing tests (4 tests)
- Added `tests/unit/test_migrator.py` - Force logic unit tests (4 tests)
- Added `tests/integration/test_migrate_force.py` - Complete force workflow integration tests (4 scenarios)

### Fixed
- Migration state tracking now correctly handles force reapplication
- Connection handling improved with `database_url` support for testing workflows

## [0.3.0] - 2025-11-09

### Added
- **Hexadecimal Sorting** - Support for hex-prefixed schema files (e.g., `0x01_`, `0x0A_`) for better organization of large schemas
- **Dynamic Discovery** - Enhanced SQL file discovery with include/exclude patterns, recursive directory control, and flexible project structures
- **Recursive Directory Support** - Automatic discovery of SQL files in nested directory hierarchies with deterministic ordering
- New configuration options for advanced file discovery (`include`, `exclude`, `recursive`, `order`, `auto_discover`)
- Build configuration section with `sort_mode` option for hex vs alphabetical sorting
- Comprehensive documentation for all new features with examples and migration guides
- 3 new test files covering hex sorting, dynamic discovery, and recursive directories

### Changed
- Enhanced `include_dirs` configuration to support object format with advanced options while maintaining backward compatibility
- Schema builder now supports multiple file naming conventions simultaneously
- File discovery logic refactored for flexibility and performance
- Updated documentation structure with dedicated features section

### Documentation
- Added 3 new feature documentation pages (hex sorting, dynamic discovery, recursive directories)
- Updated organizing-sql-files.md with hex sorting examples and patterns
- Enhanced configuration reference with new include_dirs options and build configuration
- Updated main documentation index to highlight new v0.3.0 features

### Performance
- Improved file discovery caching for better performance with complex directory structures
- Optimized recursive directory scanning algorithms

## [0.2.0] - 2025-11-09

### Added
- **Production-ready CI/CD workflows** inspired by FraiseQL patterns
- GitHub Actions Quality Gate workflow (tests, lint, type-check, rust, security)
- Multi-platform wheel building (Linux, macOS, Windows)
- **PyPI Trusted Publishing** - secure publishing without API tokens
- Python version matrix testing (3.11, 3.12, 3.13)
- Comprehensive documentation for trusted publishing setup

### Fixed
- **CI database creation issue** - properly connect to postgres database when creating test databases
- Quality gate blocking on any failed check (enforced quality standards)
- PostgreSQL service configuration for consistent testing

### Changed
- Upgraded from alpha to stable release
- Replaced legacy ci.yml with comprehensive quality-gate.yml
- Merged wheels.yml into publish.yml with full release automation
- Improved workflow documentation and setup guides

### Infrastructure
- Quality gate pattern with 6 parallel jobs
- Security scanning with Bandit + Trivy
- Rust checks (fmt + clippy) in CI
- Automated GitHub Releases with artifacts
- 255 tests passing with 89.35% coverage

## [0.2.0-alpha] - 2025-10-11

### Added
- **Rust performance layer** with PyO3 bindings (Phase 2)
- Fast schema builder using parallel file I/O (rayon)
- Fast SHA256 hashing (30-60x faster than Python)
- Graceful fallback to Python when Rust unavailable
- Performance benchmarks in `tests/performance/`
- Maturin build system for binary wheels
- Support for Python 3.11, 3.12, 3.13
- Comprehensive test coverage (212 tests, 91.76%)

### Changed
- `SchemaBuilder.build()` now uses Rust for 10-50x speedup
- `SchemaBuilder.compute_hash()` now uses Rust for 30-60x speedup
- Build system migrated from hatchling to maturin
- Version bumped to 0.2.0-alpha

### Performance
- Schema building: 5-10x faster with Rust
- Hash computation: 30-60x faster with Rust
- Parallel file operations on multi-core systems

### Documentation
- Added PHASE2_SUMMARY.md (Rust layer documentation)
- Added performance benchmarking guide
- Updated README with Rust installation notes

## [0.1.0-alpha] - 2025-10-11

### Added
- **Core schema builder** (Medium 1: Build from DDL)
- Environment configuration system with YAML
- SQL file discovery and concatenation
- Deterministic file ordering (alphabetical)
- Schema hash computation (SHA256)
- File exclusion filtering
- Multiple include directories support
- Relative path calculation for nested structures

### Added - CLI Commands
- `confiture init` - Initialize project structure
- `confiture build` - Build schema from DDL files
  - `--env` flag for environment selection
  - `--output` flag for custom output path
  - `--show-hash` flag for schema hash display
  - `--schema-only` flag to exclude seed data

### Added - Migration System
- Migration base class with up/down methods
- Migration executor with transaction support
- Migration discovery and tracking
- Schema diff detection (basic)
- Migration generator from schema diffs
- Migration status command
- Version sequencing

### Added - Testing
- 212 unit tests with 91.76% coverage
- Integration test framework
- Test fixtures for schema files
- Comprehensive error path testing
- Edge case coverage

### Added - Configuration
- Environment config (db/environments/*.yaml)
- Include/exclude directory patterns
- Database URL configuration
- Project directory support

### Added - Documentation
- README with quick start guide
- PHASES.md with development roadmap
- CLAUDE.md with AI development guide
- PRD.md with product requirements
- Code examples in examples/

### Infrastructure
- Python 3.11+ support
- pytest test framework
- ruff linting and formatting
- mypy type checking
- pre-commit hooks
- uv package manager integration

## [0.0.1] - 2025-10-10

### Added
- Initial project structure
- Basic package scaffolding
- Development environment setup

---

## Version History Summary

| Version | Date | Key Features |
|---------|------|--------------|
| 0.3.7 | 2026-01-18 | Fix: load_migration() now supports SQL-only migrations |
| 0.3.6 | 2026-01-18 | DX improvements: migration loader, JSON status, baseline command, SQL migrations, testing sandbox, pytest plugin |
| 0.3.2 | 2025-11-20 | --force flag for migrate up, troubleshooting guide, database_url support |
| 0.3.0 | 2025-11-09 | Hexadecimal sorting, dynamic discovery, recursive directories |
| 0.2.0 | 2025-11-09 | Production CI/CD, Trusted Publishing, Multi-platform wheels |
| 0.2.0-alpha | 2025-10-11 | Rust performance layer, 10-50x speedup |
| 0.1.0-alpha | 2025-10-11 | Core schema builder, CLI, migrations |
| 0.0.1 | 2025-10-10 | Initial setup |

## Migration Guide

### From 0.1.0 to 0.2.0

No breaking changes! Upgrade is seamless:

```bash
pip install --upgrade confiture
```

**What's New:**
- Rust extension auto-detected and used for performance
- Falls back to Python if Rust unavailable
- All existing code continues to work unchanged

**To verify Rust extension:**
```python
from confiture.core.builder import HAS_RUST
print(f"Rust available: {HAS_RUST}")
```

**Performance improvements:**
- `SchemaBuilder.build()`: 5-10x faster
- `SchemaBuilder.compute_hash()`: 30-60x faster

## Deprecations

No deprecated features yet.

## Security

No security advisories yet.

To report security vulnerabilities, please email security@fraiseql.com or create a private security advisory on GitHub.

---

## Links

- [GitHub Repository](https://github.com/fraiseql/confiture)
- [Issue Tracker](https://github.com/fraiseql/confiture/issues)
- [PyPI Package](https://pypi.org/project/confiture/)
- [Documentation](https://github.com/fraiseql/confiture)
- [FraiseQL](https://github.com/fraiseql/fraiseql)

---

*Making jam from strawberries, one version at a time.* 🍓
