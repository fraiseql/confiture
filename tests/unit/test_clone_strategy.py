"""``clone(strategy=…)``: ask PostgreSQL for ``STRATEGY file_copy`` (#438).

``CREATE DATABASE … WITH TEMPLATE`` defaults to ``WAL_LOG`` on PostgreSQL 15+,
which writes the whole template through WAL: measured on a 1.4 GB template,
35 s per clone with ``fsync=on`` against 1.7 s with ``file_copy``. The strategy is
explicit — ``file_copy`` forces two checkpoints and is not crash-safe, fine for a
disposable test clone and wrong as a silent default — validated, and refused on a
server that has no ``STRATEGY`` clause.
"""

from __future__ import annotations

import pglast
import pytest
from typer.testing import CliRunner

from confiture.core.test_db import TestDbProvisioner, _clone_sql
from confiture.exceptions import ConfigurationError
from confiture.testing.worker_db import resolve_clone_strategy


def _options(sql: str) -> dict[str, str]:
    (raw,) = pglast.parse_sql(sql)
    return {o.defname: getattr(o.arg, "sval", None) for o in raw.stmt.options or ()}


class _Conn:
    """A maintenance connection that answers the version probe and records statements."""

    def __init__(self, version_num: int, fail_on: str | None = None) -> None:
        self.version_num = version_num
        self.fail_on = fail_on
        self.statements: list[str] = []

    def __enter__(self) -> _Conn:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def execute(self, query: object, params: object = None, **_: object) -> _Conn:
        text = query.as_string(None) if hasattr(query, "as_string") else str(query)
        self.statements.append(text)
        if self.fail_on and text.startswith("CREATE DATABASE") and self.fail_on in text:
            import psycopg

            raise psycopg.errors.InvalidParameterValue("tablespace gone")
        self._row = (str(self.version_num),) if "server_version_num" in text else (1,)
        return self

    def fetchone(self) -> tuple[object, ...]:
        return self._row


def _provisioner(monkeypatch: pytest.MonkeyPatch, conn: _Conn) -> TestDbProvisioner:
    prov = TestDbProvisioner("postgresql://localhost/x")
    monkeypatch.setattr(prov, "_maintenance_conn", lambda: conn)
    monkeypatch.setattr(prov, "_require_template_exists", lambda template: None)
    return prov


def test_file_copy_is_written_as_the_strategy_option() -> None:
    sql = _clone_sql("t_gw0", "tmpl", strategy="file_copy").as_string(None)

    assert _options(sql) == {"template": "tmpl", "strategy": "file_copy"}


def test_no_strategy_writes_no_strategy_option() -> None:
    assert "strategy" not in _options(_clone_sql("t_gw0", "tmpl").as_string(None))


def test_an_unknown_strategy_is_refused_before_anything_runs(monkeypatch) -> None:
    conn = _Conn(180000)
    prov = _provisioner(monkeypatch, conn)

    with pytest.raises(ConfigurationError, match="strategy"):
        prov.clone("tmpl", "t_gw0", strategy="fast")  # type: ignore[arg-type]
    assert conn.statements == []


def test_a_server_without_the_clause_refuses_a_strategy_and_names_its_version(monkeypatch) -> None:
    conn = _Conn(140012)
    prov = _provisioner(monkeypatch, conn)

    with pytest.raises(ConfigurationError, match="15"):
        prov.clone("tmpl", "t_gw0", strategy="file_copy")
    assert not any(s.startswith("CREATE DATABASE") for s in conn.statements)


def test_the_strategy_rides_the_clone_and_its_result(monkeypatch) -> None:
    conn = _Conn(180000)
    result = _provisioner(monkeypatch, conn).clone("tmpl", "t_gw0", strategy="file_copy")

    (create,) = [s for s in conn.statements if s.startswith("CREATE DATABASE")]
    assert _options(create)["strategy"] == "file_copy"
    assert result.strategy == "file_copy"


def test_the_on_disk_fallback_keeps_the_strategy(monkeypatch) -> None:
    conn = _Conn(180000, fail_on="TABLESPACE")
    result = _provisioner(monkeypatch, conn).clone(
        "tmpl", "t_gw0", tablespace="ram", strategy="file_copy"
    )

    creates = [s for s in conn.statements if s.startswith("CREATE DATABASE")]
    assert [_options(s).get("strategy") for s in creates] == ["file_copy", "file_copy"]
    assert (result.tablespace, result.strategy) == (None, "file_copy")


@pytest.mark.parametrize(
    ("raw", "expected"), [("", None), ("file_copy", "file_copy"), ("WAL_LOG", "wal_log")]
)
def test_the_worker_fixture_reads_the_strategy_from_the_environment(raw, expected) -> None:
    assert resolve_clone_strategy(env={"CONFITURE_TEST_CLONE_STRATEGY": raw}) == expected


def test_a_misspelt_strategy_in_the_environment_is_refused() -> None:
    with pytest.raises(ConfigurationError, match="CONFITURE_TEST_CLONE_STRATEGY"):
        resolve_clone_strategy(env={"CONFITURE_TEST_CLONE_STRATEGY": "filecopy"})


def test_the_cli_clones_with_the_strategy_the_environment_names(monkeypatch) -> None:
    """``test-db clone`` reads the variable the fixture reads: one knob, both paths."""
    from confiture.cli.main import app
    from confiture.core.test_db import CloneResult

    seen: dict[str, object] = {}

    def fake_clone(self, template, target, **kwargs):
        seen.update(kwargs)
        return CloneResult(template, target, "postgresql://localhost/t_gw0")

    monkeypatch.setattr(TestDbProvisioner, "clone", fake_clone)
    monkeypatch.setenv("CONFITURE_TEST_CLONE_STRATEGY", "file_copy")
    result = CliRunner().invoke(
        app,
        [
            "test-db",
            "clone",
            "--template",
            "tmpl",
            "--target",
            "t_gw0",
            "--database-url",
            "postgresql://localhost/x",
        ],
    )

    assert result.exit_code == 0, result.output
    assert seen["strategy"] == "file_copy"
