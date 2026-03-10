#!/usr/bin/env python3
"""Pre-commit hook: ensure version consistency across the project.

Single source of truth: pyproject.toml [project] version.
Synced targets:
  1. python/confiture/__init__.py  __version__ = "X.Y.Z"
  2. python/confiture/__init__.py  docstring   >>> print(__version__) / X.Y.Z

Exits 0 if everything is in sync.
Exits 1 if files were auto-fixed (pre-commit will require re-staging).
Exits 2 on hard errors (missing files, unparseable content).
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
INIT_FILE = ROOT / "python" / "confiture" / "__init__.py"

VERSION_RE_PYPROJECT = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)
VERSION_RE_INIT = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)
VERSION_RE_DOCSTRING = re.compile(r"(>>>\s*print\(__version__\)\n\s*)(\d+\.\d+(?:\.\d+)*)")


def read_pyproject_version() -> str | None:
    if not PYPROJECT.exists():
        return None
    match = VERSION_RE_PYPROJECT.search(PYPROJECT.read_text())
    return match.group(1) if match else None


def main() -> int:
    # ---- 1. Read canonical version from pyproject.toml ----
    canonical = read_pyproject_version()
    if canonical is None:
        print("ERROR: could not read version from pyproject.toml", file=sys.stderr)
        return 2

    if not INIT_FILE.exists():
        print(f"ERROR: {INIT_FILE} not found", file=sys.stderr)
        return 2

    source = INIT_FILE.read_text()
    modified = False

    # ---- 2. Sync __version__ assignment ----
    init_match = VERSION_RE_INIT.search(source)
    if not init_match:
        print(f"ERROR: could not find __version__ in {INIT_FILE}", file=sys.stderr)
        return 2

    if init_match.group(1) != canonical:
        source = VERSION_RE_INIT.sub(f'__version__ = "{canonical}"', source)
        modified = True
        print(f"Fixed: __version__ {init_match.group(1)} -> {canonical}")

    # ---- 3. Sync docstring version example ----
    source_after_docstring = VERSION_RE_DOCSTRING.sub(lambda m: m.group(1) + canonical, source)
    if source_after_docstring != source:
        source = source_after_docstring
        modified = True
        print(f"Fixed: docstring version example -> {canonical}")

    if modified:
        INIT_FILE.write_text(source)
        return 1  # pre-commit re-stages

    return 0


if __name__ == "__main__":
    sys.exit(main())
