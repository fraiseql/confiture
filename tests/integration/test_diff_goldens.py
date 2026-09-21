"""``migrate diff`` still says, about every example tree, what it said at ``6f94788b``.

The model campaign rewrites how confiture reads DDL. These goldens are its only
evidence that the rewrite preserved behaviour: each is the CLI's own output —
the JSON on stdout, the exit code, and the DDL ``--generate`` writes — for a
tree's every object (``--from`` an empty file) and for the before/after pair
``examples/03`` ships. ``scripts/refresh_model_goldens.py`` records them.

A golden that changes on purpose is refreshed with ``--write`` in the same PR,
and the reason is named in ``CHANGELOG.md`` under ``## [Unreleased]``.
"""

from __future__ import annotations

import difflib
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Example directories that declare no DDL of their own, and why.
NO_SCHEMA_TREE = {
    "07-external-emitter": "its schema is what an external emitter writes; the tree ships a .gitkeep",
}


def _load() -> ModuleType:
    script = REPO_ROOT / "scripts" / "refresh_model_goldens.py"
    spec = importlib.util.spec_from_file_location("refresh_model_goldens", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered first: `@dataclass` resolves its fields through sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


goldens = _load()


def _explain(live: dict[str, str], on_disk: dict[str, str]) -> str:
    lines: list[str] = []
    for key in sorted(set(live) | set(on_disk)):
        if live.get(key) == on_disk.get(key):
            continue
        lines.extend(
            difflib.unified_diff(
                on_disk.get(key, "").splitlines(keepends=True),
                live.get(key, "").splitlines(keepends=True),
                fromfile=f"recorded/{key}",
                tofile=f"live/{key}",
            )
        )
    return "".join(lines)


@pytest.fixture(scope="module")
def live_diff() -> dict[str, str]:
    return goldens.diff_goldens()


def test_diff_goldens_are_recorded() -> None:
    assert goldens.recorded("diff"), (
        "tests/fixtures/model_goldens/diff/ is empty; "
        "record it with `uv run python scripts/refresh_model_goldens.py --write --only diff`"
    )


def test_migrate_diff_matches_its_goldens(live_diff: dict[str, str]) -> None:
    on_disk = goldens.recorded("diff")
    assert live_diff == on_disk, (
        "`migrate diff` output changed. If deliberate, run "
        "`uv run python scripts/refresh_model_goldens.py --write --only diff` and name "
        "the reason in CHANGELOG.md.\n" + _explain(live_diff, on_disk)
    )


def test_every_example_schema_tree_is_recorded() -> None:
    """A new example with DDL joins the goldens, or states why it cannot."""
    tracked = subprocess.run(
        ["git", "ls-files", "examples/*/db/*.sql", "examples/*/db/**/*.sql"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    with_ddl = {Path(path).parts[1] for path in tracked if "/seeds/" not in path}
    recorded = {tree.name.split(".")[0] for tree in goldens.TREES if tree.name != "db-schema"}
    unrecorded = sorted(with_ddl - recorded - set(NO_SCHEMA_TREE))
    assert not unrecorded, f"example trees with no model golden: {unrecorded}"
    stale = sorted(set(NO_SCHEMA_TREE) & with_ddl)
    assert not stale, f"NO_SCHEMA_TREE lists examples that now ship DDL: {stale}"
