"""Every file a migration reads, and the path each read names (#540, #538).

``ModuleModel.file_reads()`` answers a different question from ``evaluate``: not
"what SQL does this call hand over" but "which files can this read open". So a
loop over a static tuple fans out, one path per item, here and only here;
``evaluate`` still refuses a loop variable.
"""

from __future__ import annotations

from pathlib import Path

from confiture.core.idempotency.static_eval import ModuleModel, PathV, Refusal, Str, Unknown

HEADER = "from pathlib import Path\nfrom confiture.models.migration import Migration\n"
SCHEMA_DIR = 'SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schema"'


def _model(tmp_path: Path, module_level: str, up_body: str) -> ModuleModel:
    root = tmp_path / "project"
    (root / "db" / "migrations").mkdir(parents=True)
    (root / "pyproject.toml").write_text("")
    body = "\n".join("        " + line for line in up_body.splitlines())
    text = (
        f"{HEADER}\n{module_level}\n\n"
        "class M(Migration):\n"
        '    version = "20260101000000"\n'
        '    name = "m"\n'
        "    def up(self) -> None:\n"
        f"{body}\n"
        "    def down(self) -> None:\n"
        "        pass\n"
    )
    path = root / "db" / "migrations" / "20260101000000_m.py"
    path.write_text(text)
    return ModuleModel(text, path=path, project_root=root)


def _paths(model: ModuleModel) -> list[list[str]]:
    """Each read site's paths, relative to the project, in source order."""
    root = model.project_root
    found = []
    for site in model.file_reads():
        paths = []
        for value in site.values:
            assert isinstance(value, (PathV, Str)), value
            raw = value.path if isinstance(value, PathV) else Path(value.text)
            absolute = raw if raw.is_absolute() else root / raw
            paths.append(absolute.resolve().relative_to(root.resolve()).as_posix())
        found.append(paths)
    return found


def test_sql_embedded_as_constants_reads_nothing(tmp_path: Path) -> None:
    model = _model(tmp_path, 'DDL = "CREATE TABLE t (id int)"', "self.execute(DDL)")

    assert list(model.file_reads()) == []


def test_a_read_text_names_its_file(tmp_path: Path) -> None:
    model = _model(
        tmp_path,
        "",
        'self.execute((Path(__file__).parent.parent / "schema" / "a.sql").read_text())',
    )

    assert _paths(model) == [["db/schema/a.sql"]]


def test_a_directory_constant_joined_with_a_filename_constant(tmp_path: Path) -> None:
    model = _model(
        tmp_path,
        f'{SCHEMA_DIR}\nFUNCTION_FILE = "functions/billing/0219_attach.sql"',
        "self.execute((SCHEMA_DIR / FUNCTION_FILE).read_text())",
    )

    assert _paths(model) == [["db/schema/functions/billing/0219_attach.sql"]]


def test_a_loop_over_a_module_tuple_reads_each_file(tmp_path: Path) -> None:
    model = _model(
        tmp_path,
        f'{SCHEMA_DIR}\nFILES = ("a.sql", "b/c.sql")',
        "for name in FILES:\n    self.execute((SCHEMA_DIR / name).read_text())",
    )

    assert _paths(model) == [["db/schema/a.sql", "db/schema/b/c.sql"]]


def test_nested_loops_read_every_combination(tmp_path: Path) -> None:
    model = _model(
        tmp_path,
        f'{SCHEMA_DIR}\nDIRS = ("x", "y")\nFILES = ("a.sql", "b.sql")',
        "for d in DIRS:\n    for f in FILES:\n        (SCHEMA_DIR / d / f).read_text()",
    )

    assert _paths(model) == [
        ["db/schema/x/a.sql", "db/schema/x/b.sql", "db/schema/y/a.sql", "db/schema/y/b.sql"]
    ]


def test_every_way_of_reading_is_a_site(tmp_path: Path) -> None:
    model = _model(
        tmp_path,
        SCHEMA_DIR,
        "\n".join(
            (
                '(SCHEMA_DIR / "a.sql").read_bytes()',
                'open(SCHEMA_DIR / "b.sql").read()',
                'with (SCHEMA_DIR / "c.sql").open() as f:\n    f.read()',
                'self.execute_file("db/schema/d.sql")',
                'self.execute_file(path=SCHEMA_DIR / "e.sql")',
            )
        ),
    )

    assert _paths(model) == [
        ["db/schema/a.sql"],
        ["db/schema/b.sql"],
        ["db/schema/c.sql"],
        ["db/schema/d.sql"],
        ["db/schema/e.sql"],
    ]


def test_a_read_at_module_level_is_a_site(tmp_path: Path) -> None:
    model = _model(tmp_path, f'{SCHEMA_DIR}\nDDL = (SCHEMA_DIR / "a.sql").read_text()', "pass")

    assert _paths(model) == [["db/schema/a.sql"]]


def test_a_loop_over_what_the_file_cannot_fix_is_refused(tmp_path: Path) -> None:
    model = _model(
        tmp_path,
        SCHEMA_DIR,
        "for name in self.names():\n    (SCHEMA_DIR / name).read_text()",
    )

    (site,) = model.file_reads()
    (value,) = site.values
    assert isinstance(value, Unknown)
    assert value.code is Refusal.OTHER_BINDING


def test_a_loop_variable_rebound_in_the_body_is_not_fanned_out(tmp_path: Path) -> None:
    model = _model(
        tmp_path,
        f'{SCHEMA_DIR}\nFILES = ("a.sql",)',
        'for name in FILES:\n    name = name + ".bak"\n    (SCHEMA_DIR / name).read_text()',
    )

    (site,) = model.file_reads()
    (value,) = site.values
    assert isinstance(value, Unknown)
    assert value.code is Refusal.MULTIPLE_BINDINGS


def test_each_site_carries_its_line(tmp_path: Path) -> None:
    model = _model(tmp_path, SCHEMA_DIR, '(SCHEMA_DIR / "a.sql").read_text()')

    (site,) = model.file_reads()
    lines = model.path.read_text().splitlines()
    assert "read_text" in lines[site.line - 1]


def test_evaluate_still_refuses_a_loop_variable(tmp_path: Path) -> None:
    """The SQL extractor's grammar is unchanged: the fan-out lives in ``file_reads``."""
    model = _model(
        tmp_path,
        f'{SCHEMA_DIR}\nFILES = ("a.sql",)',
        'for name in FILES:\n    self.execute(f"SELECT {name}")',
    )

    ((call, scope),) = model.execute_calls()
    value, _trace = model.evaluate(call.args[0], scope)
    assert isinstance(value, Unknown)
