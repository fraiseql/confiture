# Changelog

All notable changes to Confiture will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
