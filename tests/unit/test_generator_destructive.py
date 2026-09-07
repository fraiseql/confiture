"""A generated migration says how dangerous each statement is, in the words the change set uses.

The desired state may remove a table or a column, or narrow a type. The
generator writes that DDL for real, and the file carries the risk tier of every
statement as a ``-- confiture:tier <tier>`` directive — the tier
``migrate preflight``'s change-set classifier assigns, so the two never disagree.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from confiture.core import sql_lexer
from confiture.core.change_set import classify_statements
from confiture.core.migration_generator import MigrationGenerator
from confiture.core.risk_tier import worst_tier
from confiture.models.schema import SchemaChange, SchemaDiff

VERSION = "20260101000000"


def _generate(tmp_path: Path, *changes: SchemaChange) -> tuple[str, str]:
    up = MigrationGenerator(migrations_dir=tmp_path).generate_sql(
        SchemaDiff(changes=list(changes)), name="reshape", version=VERSION
    )
    down = up.with_name(up.name.replace(".up.sql", ".down.sql"))
    return up.read_text(), down.read_text()


def _tiers(text: str) -> dict[int, str | None]:
    """The tier directive attached to each statement, keyed by the statement's line."""
    return {d.statement_line: d.argument for d in sql_lexer.directives(text) if d.name == "tier"}


def test_a_dropped_column_is_real_ddl_at_tier_irreversible(tmp_path: Path) -> None:
    up, _ = _generate(
        tmp_path, SchemaChange(type="DROP_COLUMN", table="tb_user", column="display_name")
    )
    assert "ALTER TABLE tb_user DROP COLUMN display_name;" in up
    # Data is lost with the column: the change set tiers the drop irreversible, not merely destructive.
    assert list(_tiers(up).values()) == ["irreversible"]


@pytest.mark.parametrize(
    "change",
    [
        SchemaChange(type="DROP_TABLE", table="tb_old"),
        SchemaChange(type="DROP_COLUMN", table="tb_user", column="display_name"),
        SchemaChange(
            type="CHANGE_COLUMN_TYPE",
            table="tb_user",
            column="score",
            old_value="BIGINT",
            new_value="INTEGER",
        ),
        SchemaChange(type="ADD_COLUMN", table="tb_user", column="bio", new_value="TEXT"),
    ],
    ids=lambda c: c.type,
)
def test_every_statement_carries_the_tier_the_change_set_gives_it(
    tmp_path: Path, change: SchemaChange
) -> None:
    up, down = _generate(tmp_path, change)
    for text in (up, down):
        statements = [
            s for s in sql_lexer.split_statements(sql_lexer.code_text(text).text) if s.strip()
        ]
        assert statements, text
        # A statement the classifier cannot tier gets no directive: five tiers, no "unknown".
        classified = [worst_tier(e.tier for e in classify_statements(s)) for s in statements]
        expected = [tier.value for tier in classified if tier is not None]
        assert list(_tiers(text).values()) == expected, text
