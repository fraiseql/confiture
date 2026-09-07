"""The checked-in artifact → migration pair is the contract with FraiseQL (issue #196).

``tests/fixtures/desired_state/emit_ddl/`` is what ``fraiseql compile --emit-ddl``
wrote for ``types.json``; ``expected_migration.up.sql`` / ``.down.sql`` is the migration confiture
generates from an empty current schema with version ``20260101000000``. Changing
either side is a contract change and needs a CHANGELOG line.
"""

from __future__ import annotations

from pathlib import Path

from confiture.core.desired_state import load_desired_state
from confiture.core.differ import SchemaDiffer
from confiture.core.migration_generator import MigrationGenerator

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "desired_state"


def test_artifact_generates_the_checked_in_migration(tmp_path: Path) -> None:
    diff = SchemaDiffer().compare("", load_desired_state(str(FIXTURES / "emit_ddl")).read())
    generated = MigrationGenerator(migrations_dir=tmp_path).generate_sql(
        diff, name="init_from_spec", version="20260101000000"
    )

    assert generated.read_text() == (FIXTURES / "expected_migration.up.sql").read_text()
    down = generated.with_name(generated.name.replace(".up.sql", ".down.sql"))
    assert down.read_text() == (FIXTURES / "expected_migration.down.sql").read_text()
