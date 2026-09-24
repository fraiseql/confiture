"""Levels 4 and 5 call a resolver by the identity PostgreSQL gave it (#375).

Both levels wrote ``f"SELECT {func_name}();"`` from a file stem and a savepoint
name straight into SQL. A resolver's name is now the parsed one: pglast has
already folded an unquoted name and kept a quoted one's case, which is
PostgreSQL's own identity, so quoting it every time calls the routine the DDL
created — and no parameter is passed, so a ``%`` in a name is not a placeholder.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from psycopg import sql

from confiture.core.schema_sources import read_schema
from confiture.core.seed.validation.prep_seed.level_4_runtime import Level4RuntimeValidator
from confiture.core.seed.validation.prep_seed.level_5_execution import Level5ExecutionValidator
from confiture.core.seed.validation.prep_seed.resolvers import Resolver, find_resolvers


class _Recorder:
    """A connection that keeps the text of everything it is asked to run."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, query: Any, params: Any = None) -> None:
        assert params is None, "a resolver call passes no parameters"
        self.statements.append(query.as_string() if isinstance(query, sql.Composable) else query)


def _resolver(tmp_path: Path, create: str) -> Resolver:
    (tmp_path / "fn.sql").write_text(create)
    (found,) = find_resolvers(read_schema(tmp_path), catalog_schema="catalog")
    return found


@pytest.mark.parametrize(
    ("create", "call"),
    [
        pytest.param(
            'CREATE FUNCTION "Fn_resolve_X"() RETURNS void LANGUAGE sql AS $$ $$;',
            'SELECT "Fn_resolve_X"()',
            id="quoted-mixed-case",
        ),
        pytest.param(
            "CREATE FUNCTION Fn_Resolve_X() RETURNS void LANGUAGE sql AS $$ $$;",
            'SELECT "fn_resolve_x"()',
            id="unquoted-folds",
        ),
        pytest.param(
            "CREATE FUNCTION app.fn_resolve_x() RETURNS void LANGUAGE sql AS $$ $$;",
            'SELECT "app"."fn_resolve_x"()',
            id="schema-qualified",
        ),
        pytest.param(
            'CREATE FUNCTION "fn_resolve_%x"() RETURNS void LANGUAGE sql AS $$ $$;',
            'SELECT "fn_resolve_%x"()',
            id="percent",
        ),
    ],
)
def test_both_levels_call_the_resolver_the_ddl_created(
    tmp_path: Path, create: str, call: str
) -> None:
    resolver = _resolver(tmp_path, create)
    level_4, level_5 = _Recorder(), _Recorder()

    assert Level4RuntimeValidator().dry_run_resolution(resolver, level_4) == []
    assert Level5ExecutionValidator().execute_resolutions(level_5, [resolver]) == []

    assert call in level_4.statements
    assert level_5.statements == [call]


def test_the_savepoint_is_an_identifier(tmp_path: Path) -> None:
    resolver = _resolver(
        tmp_path, "CREATE FUNCTION fn_resolve_x() RETURNS void AS 'x' LANGUAGE sql;"
    )
    recorder = _Recorder()
    Level4RuntimeValidator().dry_run_resolution(resolver, recorder, savepoint_name="Sp 1")
    assert recorder.statements[0] == 'SAVEPOINT "Sp 1"'
    assert recorder.statements[-1] == 'ROLLBACK TO SAVEPOINT "Sp 1"'


def test_a_failed_call_names_the_resolver_file(tmp_path: Path) -> None:
    resolver = _resolver(
        tmp_path, "CREATE FUNCTION fn_resolve_x() RETURNS void AS 'x' LANGUAGE sql;"
    )

    class _Refusing(_Recorder):
        def execute(self, query: Any, params: Any = None) -> None:
            super().execute(query, params)
            if "fn_resolve_x" in self.statements[-1]:
                raise RuntimeError("boom")

    (violation,) = Level5ExecutionValidator().execute_resolutions(_Refusing(), [resolver])
    assert (Path(violation.file_path).name, violation.line_number) == ("fn.sql", 1)
