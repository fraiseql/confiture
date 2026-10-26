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

#: The oldest system confiture's own wheel installs on (``manylinux_2_28`` image,
#: maturin's ``macosx_11_0`` arm64 floor): a dependency wheel that needs a newer
#: one does not install where confiture does, and its sdist compiles instead.
FLOORS: dict[str, tuple[int, int]] = {"manylinux_x86_64": (2, 28), "macosx_arm64": (11, 0)}

#: The fixed glibc each legacy manylinux tag stands for (PEP 600).
_LEGACY_MANYLINUX: dict[str, tuple[int, int]] = {
    "manylinux1": (2, 5),
    "manylinux2010": (2, 12),
    "manylinux2014": (2, 17),
}

_CPYTHON = re.compile(r"cp3(\d+)")
_MANYLINUX = re.compile(r"manylinux_(\d+)_(\d+)_x86_64")
_MACOSX = re.compile(r"macosx_(\d+)_(\d+)_(?:arm64|universal2)")
_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9_.\-]*)")
_NOT_EQUAL = re.compile(r"!=\s*([0-9][^,;\s]*)")


def _platform_fits(platform: str, target: str) -> bool:
    """Whether a wheel's platform tag installs on *target*, at confiture's own floor."""
    if platform == "any":
        return True
    if target == "manylinux_x86_64":
        version = (
            _LEGACY_MANYLINUX.get(platform.removesuffix("_x86_64"))
            if platform.endswith("_x86_64")
            else None
        )
        if version is None and (match := _MANYLINUX.fullmatch(platform)):
            version = (int(match.group(1)), int(match.group(2)))
        return version is not None and version <= FLOORS[target]
    if target == "macosx_arm64":
        match = _MACOSX.fullmatch(platform)
        return match is not None and (int(match.group(1)), int(match.group(2))) <= FLOORS[target]
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
    if len(parts) < 5:
        return False
    python, abi, platforms = parts[-3], parts[-2], parts[-1]
    # A compressed tag set (PEP 425) stands for every combination of its parts.
    return any(
        _python_fits(py, one_abi) for py in python.split(".") for one_abi in abi.split(".")
    ) and any(_platform_fits(tag, target) for tag in platforms.split("."))


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
        named = _NAME.match(requirement)
        if named is None:
            continue
        dist = named.group(1)
        for version in _NOT_EQUAL.findall(requirement.split(";", 1)[0]):
            if "*" in version:
                continue  # a range, not one release to look up
            if not missing(dist, version, files_of((dist, version))):
                stale.append(
                    f"{dist}!={version}: {version} now has every wheel; drop the exclusion"
                )
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
            # No --no-build: it would skip an sdist-only release and resolve an older one,
            # hiding exactly the gap this looks for.
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
    try:
        found = gaps()
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = (getattr(exc, "stderr", None) or str(exc)).strip()
        print(
            f"::{'error' if strict else 'warning'}::the dependency-wheel check could not run: {detail}"
        )
        return 1 if strict else 0
    for gap in found:
        print(f"::{'error' if strict else 'warning'}::{gap}")
    if not found:
        print("every dependency has a wheel for every platform confiture ships")
    return 1 if strict and found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
