# Release Guide

This document describes how to create and publish releases of Confiture.

## Prerequisites

- Push access to `github.com/fraiseql/confiture`
- PyPI account with maintainer access to `confiture` package
- GitHub repository configured with PyPI trusted publisher

## Release Process

### 1. Prepare Release

Update version numbers:

```bash
# Update version in Cargo.toml
sed -i 's/version = "0.2.0"/version = "0.3.0"/' Cargo.toml

# Update version in pyproject.toml
sed -i 's/version = "0.2.0-alpha"/version = "0.3.0"/' pyproject.toml

# Update PHASE2_SUMMARY.md or create PHASE3_SUMMARY.md
```

Run full test suite:

```bash
# Unit tests
uv run pytest tests/unit/ -v

# Integration tests (requires PostgreSQL)
uv run pytest tests/integration/ -v

# Performance benchmarks
uv run pytest tests/performance/ -v -m slow

# Linting
uv run ruff check .
uv run mypy python/confiture/

# Rust tests
cargo test
cargo clippy
```

### 2. Create Release Commit

```bash
git add Cargo.toml pyproject.toml
git commit -m "chore: bump version to 0.3.0"
git push origin main
```

### 3. Tag Release

```bash
# Create annotated tag
git tag -a v0.3.0 -m "Release v0.3.0

- Feature 1
- Feature 2
- Bug fix 3
"

# Push tag (triggers CI/CD)
git push origin v0.3.0
```

### 4. Monitor CI/CD

The tag push triggers `.github/workflows/wheels.yml`:

1. **Build wheels** for all platforms:
   - Linux: `manylinux2014_x86_64`
   - macOS: `macosx_11_0_arm64`, `macosx_10_12_x86_64`
   - Windows: `win_amd64`
   - Python: 3.11, 3.12, 3.13

2. **Test wheels** on each platform

3. **Publish to PyPI** (automatic with trusted publisher)

Monitor: https://github.com/fraiseql/confiture/actions

### 5. Create GitHub Release

1. Go to https://github.com/fraiseql/confiture/releases/new
2. Select tag: `v0.3.0`
3. Release title: `Confiture v0.3.0`
4. Description:

```markdown
## What's New

### Features
- New feature 1
- New feature 2

### Performance
- 10x faster schema building with Rust
- 30-60x faster hashing

### Bug Fixes
- Fixed bug 1
- Fixed bug 2

### Breaking Changes
- None (backward compatible)

## Installation

```bash
pip install confiture
```

## Upgrading

```bash
pip install --upgrade confiture
```

## Full Changelog

See [CHANGELOG.md](https://github.com/fraiseql/confiture/blob/main/CHANGELOG.md)
```

5. Click "Publish release"

### 6. Verify Release

```bash
# Create fresh virtual environment
python -m venv test_venv
source test_venv/bin/activate

# Install from PyPI
pip install confiture==0.3.0

# Verify Rust extension
python -c "from confiture import _core; print('✓ Rust extension available')"

# Test CLI
confiture --version
confiture init test_project

# Clean up
deactivate
rm -rf test_venv
```

### 7. Announce Release

- [ ] Update README.md with new version
- [ ] Post on Twitter/social media
- [ ] Update FraiseQL documentation if applicable
- [ ] Notify users via mailing list (if applicable)

## Hotfix Process

For urgent bug fixes:

```bash
# Create hotfix branch from tag
git checkout -b hotfix/v0.3.1 v0.3.0

# Apply fix
git commit -m "fix: critical bug in X"

# Bump version (patch)
# Update Cargo.toml: 0.3.0 -> 0.3.1
# Update pyproject.toml: 0.3.0 -> 0.3.1

# Tag and push
git tag -a v0.3.1 -m "Hotfix v0.3.1: Fix critical bug"
git push origin v0.3.1

# Merge back to main
git checkout main
git merge hotfix/v0.3.1
git push origin main
```

## Rollback Process

If a release has critical issues:

```bash
# Remove tag from GitHub
git push --delete origin v0.3.0

# Delete local tag
git tag -d v0.3.0

# Mark release as yanked on PyPI (cannot delete)
# 1. Go to https://pypi.org/manage/project/confiture/releases/
# 2. Find version 0.3.0
# 3. Click "Options" -> "Yank release"
# 4. Explain reason for yanking
```

Then follow hotfix process to release fixed version.

## Release Checklist

Before tagging:
- [ ] All tests pass locally
- [ ] Version bumped in Cargo.toml
- [ ] Version bumped in pyproject.toml
- [ ] CHANGELOG.md updated
- [ ] Documentation updated
- [ ] No uncommitted changes

After tagging:
- [ ] CI/CD completed successfully
- [ ] Wheels available on PyPI
- [ ] GitHub release created
- [ ] Release verified in clean environment
- [ ] Announcement posted

## Version Numbering

Confiture follows [Semantic Versioning](https://semver.org/):

- **MAJOR** (1.0.0 -> 2.0.0): Breaking API changes
- **MINOR** (0.2.0 -> 0.3.0): New features, backward compatible
- **PATCH** (0.2.0 -> 0.2.1): Bug fixes, backward compatible

### Pre-release Versions

- **Alpha** (0.1.0-alpha): Early development, API unstable
- **Beta** (0.2.0-beta): Feature complete, testing
- **RC** (1.0.0-rc1): Release candidate, final testing

## PyPI Trusted Publisher Setup

Confiture uses PyPI's trusted publisher feature for secure, automated releases.

### Initial Setup (Already Configured)

1. Go to https://pypi.org/manage/account/publishing/
2. Add new trusted publisher:
   - **PyPI Project Name**: `confiture`
   - **Owner**: `fraiseql`
   - **Repository name**: `confiture`
   - **Workflow name**: `wheels.yml`
   - **Environment name**: `pypi`

### How It Works

When `.github/workflows/wheels.yml` runs on a tag push:

1. GitHub Actions authenticates with PyPI via OIDC
2. No manual token/password needed
3. Wheels are automatically published
4. Secure, no credentials stored

## Troubleshooting

### Build Fails on CI

**Check Rust version**: Ensure CI uses compatible Rust version
```yaml
- uses: dtolnay/rust-toolchain@stable
```

**Check Python version**: Ensure Python 3.11+ in matrix
```yaml
python-version: ['3.11', '3.12', '3.13']
```

### Wheels Not Publishing

**Check environment**: Ensure `environment: pypi` in workflow
```yaml
environment:
  name: pypi
  url: https://pypi.org/p/confiture
permissions:
  id-token: write
```

**Check tag format**: Must be `v*` (e.g., `v0.3.0`)
```yaml
on:
  push:
    tags:
      - 'v*'
```

### Import Fails After Install

**Check wheel platform**: Ensure correct platform downloaded
```bash
pip install --only-binary :all: confiture
```

**Fallback to Python**: If Rust unavailable, should still work
```python
from confiture.core.builder import HAS_RUST
print(f"Rust available: {HAS_RUST}")
```

## Related Documentation

- [PHASES.md](PHASES.md) - Development phases
- [PHASE2_SUMMARY.md](PHASE2_SUMMARY.md) - Phase 2 completion
- [CLAUDE.md](CLAUDE.md) - Development guide
- [README.md](README.md) - User documentation

---

*Last Updated: October 11, 2025*
