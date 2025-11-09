# PyPI Trusted Publishing Setup

This document explains how to set up PyPI Trusted Publishing for the Confiture project.

## What is Trusted Publishing?

Trusted Publishing is PyPI's recommended method for publishing packages. It uses OpenID Connect (OIDC) to securely publish packages from GitHub Actions without needing API tokens.

**Benefits**:
- 🔒 No API tokens to manage or leak
- ✅ More secure than token-based publishing
- 🚀 Easier to set up and maintain
- 📦 Recommended by PyPI for all new projects

## Setup Steps

### 1. Create the Project on PyPI (First Time Only)

**Option A: Use the PyPI web interface**

1. Go to https://pypi.org/manage/account/publishing/
2. Click "Add a new pending publisher"
3. Fill in the form:
   - **PyPI Project Name**: `fraiseql-confiture`
   - **Owner**: `fraiseql` (or your GitHub org/username)
   - **Repository name**: `confiture`
   - **Workflow name**: `publish.yml`
   - **Environment name**: `release`
4. Click "Add"

**Option B: Let the first release create it automatically**

PyPI will automatically create the project on first publish if you have the right permissions.

### 2. Configure GitHub Environment (Optional but Recommended)

1. Go to your GitHub repository: https://github.com/fraiseql/confiture
2. Navigate to **Settings** → **Environments**
3. Click **New environment**
4. Name it: `release`
5. Add protection rules (recommended):
   - ✅ **Required reviewers**: Add yourself or team members
   - ✅ **Wait timer**: Add a 5-minute delay to prevent accidental releases
   - ✅ **Deployment branches**: Only allow `main` branch

This adds an extra safety layer - releases will require manual approval.

### 3. Create a Release Tag

To trigger a release, create and push a git tag:

```bash
# Make sure you're on main and up to date
git checkout main
git pull

# Create a tag (version should match pyproject.toml)
git tag v0.1.0

# Push the tag to trigger the workflow
git push origin v0.1.0
```

### 4. Monitor the Release

1. Go to **Actions** tab in GitHub
2. Watch the `Publish` workflow run
3. It will:
   - ✅ Run all tests
   - ✅ Run linting and type checking
   - ✅ Run security scans
   - ✅ Build wheels for Linux, macOS, Windows
   - ✅ Build source distribution
   - ✅ Validate all artifacts
   - ✅ Publish to PyPI (requires approval if you set up environment protection)
   - ✅ Create GitHub Release with artifacts

## Workflow Files

We have 3 workflow files:

### 1. `quality-gate.yml` - PR and Main Branch Protection
- Runs on every PR and push to main
- Tests, linting, type checking, Rust checks, security
- Must pass before merging PRs

### 2. `python-version-matrix.yml` - Multi-Version Testing
- Tests Python 3.11, 3.12, 3.13
- Ensures compatibility across all supported versions
- Runs on PR and main branch

### 3. `publish.yml` - PyPI Release
- **Triggers**: Only on tags matching `v*` (e.g., `v0.1.0`)
- **Requirements**: All tests must pass first
- **Builds**: Wheels for Linux, macOS, Windows + source distribution
- **Publishes**: To PyPI using trusted publishing
- **Creates**: GitHub Release with all artifacts

## Troubleshooting

### "Publishing to PyPI failed: Trusted publishing exchange failure"

**Solution**: Make sure you've registered the publisher on PyPI:
1. Go to https://pypi.org/manage/account/publishing/
2. Add the publisher with exact details:
   - Repository: `fraiseql/confiture`
   - Workflow: `publish.yml`
   - Environment: `release`

### "Workflow requires approval"

This is normal if you set up environment protection. Go to the Actions tab and approve the deployment.

### "Version already exists on PyPI"

You can't republish the same version. Increment the version in `pyproject.toml` and create a new tag.

## Version Bumping Checklist

Before creating a release tag:

- [ ] Update version in `pyproject.toml`
- [ ] Update version in `python/confiture/__init__.py`
- [ ] Update version in `Cargo.toml` (optional, can differ)
- [ ] Update `CHANGELOG.md` or release notes
- [ ] Run tests locally: `uv run pytest`
- [ ] Build locally to verify: `uv run maturin build --release`
- [ ] Commit changes: `git commit -am "chore: bump version to X.Y.Z"`
- [ ] Push to main: `git push`
- [ ] Create and push tag: `git tag vX.Y.Z && git push origin vX.Y.Z`

## Security Best Practices

✅ **DO**:
- Use trusted publishing (already configured)
- Set up environment protection for releases
- Review the publish workflow before approving
- Use semantic versioning (v1.0.0, v1.0.1, etc.)

❌ **DON'T**:
- Don't share PyPI API tokens (not needed with trusted publishing)
- Don't skip tests before releasing
- Don't release from feature branches (only from main)
- Don't reuse version numbers

## References

- [PyPI Trusted Publishing Guide](https://docs.pypi.org/trusted-publishers/)
- [GitHub Actions OIDC](https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/about-security-hardening-with-openid-connect)
- [Maturin Publishing](https://www.maturin.rs/distribution.html)

---

*Last updated: November 9, 2025*
