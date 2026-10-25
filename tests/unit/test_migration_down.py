"""Whether a Python migration's ``down()`` does anything, read from its source (#754)."""

import ast
from pathlib import Path
from textwrap import dedent

import pytest

from confiture.core import migration_down
from confiture.core.migration_down import DownBody, read_down

_HEAD = "from confiture.models.migration import Migration\n\n\n"


def _class(down: str, *, base: str = "Migration") -> str:
    return (
        _HEAD
        + dedent(
            f"""
        class AddU({base}):
            version = "002"
            name = "add_u"

            def up(self):
                self.execute("ALTER TABLE t ADD COLUMN u int")
        """
        )
        + ("    " + down.replace("\n", "\n    ")).rstrip()
        + "\n"
    )


@pytest.mark.parametrize(
    "down",
    [
        "def down(self):\n    pass",
        "def down(self):\n    ...",
        'def down(self):\n    """Nothing to undo."""',
        'def down(self):\n    """Nothing to undo."""\n    pass',
        "def down(self):\n    return",
        "def down(self):\n    raise NotImplementedError",
        'def down(self):\n    raise NotImplementedError("irreversible")',
        "def down(self) -> None:\n    pass",
        "",  # no down(): the abstract one, which raises
    ],
    ids=[
        "pass",
        "ellipsis",
        "docstring",
        "docstring-pass",
        "bare-return",
        "raise",
        "raise-call",
        "annotated",
        "absent",
    ],
)
def test_a_down_that_does_nothing_is_empty(down: str) -> None:
    assert read_down(_class(down)) is DownBody.EMPTY


@pytest.mark.parametrize(
    "down",
    [
        'def down(self):\n    self.execute("ALTER TABLE t DROP COLUMN u")',
        'def down(self):\n    """Drop it."""\n    self.execute("ALTER TABLE t DROP COLUMN u")',
        "def down(self):\n    if True:\n        pass",
        "def down(self):\n    raise RuntimeError('no')",
    ],
    ids=["execute", "docstring-execute", "branch", "other-raise"],
)
def test_a_down_with_a_statement_is_present(down: str) -> None:
    assert read_down(_class(down)) is DownBody.PRESENT


@pytest.mark.parametrize(
    "source",
    [
        _class("def down(self):\n    pass", base="SQLMigration"),
        _class("def down(self):\n    pass", base="ProjectBase"),
        _class("@staticmethod\ndef down():\n    pass"),
        _class("down = None"),
        _class("def down(self):\n    pass") + "\n\nclass Other(Migration):\n    pass\n",
        _class("def down(self):\n    pass") + "\n\nclass Child(AddU):\n    pass\n",
        "def broken(:\n",
        "x = 1\n",
    ],
    ids=[
        "sql-migration",
        "project-base",
        "decorated",
        "assigned",
        "two-classes",
        "local-subclass",
        "syntax-error",
        "no-class",
    ],
)
def test_a_down_confiture_cannot_place_is_unknown(source: str) -> None:
    assert read_down(source) is DownBody.UNKNOWN


def test_a_mixin_may_supply_an_absent_down() -> None:
    assert read_down(_class("", base="Migration, UndoMixin")) is DownBody.UNKNOWN
    assert read_down(_class("def down(self):\n    pass", base="Migration, Mixin")) is DownBody.EMPTY


def test_a_qualified_base_is_read() -> None:
    source = "import confiture.models.migration as m\n\n\n" + _class(
        "def down(self):\n    pass", base="m.Migration"
    ).removeprefix(_HEAD)
    assert read_down(source) is DownBody.EMPTY


def test_the_last_down_defined_is_the_one_that_runs() -> None:
    down = "def down(self):\n    self.execute('SELECT 1')\n\ndef down(self):\n    pass"
    assert read_down(_class(down)) is DownBody.EMPTY


def test_the_reader_never_imports_or_executes() -> None:
    tree = ast.parse(Path(migration_down.__file__).read_text(encoding="utf-8"))
    calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not calls & {"eval", "exec", "compile", "__import__"}
    assert not imported & {"importlib", "runpy", "subprocess"}


def test_a_usable_down_is_a_down_sql_or_a_python_down_that_is_not_empty(tmp_path: Path) -> None:
    from confiture.core.migration_down import has_usable_down

    (tmp_path / "001_a.up.sql").write_text("CREATE TABLE a (id int);")
    (tmp_path / "001_a.down.sql").write_text("DROP TABLE a;")
    (tmp_path / "002_b.up.sql").write_text("CREATE TABLE b (id int);")
    (tmp_path / "003_c.py").write_text(_class("def down(self):\n    pass"))
    (tmp_path / "004_d.py").write_text(_class("def down(self):\n    self.execute('SELECT 1')"))
    (tmp_path / "005_e.py").write_text("from base import Base\n\n\nclass E(Base):\n    pass\n")

    assert {
        p.name: has_usable_down(p)
        for p in sorted(tmp_path.glob("*[!n].*"))
        if ".down." not in p.name
    } == {
        "001_a.up.sql": True,
        "002_b.up.sql": False,
        "003_c.py": False,
        "004_d.py": True,
        "005_e.py": True,  # unknown is never refused
    }


def test_preflight_reversibility_is_the_usable_down(tmp_path: Path) -> None:
    from confiture.core.migration_down import has_usable_down
    from confiture.core.preflight import run_preflight

    (tmp_path / "001_a.up.sql").write_text("CREATE TABLE a (id int);")
    (tmp_path / "003_c.py").write_text(_class("def down(self):\n    pass"))
    (tmp_path / "004_d.py").write_text(_class("def down(self):\n    self.execute('SELECT 1')"))
    result = run_preflight(tmp_path)

    files = {"001": "001_a.up.sql", "003": "003_c.py", "004": "004_d.py"}
    assert {m.version: m.reversible for m in result.migrations} == {
        v: has_usable_down(tmp_path / f) for v, f in files.items()
    }
    assert [m.version for m in result.irreversible] == ["001", "003"]
    assert [i.migration for i in result.issues if i.code == "PFLIGHT_MISSING_DOWN"] == ["001"]


def test_a_file_that_is_not_utf8_is_unknown(tmp_path: Path) -> None:
    from confiture.core.migration_down import read_python_down

    path = tmp_path / "002_bad.py"
    path.write_bytes(b'x = "\xff"\n')
    assert read_python_down(path) is DownBody.UNKNOWN
