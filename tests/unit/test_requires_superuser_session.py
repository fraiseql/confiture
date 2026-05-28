"""Unit tests for halt-at-first-skip semantics on MigratorSession.up (issue #137)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from confiture.config.environment import Environment
from confiture.core._migrator.session import MigratorSession


def _make_entered_session(migrations_dir: Path) -> MigratorSession:
    env = MagicMock(spec=Environment)
    env.database_url = "postgresql://localhost/test"
    env.migration = MagicMock()
    env.migration.tracking_table = "tb_confiture"

    session = MigratorSession(config=env, migrations_dir=migrations_dir)
    session._conn = MagicMock()
    session._migrator = MagicMock()
    return session


def _setup_three_pending(session, tmp_path):
    mdir = tmp_path / "migrations"
    mdir.mkdir(exist_ok=True)
    files = []
    for i in range(1, 4):
        f = mdir / f"0{i}_migration_{i}.up.sql"
        f.write_text(f"CREATE TABLE t{i} (id int);")
        files.append(f)
    session._migrations_dir = mdir
    session._migrator.find_migration_files.return_value = files
    session._migrator.find_pending.return_value = files
    session._migrator._version_from_filename.side_effect = lambda name: name.split("_")[0]
    return files


def _make_migration_class(version: str, name: str, *, requires_superuser: bool):
    """Build a MagicMock that mimics a Migration subclass."""
    inst = MagicMock()
    inst.version = version
    inst.name = name
    inst.requires_superuser = requires_superuser
    cls = MagicMock(return_value=inst)
    return cls


def test_up_halts_at_first_requires_superuser_migration(tmp_path):
    """Chain [a, b(superuser), c] → up applies a, halts at b, reports c as pending."""
    import confiture.core.migrator as _m

    session = _make_entered_session(tmp_path / "migrations")
    files = _setup_three_pending(session, tmp_path)

    cls_a = _make_migration_class("01", "a", requires_superuser=False)
    cls_b = _make_migration_class("02", "b", requires_superuser=True)
    cls_c = _make_migration_class("03", "c", requires_superuser=False)
    classes = {files[0]: cls_a, files[1]: cls_b, files[2]: cls_c}

    with patch.object(_m, "LockConfig"), patch.object(_m, "MigrationLock") as MockLock:
        mock_lock = MagicMock()
        mock_lock.acquire.return_value.__enter__ = MagicMock()
        mock_lock.acquire.return_value.__exit__ = MagicMock(return_value=False)
        MockLock.return_value = mock_lock

        with patch.object(_m, "load_migration_class", side_effect=lambda f: classes[f]):
            result = session.up()

    # Migration a applied, b skipped, c reported pending.
    assert result.success is False
    assert len(result.migrations_applied) == 1
    assert result.migrations_applied[0].version == "01"
    assert len(result.skipped_superuser) == 1
    assert result.skipped_superuser[0].version == "02"
    assert result.skipped_superuser[0].name == "b"
    assert "requires_superuser" in result.skipped_superuser[0].reason
    assert result.pending == ["03"]
    # apply() was called once (for a), never for b or c.
    assert session._migrator.apply.call_count == 1


def test_up_resumes_chain_after_apply_as_clears_skip(tmp_path):
    """Once b is no longer pending, up() picks up at c without halting."""
    import confiture.core.migrator as _m

    session = _make_entered_session(tmp_path / "migrations")
    files = _setup_three_pending(session, tmp_path)

    # Pretend b was already applied externally (via apply-as) by removing
    # it from the pending list.
    session._migrator.find_pending.return_value = [files[0], files[2]]

    cls_a = _make_migration_class("01", "a", requires_superuser=False)
    cls_c = _make_migration_class("03", "c", requires_superuser=False)
    classes = {files[0]: cls_a, files[2]: cls_c}

    with patch.object(_m, "LockConfig"), patch.object(_m, "MigrationLock") as MockLock:
        mock_lock = MagicMock()
        mock_lock.acquire.return_value.__enter__ = MagicMock()
        mock_lock.acquire.return_value.__exit__ = MagicMock(return_value=False)
        MockLock.return_value = mock_lock

        with patch.object(_m, "load_migration_class", side_effect=lambda f: classes[f]):
            result = session.up()

    assert result.success is True
    assert {m.version for m in result.migrations_applied} == {"01", "03"}
    assert result.skipped_superuser == []
    assert result.pending == []


def test_skipped_superuser_appears_in_json_output(tmp_path):
    """`MigrateUpResult.to_dict()` exposes skipped_superuser + pending."""
    import confiture.core.migrator as _m

    session = _make_entered_session(tmp_path / "migrations")
    files = _setup_three_pending(session, tmp_path)

    cls_a = _make_migration_class("01", "a", requires_superuser=False)
    cls_b = _make_migration_class("02", "b", requires_superuser=True)
    cls_c = _make_migration_class("03", "c", requires_superuser=False)
    classes = {files[0]: cls_a, files[1]: cls_b, files[2]: cls_c}

    with patch.object(_m, "LockConfig"), patch.object(_m, "MigrationLock") as MockLock:
        mock_lock = MagicMock()
        mock_lock.acquire.return_value.__enter__ = MagicMock()
        mock_lock.acquire.return_value.__exit__ = MagicMock(return_value=False)
        MockLock.return_value = mock_lock

        with patch.object(_m, "load_migration_class", side_effect=lambda f: classes[f]):
            result = session.up()

    payload = result.to_dict()
    assert "skipped_superuser" in payload
    assert payload["skipped_superuser"][0]["version"] == "02"
    assert payload["skipped_superuser"][0]["name"] == "b"
    assert payload["pending"] == ["03"]
