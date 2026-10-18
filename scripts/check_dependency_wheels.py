#!/usr/bin/env python3
"""Every dependency a fresh install picks has a wheel for every platform confiture ships.

confiture publishes a cp314 wheel for three platforms (``publish.yml``). A user on
one of them installs that wheel, then each dependency at the newest version PyPI
offers, whatever confiture's lockfile says. A dependency released as an sdist only,
as pglast 8.7 was for its first hours, makes that install compile C: it fails on a
machine with no compiler, and CI's fresh installs fail with a compile error that
names neither the dependency nor the reason. This script names them.

The runtime closure is resolved per platform by ``uv pip compile`` (transitive
dependencies and platform markers included, no lockfile), and each pinned
``<dist> <version>`` is looked up in PyPI's JSON API.

Usage:
    python scripts/check_dependency_wheels.py --warn     # pull requests: annotate, exit 0
    python scripts/check_dependency_wheels.py --strict   # Publish: exit 1 on any gap

``--strict`` also fails on an exclusion (``pkg!=X``) whose version now has every
wheel, so a workaround cannot outlive its reason. Upstream uploads an sdist before
its wheels, so on a pull request a gap is a warning: a blocking check would turn red
in every upstream release window.
"""

import json
import re
import subprocess
import sys
import tomllib
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The CPython confiture ships wheels for.
PYTHON = 314

#: Each platform ``publish.yml`` builds a confiture wheel for, and how ``uv`` names it.
TARGETS: dict[str, str] = {
    "manylinux_x86_64": "x86_64-manylinux_2_28",
    "macosx_arm64": "aarch64-apple-darwin",
    "win_amd64": "x86_64-pc-windows-msvc",
}

_CPYTHON = re.compile(r"cp3(\d+)")
_EXCLUSION = re.compile(r"^([A-Za-z0-9_.\-]+).*?!=\s*([0-9][^,;\s]*)")


def _platform_fits(platform: str, target: str) -> bool:
    if platform == "any":
        return True
    if target == "manylinux_x86_64":
        return platform.startswith("manylinux") and platform.endswith("_x86_64")
    if target == "macosx_arm64":
        return platform.startswith("macosx_") and platform.endswith(("_arm64", "_universal2"))
    return platform == target


def _python_fits(python: str, abi: str) -> bool:
    if python in {"py3", "py2.py3"} or python.startswith("py3"):
        return abi == "none"
    match = _CPYTHON.fullmatch(python)
    if match is None:
        return False
    minor = int(match.group(1))
    if abi == "abi3":
        return minor <= PYTHON % 100
    return minor == PYTHON % 100 and abi in {f"cp{PYTHON}", "none"}


def fits(filename: str, target: str) -> bool:
    """Whether the wheel *filename* installs on cp314 for *target*."""
    if not filename.endswith(".whl"):
        return False
    parts = filename[: -len(".whl")].split("-")
    python, abi, platforms = parts[-3], parts[-2], parts[-1]
    return any(_python_fits(tag, abi) for tag in python.split(".")) and any(
        _platform_fits(tag, target) for tag in platforms.split(".")
    )


def missing(
    dist: str, version: str, files: Sequence[str], targets: Sequence[str] = tuple(TARGETS)
) -> list[str]:
    """One sentence per target in *targets* that *files* has no wheel for."""
    return [
        f"{dist} {version}: no wheel for cp{PYTHON} {target}"
        for target in targets
        if not any(fits(name, target) for name in files)
    ]


def stale_exclusions(
    requirements: Sequence[str], files_of: Callable[[tuple[str, str]], Sequence[str]]
) -> list[str]:
    """An exclusion whose version now has every wheel: the reason for it is gone."""
    stale = []
    for requirement in requirements:
        match = _EXCLUSION.match(requirement)
        if match is None:
            continue
        dist, version = match.group(1), match.group(2)
        if not missing(dist, version, files_of((dist, version))):
            stale.append(f"{dist}!={version}: {version} now has every wheel; drop the exclusion")
    return stale


def _pypi_files(key: tuple[str, str]) -> list[str]:
    dist, version = key
    url = f"https://pypi.org/pypi/{dist}/{version}/json"
    with urllib.request.urlopen(url, timeout=30) as response:  # nosec B310: a fixed https URL
        return [entry["filename"] for entry in json.load(response)["urls"]]


def _resolved(uv_platform: str) -> dict[str, str]:
    """``{dist: version}`` a fresh install picks on *uv_platform*, transitive dependencies included."""
    output = subprocess.run(  # nosec B603 B607: uv with fixed arguments
        [
            "uv",
            "pip",
            "compile",
            str(REPO_ROOT / "pyproject.toml"),
            "--python-version",
            f"3.{PYTHON % 100}",
            "--python-platform",
            uv_platform,
            "--no-header",
            "--no-annotate",
            "--refresh",
            "--quiet",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    pins = (line.split("==", 1) for line in output.splitlines() if "==" in line)
    return {dist.strip(): version.strip() for dist, version in pins}


def _requirements() -> list[str]:
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return list(project["project"]["dependencies"])


def gaps() -> list[str]:
    """Every missing wheel across the targets, then every stale exclusion."""
    files: dict[tuple[str, str], list[str]] = {}

    def files_of(key: tuple[str, str]) -> list[str]:
        if key not in files:
            files[key] = _pypi_files(key)
        return files[key]

    found = [
        gap
        for target, uv_platform in TARGETS.items()
        for dist, version in sorted(_resolved(uv_platform).items())
        for gap in missing(dist, version, files_of((dist, version)), (target,))
    ]
    return found + stale_exclusions(_requirements(), files_of)


def main(argv: Sequence[str]) -> int:
    strict = "--strict" in argv
    if not strict and "--warn" not in argv:
        print(__doc__)
        return 2
    found = gaps()
    for gap in found:
        print(f"::{'error' if strict else 'warning'}::{gap}")
    if not found:
        print("every dependency has a wheel for every platform confiture ships")
    return 1 if strict and found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
