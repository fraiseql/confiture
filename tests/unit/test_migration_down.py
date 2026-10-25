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
