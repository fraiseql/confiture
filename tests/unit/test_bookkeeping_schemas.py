"""The view-helper schema is part of confiture's bookkeeping (#827).

``migration.view_helpers: auto`` (the default) installs ``sql/view_helpers.sql`` on
the first ``migrate up``; what it creates is confiture's, never the project's.
"""

from importlib import resources

from confiture.cli.commands.admin import _install_view_helpers
from confiture.core.ledger import VIEW_HELPER_SCHEMA, bookkeeping_schemas
from confiture.core.sql_lexer import parse_file


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
