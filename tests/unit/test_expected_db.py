"""Unit tests for ExpectedSchemaDB lifecycle (no database required).

Covers the mode guard and — most importantly — that a failure *during* the
build still drops the scratch database, so no orphan ``confiture_tmp_*`` DB is
left behind.
"""

from __future__ import annotations

import pytest

from confiture.core.expected_db import ExpectedSchemaDB
from confiture.exceptions import ConfigurationError, SchemaError


class _FakeTempDatabase:
    """Stand-in for TempDatabase that records whether __exit__ (drop) ran."""

    instances: list[_FakeTempDatabase] = []

    def __init__(self, server_url: str) -> None:
        self.server_url = server_url
        self.exited = False
        self.apply_calls: list[str] = []
        self._raise_on_apply = False
        _FakeTempDatabase.instances.append(self)

    def __enter__(self) -> str:
        return "postgresql://localhost/confiture_tmp_fake"

    def __exit__(self, *_exc: object) -> None:
        self.exited = True

    def apply_schema(self, _url: str, sql: str) -> None:
        self.apply_calls.append(sql)
        if self._raise_on_apply:
            raise SchemaError("boom: schema application failed")


@pytest.fixture(autouse=True)
def _reset_instances() -> None:
    _FakeTempDatabase.instances.clear()


def test_enter_without_mode_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("confiture.core.expected_db.TempDatabase", _FakeTempDatabase)
    edb = ExpectedSchemaDB("postgresql://localhost/x")
    with pytest.raises(ConfigurationError, match="build mode"):
        edb.__enter__()


def test_cleanup_runs_when_build_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """apply_schema raising mid-build must still drop the scratch DB."""

    def _factory(server_url: str) -> _FakeTempDatabase:
        td = _FakeTempDatabase(server_url)
        td._raise_on_apply = True
        return td

    monkeypatch.setattr("confiture.core.expected_db.TempDatabase", _factory)

    edb = ExpectedSchemaDB("postgresql://localhost/x").from_source(
        schema_sql="CREATE TABLE t (id int);"
    )
    with pytest.raises(SchemaError, match="boom"):
        edb.__enter__()

    assert len(_FakeTempDatabase.instances) == 1
    assert _FakeTempDatabase.instances[0].exited is True  # dropped despite the failure


def test_from_source_requires_env_or_schema_sql(monkeypatch: pytest.MonkeyPatch) -> None:
    """from_source() with neither env nor schema_sql fails before touching a DB."""
    monkeypatch.setattr("confiture.core.expected_db.TempDatabase", _FakeTempDatabase)
    edb = ExpectedSchemaDB("postgresql://localhost/x").from_source()
    with pytest.raises(ConfigurationError, match="env or explicit schema_sql"):
        edb.__enter__()
    # The scratch DB was created for the attempt, then dropped on the failure.
    assert _FakeTempDatabase.instances[0].exited is True


def test_from_source_and_from_base_return_self() -> None:
    edb = ExpectedSchemaDB("postgresql://localhost/x")
    assert edb.from_source(schema_sql="") is edb
    assert edb.from_base_plus_migrations() is edb
