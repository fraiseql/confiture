"""The view-helper schema is part of confiture's bookkeeping (#827).

``confiture install-helpers`` installs ``sql/view_helpers.sql``, and nothing else does;
what it creates is confiture's, never the project's. It is refused where the schema
would be on the connecting role's ``search_path`` (``CONFIG_017``).
"""

from importlib import resources

import pytest

from confiture.cli.commands.admin import _install_view_helpers
from confiture.core.ledger import VIEW_HELPER_SCHEMA, bookkeeping_schemas
from confiture.core.sql_lexer import parse_file
from confiture.core.view_manager import ViewManager
from confiture.exceptions import ConfigurationError


def _created() -> tuple[set[str], set[str]]:
    """The schemas ``view_helpers.sql`` creates, and the schemas its tables are created in."""
    text = resources.files("confiture.sql").joinpath("view_helpers.sql").read_text()
    schemas: set[str] = set()
    table_schemas: set[str] = set()
    for raw in parse_file(text).statements:
        node = raw.stmt
        kind = type(node).__name__
        if kind == "CreateSchemaStmt":
            schemas.add(node.schemaname)
        elif kind == "CreateStmt":
            table_schemas.add(node.relation.schemaname)
    return schemas, table_schemas


def test_the_helper_schema_is_bookkeeping() -> None:
    assert bookkeeping_schemas() == frozenset({VIEW_HELPER_SCHEMA})


def test_the_installer_creates_only_bookkeeping_schemas() -> None:
    schemas, table_schemas = _created()
    assert schemas == set(bookkeeping_schemas())
    assert table_schemas <= bookkeeping_schemas()


def test_admin_reports_the_same_schema() -> None:
    payload = _install_view_helpers(object(), dry_run=True, force=False)
    assert payload["schema"] == VIEW_HELPER_SCHEMA


class _Cursor:
    def __init__(self, row: tuple[str, str]) -> None:
        self.row = row
        self.executed: list[str] = []

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, sql: str) -> None:
        self.executed.append(sql)

    def fetchone(self) -> tuple[str, str]:
        return self.row


class _Connection:
    def __init__(self, role: str, search_path: str) -> None:
        self.cur = _Cursor((role, search_path))

    def cursor(self) -> _Cursor:
        return self.cur

    def commit(self) -> None:
        return None


@pytest.mark.parametrize(
    ("role", "search_path"),
    [
        ("confiture", '"$user", public'),
        ("app", "public, confiture"),
        ("app", 'public, "confiture"'),
    ],
    ids=["role-named-confiture", "schema-written", "schema-quoted"],
)
def test_the_helpers_are_refused_where_their_schema_is_on_the_search_path(
    role: str, search_path: str
) -> None:
    conn = _Connection(role, search_path)
    with pytest.raises(ConfigurationError) as info:
        ViewManager(conn).install_helpers()  # type: ignore[arg-type]
    assert info.value.error_code == "CONFIG_017"
    assert len(conn.cur.executed) == 1  # nothing was installed


@pytest.mark.parametrize(
    ("role", "search_path"),
    [("app", '"$user", public'), ("confiture", "public")],
    ids=["other-role", "pinned-search-path"],
)
def test_the_helpers_install_where_their_schema_is_off_the_search_path(
    role: str, search_path: str
) -> None:
    conn = _Connection(role, search_path)
    ViewManager(conn).install_helpers()  # type: ignore[arg-type]
    assert "CREATE SCHEMA IF NOT EXISTS confiture" in conn.cur.executed[-1]
