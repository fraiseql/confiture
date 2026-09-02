"""Coverage guard: what the Python-migration extractor can reach is a pinned table.

This repository has under-reported silently twice — #121 (the analyzer
no-op'd on Python migrations) and the pglast-8 enum renumbering (replica-unsafe
migrations scored ``window_safe: true``). Both were "the analyzer sees less
than it used to", and neither was a number anyone could watch. This table is
that number, per argument shape. Widening the extractor is an edit here, in a
diff a reviewer reads; narrowing it, by any refactor, fails the row that
regressed.

The fixtures live in ``tests/fixtures/idempotency_shapes/`` (a small project
with its own ``pyproject.toml`` anchor). Every statement in them is
idempotent: the table measures *reach*, not findings.
"""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path

import pytest

from confiture.core.idempotency.python_migration_extractor import (
    extract_sql_from_python_migration,
    is_migration_file,
)

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "idempotency_shapes"
MIGRATIONS = FIXTURE_ROOT / "db" / "migrations"

# (resolved calls, {warning kind: count}) per fixture — what the extractor
# does today, recorded from a run, not what anyone wishes it did. Rows moved
# in 0.46.0 when the static evaluator landed (names, paths, string
# operations, reader helpers); each move was a reviewed edit here.
EXPECTED: dict[str, tuple[int, dict[str, int]]] = {
    "20260101000001_literal.py": (1, {}),
    "20260101000002_static_fstring.py": (1, {}),
    "20260101000003_concat.py": (1, {}),
    "20260101000004_keyword_sql.py": (1, {}),
    "20260101000005_execute_file_literal.py": (1, {}),
    "20260101000006_read_text_literal.py": (1, {}),
    "20260101000007_module_constant.py": (1, {}),
    "20260101000008_module_constant_concat.py": (2, {}),
    "20260101000009_annotated_constant.py": (1, {}),
    "20260101000010_constant_below_class.py": (1, {}),
    "20260101000011_class_attribute.py": (1, {}),
    "20260101000012_local_single_assignment.py": (1, {}),
    "20260101000013_file_relative_path.py": (1, {}),
    "20260101000014_reader_helper_function.py": (1, {}),
    "20260101000015_reader_helper_method.py": (1, {}),
    "20260101000016_string_ops_on_constant.py": (3, {}),
    "20260101000017_fstring_over_static_local.py": (1, {}),
    "20260101000018_loop_variable_fstring.py": (0, {"unresolved_fstring": 1}),
    "20260101000019_parameter.py": (0, {"dynamic_execute": 1}),
    "20260101000020_rebound_module_name.py": (0, {"dynamic_execute": 1}),
    "20260101000021_augassign.py": (0, {"dynamic_execute": 1}),
    "20260101000022_global_rebind.py": (0, {"dynamic_execute": 2}),
    "20260101000023_loop_target_shadows_module_constant.py": (0, {"dynamic_execute": 1}),
    "20260101000024_subscript_non_literal_key.py": (0, {"dynamic_execute": 1}),
    "20260101000025_unbound_name.py": (0, {"dynamic_execute": 1}),
    "20260101000026_percent_format.py": (0, {"dynamic_execute": 1}),
    "20260101000027_execute_file_computed.py": (1, {}),
    "20260101000028_execute_file_missing.py": (0, {"execute_file_missing": 1}),
    "20260101000029_execute_file_escaped.py": (0, {"execute_file_escaped": 1}),
    "20260101000030_syntax_error.py": (0, {"syntax_error": 1}),
    "20260101000031_multi_statement_helper.py": (0, {"dynamic_execute": 1}),
    "20260101000032_fstring_conversion.py": (0, {"unresolved_fstring": 1}),
    "20260101000033_guard_helper_fstring.py": (1, {}),
    "20260101000034_class_attribute_path.py": (1, {}),
    "20260101000035_pathlib_variants.py": (1, {}),
}


def _observe(migration: Path) -> tuple[int, dict[str, int]]:
    result = extract_sql_from_python_migration(migration, project_root=FIXTURE_ROOT)
    return len(result.snippets), dict(Counter(w.kind.value for w in result.warnings))


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_shape_reach_is_pinned(name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # From a foreign cwd on purpose: reach must not depend on where the gate runs.
    monkeypatch.chdir(tmp_path)

    assert _observe(MIGRATIONS / name) == EXPECTED[name]


def test_every_fixture_has_a_row_and_every_row_a_fixture() -> None:
    """A shape cannot be added, or dropped, without the table saying so."""
    on_disk = {p.name for p in MIGRATIONS.glob("*.py") if is_migration_file(p)}

    assert on_disk == set(EXPECTED)


# Resolved calls ÷ every execute/execute_file call, over the reporter's real
# corpus (251 migrations). Measured 2026-09-02: 901 of 1361 after the shared
# path resolver, 1294 of 1361 once the static evaluator landed. Raise it when
# the extractor's reach grows; never lower it.
CORPUS_FLOOR = 0.95


def test_real_corpus_reach_never_drops() -> None:
    corpus_dir = os.environ.get("CONFITURE_CORPUS_DIR")
    if not corpus_dir:
        pytest.skip("set CONFITURE_CORPUS_DIR to a directory of real .py migrations")
    corpus = Path(corpus_dir)
    resolved = unresolved = 0
    for migration in sorted(corpus.glob("*.py")):
        if not is_migration_file(migration):
            continue
        result = extract_sql_from_python_migration(migration)
        resolved += len(result.snippets)
        unresolved += len(result.warnings)

    assert resolved + unresolved > 0, f"no execute calls found under {corpus}"
    ratio = resolved / (resolved + unresolved)
    assert ratio >= CORPUS_FLOOR, (
        f"extractor reach dropped to {ratio:.4f} ({resolved}/{resolved + unresolved}); "
        f"floor is {CORPUS_FLOOR}"
    )
