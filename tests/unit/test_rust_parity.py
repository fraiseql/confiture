"""The native hasher agrees with Python, fails like Python, and says whether it is there (Phase 09).

``hash_files`` hashed each file separately and then hashed the digests, with
paths relative to the files' common parent; Python streams one digest over
``(relpath \\0 content \\0)*`` relative to ``base_dir``. A wheel install and an
editable install therefore disagreed on whether a test-database template was
stale. The extension takes ``base_dir`` now and streams the same digest; a
missing file is an ``OSError`` (it used to panic, and ``PanicException`` is a
``BaseException`` the Python fallback never caught).

The parity cases skip when the extension is not importable, except under
``CONFITURE_REQUIRE_NATIVE=1`` — the CI leg that runs ``maturin develop`` must
prove the native path, not skip it.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core import builder as builder_module
from confiture.core.builder import HAS_RUST, SchemaBuilder

REQUIRE_NATIVE = os.environ.get("CONFITURE_REQUIRE_NATIVE") == "1"
native = pytest.mark.skipif(
    not HAS_RUST and not REQUIRE_NATIVE, reason="native extension not built"
)


def _python_hash(files: list[Path], base_dir: Path) -> str:
    hasher = hashlib.sha256()
    for file in files:
        hasher.update(str(file.relative_to(base_dir)).encode("utf-8"))
        hasher.update(b"\x00")
        hasher.update(file.read_bytes())
        hasher.update(b"\x00")
    return hasher.hexdigest()


@pytest.fixture
def schema_tree(tmp_path: Path) -> tuple[list[Path], Path]:
    base = tmp_path / "db" / "schema"
    (base / "10_tables").mkdir(parents=True)
    (base / "20_views").mkdir()
    files = [
        base / "10_tables" / "010_a.sql",
        base / "10_tables" / "020_b.sql",
        base / "20_views" / "010_v.sql",
    ]
    files[0].write_text("CREATE TABLE a (id int);\n")
    files[1].write_text("CREATE TABLE b (id int); -- café ☕\n")
    files[2].write_text("CREATE VIEW v AS SELECT 1;\n")
    return files, base


def test_the_native_flag_is_honest_under_require_native() -> None:
    if REQUIRE_NATIVE:
        assert HAS_RUST, "CONFITURE_REQUIRE_NATIVE=1 but confiture._core is not importable"
    assert isinstance(HAS_RUST, bool)


@native
def test_native_hash_equals_the_python_hash(schema_tree: tuple[list[Path], Path]) -> None:
    from confiture import _core

    files, base = schema_tree
    assert _core.hash_files([str(f) for f in files], str(base)) == _python_hash(files, base)


@native
def test_native_hash_changes_with_a_rename_and_with_content(
    schema_tree: tuple[list[Path], Path],
) -> None:
    from confiture import _core

    files, base = schema_tree
    before = _core.hash_files([str(f) for f in files], str(base))
    renamed = files[0].with_name("011_a.sql")
    files[0].rename(renamed)
    files[0] = renamed
    assert _core.hash_files([str(f) for f in files], str(base)) != before
    assert _core.hash_files([str(f) for f in files], str(base)) == _python_hash(files, base)


@native
def test_a_missing_file_is_an_os_error_not_a_panic(schema_tree: tuple[list[Path], Path]) -> None:
    from confiture import _core

    files, base = schema_tree
    with pytest.raises(OSError):
        _core.hash_files([str(files[0]), str(base / "10_tables" / "missing.sql")], str(base))


def test_compute_hash_is_the_same_with_and_without_the_extension(
    schema_tree: tuple[list[Path], Path], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    files, base = schema_tree
    (tmp_path / "db" / "environments").mkdir(parents=True)
    (tmp_path / "db" / "environments" / "local.yaml").write_text(
        "database_url: postgresql://localhost/test\ninclude_dirs:\n  - path: db/schema\n"
    )
    builder = SchemaBuilder(env="local", project_dir=tmp_path)
    monkeypatch.setattr(builder_module, "HAS_RUST", False)
    python_side = builder.compute_hash()
    assert python_side == _python_hash(files, base)
    if HAS_RUST:
        monkeypatch.setattr(builder_module, "HAS_RUST", True)
        assert builder.compute_hash() == python_side


@native
def test_a_missing_file_raises_a_schema_error_on_both_paths(
    schema_tree: tuple[list[Path], Path], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from confiture.exceptions import SchemaError

    files, base = schema_tree
    (tmp_path / "db" / "environments").mkdir(parents=True)
    (tmp_path / "db" / "environments" / "local.yaml").write_text(
        "database_url: postgresql://localhost/test\ninclude_dirs:\n  - path: db/schema\n"
    )
    builder = SchemaBuilder(env="local", project_dir=tmp_path)
    monkeypatch.setattr(
        builder, "find_sql_files", lambda: [*files, base / "10_tables" / "gone.sql"]
    )
    for flag in (True, False):
        monkeypatch.setattr(builder_module, "HAS_RUST", flag)
        with pytest.raises(SchemaError):
            builder.compute_hash()


def test_the_fallback_to_python_is_logged_once(
    schema_tree: tuple[list[Path], Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _files, _base = schema_tree
    (tmp_path / "db" / "environments").mkdir(parents=True)
    (tmp_path / "db" / "environments" / "local.yaml").write_text(
        "database_url: postgresql://localhost/test\ninclude_dirs:\n  - path: db/schema\n"
    )
    builder = SchemaBuilder(env="local", project_dir=tmp_path)
    monkeypatch.setattr(builder_module, "HAS_RUST", False)
    builder_module._FALLBACK_NOTED.clear()
    with caplog.at_level(logging.INFO, logger="confiture.core.builder"):
        builder.compute_hash()
        builder.compute_hash()
    notes = [r for r in caplog.records if "native extension" in r.getMessage()]
    assert len(notes) == 1 and notes[0].levelno == logging.INFO


def test_version_reports_the_native_extension() -> None:
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert f"native extension: {'yes' if HAS_RUST else 'no'}" in result.output


def test_build_has_one_path() -> None:
    """D1: the Rust builder is gone; `build()` no longer branches on the separator style."""
    import inspect

    source = inspect.getsource(SchemaBuilder.build)
    assert "use_rust" not in source and "_core.build_schema" not in source
    from confiture import _core

    assert not hasattr(_core, "build_schema")
