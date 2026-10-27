"""What ``migrate validate --idempotent`` says about the migrations confiture generates.

A file that runs in one transaction creates each relation it proves new
plainly, under ``-- confiture:creates``; one that does not keeps ``IF NOT
EXISTS`` and declares nothing. Neither is a ``CREATE_TABLE`` violation, and
every other finding on a diff golden is what it was before plain creates:
``PINNED`` holds the count per pattern, ``CREATE_TABLE`` excluded.
"""

from collections import Counter
from pathlib import Path

import pglast
import pytest

from confiture.core._pglast_enums import member
from confiture.core.created_relations import declared
from confiture.core.idempotency.models import IdempotencyPattern
from confiture.core.idempotency.patterns import detect_non_idempotent_patterns
from confiture.core.migration_analyzer import runs_in_one_transaction

_MATVIEW = member("ObjectType", "OBJECT_MATVIEW")
GOLDENS = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "model_goldens" / "diff"

#: Each golden's idempotency findings, per pattern, ``CREATE_TABLE`` excluded.
PINNED: dict[str, dict[str, int]] = {
    "01-basic-migration.down.sql": {"DROP_TABLE": 1},
    "01-basic-migration.up.sql": {},
    "02-fraiseql-integration.down.sql": {"DROP_TABLE": 6},
    "02-fraiseql-integration.up.sql": {"CREATE_OR_REPLACE_FUNCTION_SHAPE_RISK": 1},
    "03-zero-downtime-migration.down.sql": {"ALTER_TABLE_RENAME_COLUMN": 1},
    "03-zero-downtime-migration.new.down.sql": {"DROP_TABLE": 1},
    "03-zero-downtime-migration.new.up.sql": {"CREATE_OR_REPLACE_FUNCTION_SHAPE_RISK": 1},
    "03-zero-downtime-migration.old.down.sql": {"DROP_TABLE": 1},
    "03-zero-downtime-migration.old.up.sql": {"CREATE_OR_REPLACE_FUNCTION_SHAPE_RISK": 1},
    "03-zero-downtime-migration.up.sql": {"ALTER_TABLE_RENAME_COLUMN": 1},
    "04-production-sync-anonymization.down.sql": {"DROP_TABLE": 9},
    "04-production-sync-anonymization.up.sql": {},
    "05-multi-environment-workflow.down.sql": {"DROP_TABLE": 3},
    "05-multi-environment-workflow.up.sql": {
        "CREATE_OR_REPLACE_FUNCTION_SHAPE_RISK": 3,
        "CREATE_OR_REPLACE_VIEW_SHAPE_RISK": 3,
    },
    "06-prep-seed-validation.down.sql": {"DROP_TABLE": 2},
    "06-prep-seed-validation.up.sql": {"CREATE_OR_REPLACE_FUNCTION_SHAPE_RISK": 1},
    "07-comment-validation.down.sql": {"DROP_TABLE": 2},
    "07-comment-validation.up.sql": {"CREATE_OR_REPLACE_VIEW_SHAPE_RISK": 2},
    "08-generated-seeds.down.sql": {"DROP_TABLE": 4},
    "08-generated-seeds.up.sql": {"CREATE_OR_REPLACE_FUNCTION_SHAPE_RISK": 2, "CREATE_TYPE": 1},
    "09-multi-tenant-schema.down.sql": {"DROP_TABLE": 8},
    "09-multi-tenant-schema.up.sql": {
        "CREATE_OR_REPLACE_FUNCTION_SHAPE_RISK": 1,
        "CREATE_OR_REPLACE_VIEW_SHAPE_RISK": 2,
    },
    "basic.down.sql": {"DROP_TABLE": 3},
    "basic.up.sql": {},
    "db-schema.down.sql": {"DROP_TABLE": 1},
    "db-schema.up.sql": {},
    "every-change.down.sql": {
        "ALTER_TABLE_ADD_COLUMN": 1,
        "ALTER_TABLE_ADD_CONSTRAINT_CHECK": 1,
        "ALTER_TABLE_ADD_CONSTRAINT_UNIQUE": 1,
        "ALTER_TABLE_RENAME_COLUMN": 1,
        "CREATE_OR_REPLACE_VIEW_SHAPE_RISK": 1,
        "CREATE_TYPE": 1,
        "DROP_TABLE": 1,
    },
    "every-change.new.down.sql": {"DROP_TABLE": 7},
    "every-change.new.up.sql": {"CREATE_OR_REPLACE_VIEW_SHAPE_RISK": 3, "CREATE_TYPE": 2},
    "every-change.old.down.sql": {"DROP_TABLE": 7},
    "every-change.old.up.sql": {"CREATE_OR_REPLACE_VIEW_SHAPE_RISK": 3, "CREATE_TYPE": 2},
    "every-change.up.sql": {
        "ALTER_TABLE_ADD_COLUMN": 1,
        "ALTER_TABLE_ADD_CONSTRAINT_UNIQUE": 1,
        "ALTER_TABLE_RENAME_COLUMN": 1,
        "CREATE_OR_REPLACE_VIEW_SHAPE_RISK": 2,
        "CREATE_TYPE": 1,
        "DROP_TABLE": 1,
    },
    "matview-indexes.down.sql": {},
    "matview-indexes.new.down.sql": {"DROP_TABLE": 1},
    "matview-indexes.new.up.sql": {},
    "matview-indexes.old.down.sql": {"DROP_TABLE": 1},
    "matview-indexes.old.up.sql": {},
    "matview-indexes.up.sql": {},
    "tview-indexes.down.sql": {},
    "tview-indexes.new.down.sql": {"DROP_TABLE": 2},
    "tview-indexes.new.up.sql": {},
    "tview-indexes.old.down.sql": {"DROP_TABLE": 2},
    "tview-indexes.old.up.sql": {},
    "tview-indexes.up.sql": {},
}

SQL_GOLDENS = sorted(GOLDENS.glob("*.sql"))


def _up_of(path: Path) -> Path:
    return path.with_name(path.name.replace(".down.sql", ".up.sql"))


def _creates(sql: str) -> list[tuple[tuple[str | None, str], bool]]:
    """``((schema, name), if_not_exists)`` of every table and matview *sql* creates."""
    found = []
    for raw in pglast.parse_sql(sql):
        stmt = raw.stmt
        if type(stmt).__name__ == "CreateStmt":
            found.append(((stmt.relation.schemaname, stmt.relation.relname), stmt.if_not_exists))
        elif type(stmt).__name__ == "CreateTableAsStmt" and stmt.objtype == _MATVIEW:
            rel = stmt.into.rel
            found.append(((rel.schemaname, rel.relname), stmt.if_not_exists))
    return found


def test_every_golden_is_pinned() -> None:
    assert sorted(PINNED) == [path.name for path in SQL_GOLDENS]


@pytest.mark.parametrize("path", SQL_GOLDENS, ids=lambda p: p.name)
def test_a_generated_golden_keeps_its_other_violations(path: Path) -> None:
    found = Counter(m.pattern.value for m in detect_non_idempotent_patterns(path.read_text()))
    assert found.pop(IdempotencyPattern.CREATE_TABLE.value, 0) == 0
    assert dict(found) == PINNED[path.name]


@pytest.mark.parametrize("path", SQL_GOLDENS, ids=lambda p: p.name)
def test_a_golden_creates_plainly_exactly_when_its_up_runs_in_one_transaction(
    path: Path,
) -> None:
    sql = path.read_text()
    plain = runs_in_one_transaction(_up_of(path).read_text())
    creates = _creates(sql)
    assert all(if_not_exists is not plain for _, if_not_exists in creates)
    assert declared(sql) == ({name for name, _ in creates} if plain else set())
