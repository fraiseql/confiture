# Changelog

All notable changes to Confiture will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- GitHub Actions CI/CD for multi-platform wheel building
- Automated PyPI publishing via trusted publisher
- CI workflow for continuous testing across platforms

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
