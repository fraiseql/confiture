"""One reader of a config's ``migration:`` block: ``config.environment.migration_block``.

Each command used to read the block its own way: ``migrate up`` only for a file under
``db/environments/``, its tracking table from a raw dict, ``migrate steps`` and
``migrate diff`` through their own ``MigrationConfig.model_validate``, the grant-sweep
checks with ``.get("migration", {})``. One ``migrate up`` honoured ``tracking_table``
from a flat config and ignored ``view_helpers`` from the same block (#832), and a
malformed block was validated by some readers and not others. This test fails on a
module that reads the block again: a ``.get("migration", …)`` or a ``MigrationConfig``
built or validated outside the module that owns it. The allow-list is empty.
"""

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PACKAGE = REPO / "python" / "confiture"
OWNER = "python/confiture/config/environment.py"
_BUILDERS = frozenset({"model_validate", "model_validate_json", "model_construct"})


def _readers(path: Path) -> list[int]:
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        reads_block = (
            isinstance(func, ast.Attribute)
            and func.attr == "get"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "migration"
        )
        builds_model = (isinstance(func, ast.Name) and func.id == "MigrationConfig") or (
            isinstance(func, ast.Attribute)
            and func.attr in _BUILDERS
            and isinstance(func.value, ast.Name)
            and func.value.id == "MigrationConfig"
        )
        if reads_block or builds_model:
            found.append(node.lineno)
    return sorted(found)


def test_no_module_reads_the_migration_block_itself() -> None:
    found = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        module = path.relative_to(REPO).as_posix()
        if module != OWNER and (lines := _readers(path)):
            found[module] = lines
    assert found == {}, f"read the block through config.environment.migration_block: {found}"


def test_the_guard_sees_each_shape(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        "a = data.get('migration') or {}\n"
        "b = MigrationConfig.model_validate(a)\n"
        "c = MigrationConfig()\n"
        "d = record['migration']\n"
    )
    assert _readers(sample) == [1, 2, 3]
