"""Same artifact, same migration — every time (issue #196, "deterministic").

Two runs from the same current state and the same desired-state artifact must
write byte-identical migration files: the version is injected (the caller's
clock, not the wall clock), the body carries no timestamp, and the differ's
change order does not depend on the interpreter's hash seed.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from confiture.core.desired_state import load_desired_state
from confiture.core.differ import SchemaDiffer
from confiture.core.migration_generator import MigrationGenerator

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "desired_state" / "emit_ddl"
VERSION = "20260101000000"


def _generate(into: Path, current_sql: str) -> Path:
    diff = SchemaDiffer().compare(current_sql, load_desired_state(str(FIXTURE)).read())
    into.mkdir(parents=True, exist_ok=True)
    return MigrationGenerator(migrations_dir=into).generate(
        diff, name="sync_from_spec", version=VERSION
    )


def test_two_runs_write_byte_identical_files(tmp_path: Path) -> None:
    current = (FIXTURE / "user.sql").read_text()

    first = _generate(tmp_path / "one", current)
    second = _generate(tmp_path / "two", current)

    assert first.name == f"{VERSION}_sync_from_spec.py" == second.name
    assert first.read_bytes() == second.read_bytes()


def test_the_body_carries_no_wall_clock(tmp_path: Path) -> None:
    generated = _generate(tmp_path, "")

    body = generated.read_text()
    assert "Generated:" not in body
    assert f'version = "{VERSION}"' in body


def test_change_order_does_not_depend_on_the_hash_seed() -> None:
    """The differ walks table-name sets; across interpreters with different seeds the order must not move."""
    code = (
        "import sys\n"
        "from confiture.core.desired_state import load_desired_state\n"
        "from confiture.core.differ import SchemaDiffer\n"
        f"diff = SchemaDiffer().compare('', load_desired_state({str(FIXTURE)!r}).read())\n"
        "print('|'.join(f'{c.type}:{c.table}' for c in diff.changes))\n"
    )
    orders = set()
    for seed in ("0", "1", "2", "3", "4", "5"):
        out = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=True,
            env={"PYTHONHASHSEED": seed, "PATH": ""},
        )
        orders.add(out.stdout.strip())
    assert len(orders) == 1, orders
    assert next(iter(orders)) == "ADD_TABLE:tb_post|ADD_TABLE:tb_user"
