# Fix for Issue #1: Python 3.13 manylinux Wheel Distribution

## Problem

The fraiseql-confiture PyPI release v0.3.7 was missing the Python 3.13 Linux wheel:
- ✅ `cp313-cp313-macosx_11_0_arm64.whl` (macOS)
- ✅ `cp313-cp313-win_amd64.whl` (Windows)
- ❌ **MISSING: `cp313-cp313-manylinux_2_34_x86_64.whl`** (Linux)

This caused Docker builds using `python:3.13-slim` to fail because pip fell back to building from source (sdist), requiring Rust toolchain and build dependencies that aren't available in minimal Docker images.

## Root Cause

The original workflow used maturin-action with `--find-interpreter`, which only finds Python interpreters already installed in the GitHub runner environment. GitHub runners don't have all Python versions pre-installed, so only the Python version being used for other CI jobs was available for wheel building.

## Solution

Updated `.github/workflows/publish.yml` to use `cibuildwheel` for Linux builds:

### Key Changes

1. **Linux (Ubuntu)**: Switched from `maturin-action` to `cibuildwheel@v2.20.0`
   - Explicitly builds for `cp311-manylinux_x86_64`, `cp312-manylinux_x86_64`, and `cp313-manylinux_x86_64`
   - Uses `manylinux_2_34` for broad Linux distribution support
   - `cibuildwheel` manages multiple Python versions natively

2. **macOS & Windows**: Kept `maturin-action`
   - These platforms build all available Python versions via `--find-interpreter`
   - No issues were observed on these platforms

3. **Configuration**:
   ```yaml
   CIBW_BUILD: 'cp311-manylinux_x86_64 cp312-manylinux_x86_64 cp313-manylinux_x86_64'
   CIBW_MANYLINUX_X86_64_IMAGE: 'manylinux_2_34'
   ```

## Expected Results

Next release (e.g., v0.3.8+) will include:
- ✅ `cp313-cp313-manylinux_2_34_x86_64.whl` (Linux - **NEW**)
- ✅ `cp313-cp313-macosx_11_0_arm64.whl` (macOS)
- ✅ `cp313-cp313-win_amd64.whl` (Windows)
- Plus 3.11 and 3.12 variants for all platforms

## Testing the Fix

The fix will be validated when the next version is tagged and released:

```bash
# After tagging v0.3.8+:
# 1. GitHub Actions runs publish workflow
# 2. cibuildwheel builds cp313-manylinux_2_34_x86_64.whl on ubuntu-latest
# 3. Wheel is uploaded to PyPI
# 4. Docker builds should work:
docker build --build-arg PYTHON_VERSION=3.13 .
```

## Compatibility

- **Forward compatible**: Uses stable ABI (`PYO3_USE_ABI3_FORWARD_COMPATIBILITY`)
- **Broad Linux support**: manylinux_2_34 (glibc 2.34) covers:
  - Ubuntu 22.04+
  - Debian 12+
  - CentOS/RHEL 9+
  - Alpine 3.17+
  - Other distributions with glibc 2.34+

## Commit

- **Hash**: `ae84383`
- **Message**: `fix: build Python 3.13 manylinux wheels for Linux distributions (issue #1)`

## References

- Issue: https://github.com/fraiseql/confiture/issues/1
- cibuildwheel docs: https://cibuildwheel.pypa.io/
- Manylinux standard: https://www.python.org/dev/peps/pep-0513/
