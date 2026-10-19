"""``scripts/check_dependency_wheels.py``: every dependency a fresh install picks has a wheel.

confiture ships a cp314 wheel for three platforms. A user on one of them gets
confiture's wheel and then every dependency PyPI's newest release offers, so a
dependency released as an sdist only (pglast 8.7, for its first hours) makes the
install compile C. These tests hold the script's reading of wheel filenames and
PyPI's file lists; none of them reaches the network.
"""

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def wheels():
    script = REPO_ROOT / "scripts" / "check_dependency_wheels.py"
    spec = importlib.util.spec_from_file_location("check_dependency_wheels", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


#: What PyPI listed for pglast 8.7 on 2026-10-18, some hours after its sdist.
PGLAST_87 = [
    "pglast-8.7.tar.gz",
    "pglast-8.7-cp314-cp314-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl",
    "pglast-8.7-cp314-cp314-macosx_11_0_arm64.whl",
    "pglast-8.7-cp314-cp314-win32.whl",
]


class TestAWheelFitsATarget:
    @pytest.mark.parametrize(
        ("filename", "target"),
        [
            ("x-1-cp314-cp314-manylinux_2_28_x86_64.whl", "manylinux_x86_64"),
            ("x-1-cp314-cp314-manylinux2014_x86_64.manylinux_2_17_x86_64.whl", "manylinux_x86_64"),
            ("x-1-cp314-cp314-macosx_11_0_arm64.whl", "macosx_arm64"),
            ("x-1-cp314-cp314-macosx_10_12_universal2.whl", "macosx_arm64"),
            ("x-1-cp314-cp314-win_amd64.whl", "win_amd64"),
            ("x-1-py3-none-any.whl", "win_amd64"),
            ("x-1-py2.py3-none-any.whl", "macosx_arm64"),
            ("x-1-cp39-abi3-win_amd64.whl", "win_amd64"),
            ("x-1-1build-cp314-cp314-win_amd64.whl", "win_amd64"),
            ("x-1-cp313.cp314-cp313.cp314-win_amd64.whl", "win_amd64"),
            ("x-1-cp314-cp314-manylinux1_x86_64.whl", "manylinux_x86_64"),
        ],
    )
    def test_fits(self, wheels, filename: str, target: str) -> None:
        assert wheels.fits(filename, target)

    @pytest.mark.parametrize(
        ("filename", "target"),
        [
            ("x-1-cp314-cp314-win32.whl", "win_amd64"),
            ("x-1-cp314-cp314t-win_amd64.whl", "win_amd64"),
            ("x-1-cp313-cp313-win_amd64.whl", "win_amd64"),
            ("x-1-cp314-cp314-musllinux_1_2_x86_64.whl", "manylinux_x86_64"),
            ("x-1-cp314-cp314-manylinux_2_28_aarch64.whl", "manylinux_x86_64"),
            ("x-1-cp314-cp314-macosx_10_15_x86_64.whl", "macosx_arm64"),
            ("x-1.tar.gz", "win_amd64"),
            # Newer systems than confiture's own wheel installs on (release review).
            ("x-1-cp314-cp314-manylinux_2_34_x86_64.whl", "manylinux_x86_64"),
            ("x-1-cp314-cp314-macosx_14_0_arm64.whl", "macosx_arm64"),
            ("x-1.whl", "win_amd64"),
        ],
    )
    def test_does_not_fit(self, wheels, filename: str, target: str) -> None:
        assert not wheels.fits(filename, target)


def test_a_dependency_with_every_wheel_is_not_reported(wheels) -> None:
    files = ["x-1-py3-none-any.whl"]

    assert wheels.missing("x", "1", files) == []


def test_an_sdist_only_release_names_every_target(wheels) -> None:
    gaps = wheels.missing("pglast", "8.7", ["pglast-8.7.tar.gz"])

    assert gaps == [
        "pglast 8.7: no wheel for cp314 manylinux_x86_64",
        "pglast 8.7: no wheel for cp314 macosx_arm64",
        "pglast 8.7: no wheel for cp314 win_amd64",
    ]


def test_a_windows_only_gap_is_named(wheels) -> None:
    """The fresh installs run on Linux: this is the gap they cannot see."""
    assert wheels.missing("pglast", "8.7", PGLAST_87) == [
        "pglast 8.7: no wheel for cp314 win_amd64"
    ]


def test_an_exclusion_whose_version_now_has_every_wheel_is_stale(wheels) -> None:
    files = {("pglast", "8.7"): [*PGLAST_87, "pglast-8.7-cp314-cp314-win_amd64.whl"]}

    stale = wheels.stale_exclusions(["pglast>=8.5,!=8.7", "rich>=13.7"], files.__getitem__)

    assert stale == ["pglast!=8.7: 8.7 now has every wheel; drop the exclusion"]


def test_an_exclusion_still_missing_a_wheel_stands(wheels) -> None:
    files = {("pglast", "8.7"): PGLAST_87}

    assert wheels.stale_exclusions(["pglast>=8.5,!=8.7"], files.__getitem__) == []


def test_the_targets_are_the_platforms_confiture_ships_wheels_for(wheels) -> None:
    """Read from ``publish.yml``: linux x86_64 by cibuildwheel, then macos-latest and windows-latest."""
    import yaml

    publish = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "publish.yml").read_text())
    job = publish["jobs"]["build-wheels"]
    runners = {entry["os"] for entry in job["strategy"]["matrix"]["include"]}
    linux = next(step for step in job["steps"] if "cibuildwheel" in step.get("uses", ""))
    built = {
        "ubuntu-latest": f"manylinux_{linux['env']['CIBW_ARCHS']}",
        "macos-latest": "macosx_arm64",
        "windows-latest": "win_amd64",
    }

    assert {built[runner] for runner in runners} == set(wheels.TARGETS)


def test_every_exclusion_in_a_requirement_is_checked_and_a_range_is_skipped(wheels) -> None:
    files = {("x", "2.0"): ["x-2.0-py3-none-any.whl"], ("x", "2.1"): ["x-2.1-py3-none-any.whl"]}

    stale = wheels.stale_exclusions(["x>=1,!=2.0,!=2.1,!=3.*"], files.__getitem__)

    assert [line.split(":")[0] for line in stale] == ["x!=2.0", "x!=2.1"]
