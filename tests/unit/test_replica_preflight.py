"""Unit tests for the preflight replica surface (#154).

Covers the ".py can't-see" blind spot (Phase 2): the replica classifier reads
``*.up.sql`` only, so a ``DROP COLUMN`` inside a Python migration used to produce
no finding at all — making "no replica issue" ambiguous between *inspected-and-safe*
and *never-inspected*. The surface now emits ``PFLIGHT_REPLICA_UNCLASSIFIED`` for
migrations it cannot read, so the presence rule covers them.
"""

from __future__ import annotations

from pathlib import Path

from confiture.core.linting.libraries.replica import replica_preflight_issues
from confiture.core.preflight import is_window_safe, run_preflight


def test_py_migration_emits_unclassified(tmp_path: Path) -> None:
    """A `.py` migration the classifier can't read surfaces as UNCLASSIFIED."""
    (tmp_path / "20260606120000_data.py").write_text(
        "def up(cur):\n    cur.execute('ALTER TABLE t DROP COLUMN c')\n"
    )
    issues = replica_preflight_issues(tmp_path, has_replicas=False, bypass=False)
    unclassified = [i for i in issues if i.code == "PFLIGHT_REPLICA_UNCLASSIFIED"]
    assert len(unclassified) == 1
    assert unclassified[0].severity == "warning"
    assert unclassified[0].file == "20260606120000_data.py"


def test_py_unclassified_is_warning_even_with_replicas(tmp_path: Path) -> None:
    """Opacity never hard-blocks: UNCLASSIFIED stays a warning even with replicas."""
    (tmp_path / "20260606120000_data.py").write_text("def up(cur):\n    pass\n")
    issues = replica_preflight_issues(tmp_path, has_replicas=True, bypass=False)
    unclassified = [i for i in issues if i.code == "PFLIGHT_REPLICA_UNCLASSIFIED"]
    assert unclassified and all(i.severity == "warning" for i in unclassified)


def test_dunder_and_underscore_py_not_flagged(tmp_path: Path) -> None:
    """`__init__.py` and `_`-prefixed helpers are not migrations (discovery filter)."""
    (tmp_path / "__init__.py").write_text("")
    (tmp_path / "_helpers.py").write_text("X = 1\n")
    issues = replica_preflight_issues(tmp_path, has_replicas=False, bypass=False)
    assert issues == []


def test_sql_only_dir_has_no_unclassified(tmp_path: Path) -> None:
    """A readable SQL migration is classified, not marked unclassified."""
    (tmp_path / "20260606120000_safe.up.sql").write_text("CREATE TABLE t (id int);")
    issues = replica_preflight_issues(tmp_path, has_replicas=False, bypass=False)
    assert all(i.code != "PFLIGHT_REPLICA_UNCLASSIFIED" for i in issues)


def _all_issues(migrations_dir: Path):
    """The full preflight issue set the CLI builds: static + replica findings."""
    static = run_preflight(migrations_dir).issues
    replica = replica_preflight_issues(migrations_dir, has_replicas=False, bypass=False)
    return static + replica


def test_is_window_safe_false_on_replica_unsafe_op(tmp_path: Path) -> None:
    """A replica-unsafe op (DROP COLUMN) makes the window unsafe (#154)."""
    (tmp_path / "20260606120000_drop.up.sql").write_text("ALTER TABLE t DROP COLUMN c;")
    (tmp_path / "20260606120000_drop.down.sql").write_text("ALTER TABLE t ADD COLUMN c int;")
    assert is_window_safe(_all_issues(tmp_path)) is False


def test_is_window_safe_false_on_unreadable_py(tmp_path: Path) -> None:
    """A `.py` migration the classifier can't read makes the window unsafe (#154)."""
    (tmp_path / "20260606120000_data.py").write_text("def up(cur):\n    pass\n")
    assert is_window_safe(_all_issues(tmp_path)) is False


def test_is_window_safe_true_despite_missing_down(tmp_path: Path) -> None:
    """Reversibility is NOT a window-safety property — a forward-compatible op with
    no .down.sql is still window-safe (#154)."""
    (tmp_path / "20260606120000_add.up.sql").write_text("ALTER TABLE t ADD COLUMN c int;")
    # no .down.sql sibling → PFLIGHT_MISSING_DOWN, but window-safety ignores it
    assert is_window_safe(_all_issues(tmp_path)) is True


def test_is_window_safe_true_for_concurrent_index(tmp_path: Path) -> None:
    """CREATE INDEX CONCURRENTLY is the canonical online op — window-safe despite
    being non-transactional (#154)."""
    (tmp_path / "20260606120000_idx.up.sql").write_text(
        "CREATE INDEX CONCURRENTLY idx_t_c ON t (c);"
    )
    (tmp_path / "20260606120000_idx.down.sql").write_text("DROP INDEX idx_t_c;")
    assert is_window_safe(_all_issues(tmp_path)) is True


def test_is_window_safe_true_when_forward_compatible(tmp_path: Path) -> None:
    """A nullable ADD COLUMN is forward-compatible → window safe (#154)."""
    (tmp_path / "20260606120000_add.up.sql").write_text("ALTER TABLE t ADD COLUMN c int;")
    (tmp_path / "20260606120000_add.down.sql").write_text("ALTER TABLE t DROP COLUMN c;")
    assert is_window_safe(_all_issues(tmp_path)) is True
