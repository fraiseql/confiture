"""The static evaluator: what ``self.execute(<expr>)`` is worth without running it.

Every test builds a small project, evaluates the argument of the first
``self.execute`` call, and asserts either the value or the refusal *reason*.
The reason matters as much as the refusal: remedies key on it, and a
gate under ``--fail-on-unanalyzable`` shows it to the person who has to fix
the migration.
"""

from __future__ import annotations

import ast
from pathlib import Path

from confiture.core.idempotency.static_eval import (
    ModuleModel,
    PathV,
    Refusal,
    Str,
    Unknown,
)

HEADER = "from pathlib import Path\nfrom confiture.models.migration import Migration\n"


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / "db" / "schema").mkdir(parents=True)
    (root / "db" / "migrations").mkdir(parents=True)
    (root / "pyproject.toml").write_text("")
    (root / "db" / "schema" / "fn.sql").write_text("CREATE TABLE IF NOT EXISTS from_file (id int);")
    return root


def _migration(module_level: str, up_body: str, *, class_body: str = "") -> str:
    body = "\n".join("        " + line for line in up_body.splitlines())
    extra = (
        ("\n".join("    " + line for line in class_body.splitlines()) + "\n") if class_body else ""
    )
    return (
        f"{HEADER}\n{module_level}\n\n"
        "class M(Migration):\n"
        '    version = "20260101000000"\n'
        '    name = "m"\n'
        f"{extra}"
        "    def up(self) -> None:\n"
        f"{body}\n"
        "    def down(self) -> None:\n"
        "        pass\n"
    )


def _evaluate(tmp_path: Path, module_level: str, up_body: str, *, class_body: str = ""):
    """(value, trace) of the first self.execute(...) argument in the built migration."""
    root = _project(tmp_path)
    path = root / "db" / "migrations" / "20260101000000_m.py"
    text = _migration(module_level, up_body, class_body=class_body)
    path.write_text(text)
    model = ModuleModel(text, path=path, project_root=root)
    for call, scope in model.execute_calls():
        if isinstance(call.func, ast.Attribute) and call.func.attr == "execute":
            return model.evaluate(call.args[0], scope)
    raise AssertionError("no self.execute call in fixture")


def _refused(value, code: Refusal, *fragments: str) -> None:
    assert isinstance(value, Unknown), value
    assert value.code is code, (value.code, value.reason)
    for fragment in fragments:
        assert fragment in value.reason, value.reason


# --------------------------------------------------------------------------- #
# Literals — parity with the pre-0.46.0 resolver                                #
# --------------------------------------------------------------------------- #


class TestLiterals:
    def test_string_literal(self, tmp_path):
        value, trace = _evaluate(tmp_path, "", 'self.execute("SELECT 1")')
        assert value == Str("SELECT 1")
        assert trace.names == ()

    def test_static_fstring_is_a_string_that_remembers_it_was_an_fstring(self, tmp_path):
        value, _ = _evaluate(tmp_path, "", 'self.execute(f"SELECT 1")')
        assert value == Str("SELECT 1", is_fstring=True)

    def test_concatenation(self, tmp_path):
        value, _ = _evaluate(tmp_path, "", 'self.execute("SELECT " + "1")')
        assert value == Str("SELECT 1")

    def test_non_string_constant_is_refused(self, tmp_path):
        value, _ = _evaluate(tmp_path, "", "self.execute(42)")
        _refused(value, Refusal.NON_STRING, "int")

    def test_fstring_over_a_loop_variable_is_refused_with_the_name(self, tmp_path):
        value, _ = _evaluate(
            tmp_path, "", 'for t in ("a",):\n    self.execute(f"DROP TABLE IF EXISTS {t}")'
        )
        _refused(value, Refusal.FSTRING_DYNAMIC, "`t`", "for")
        assert value.hint == "fstring"

    def test_fstring_conversion_is_refused(self, tmp_path):
        value, _ = _evaluate(tmp_path, "", 't = "a"\nself.execute(f"DROP TABLE {t!r}")')
        _refused(value, Refusal.FSTRING_FORMAT, "!r")

    def test_percent_format_is_outside_the_grammar(self, tmp_path):
        value, _ = _evaluate(tmp_path, "", 'self.execute("DROP TABLE %s" % "a")')
        _refused(value, Refusal.UNSUPPORTED, "%")


# --------------------------------------------------------------------------- #
# Names — one rule at every scope                                               #
# --------------------------------------------------------------------------- #


class TestNamesThatResolve:
    def test_module_constant(self, tmp_path):
        value, trace = _evaluate(tmp_path, 'DDL = "CREATE TABLE t (id int)"', "self.execute(DDL)")
        assert value == Str("CREATE TABLE t (id int)")
        assert trace.names == ("DDL",)
        assert trace.definition_line == 4

    def test_annotated_module_constant(self, tmp_path):
        value, _ = _evaluate(
            tmp_path, 'from typing import Final\nDDL: Final[str] = "SELECT 1"', "self.execute(DDL)"
        )
        assert value == Str("SELECT 1")

    def test_constant_defined_below_the_class(self, tmp_path):
        root = _project(tmp_path)
        path = root / "db" / "migrations" / "20260101000000_m.py"
        text = _migration("", "self.execute(DDL)") + '\nDDL = "SELECT 1"\n'
        path.write_text(text)
        model = ModuleModel(text, path=path, project_root=root)
        call, scope = next(iter(model.execute_calls()))

        value, _ = model.evaluate(call.args[0], scope)

        assert value == Str("SELECT 1")

    def test_constants_built_from_constants(self, tmp_path):
        value, trace = _evaluate(
            tmp_path, '_A = "SELECT "\n_B = "1"\nDDL = _A + _B', 'self.execute(DDL + "; SELECT 2")'
        )
        assert value == Str("SELECT 1; SELECT 2")
        assert trace.names == ("DDL", "_A", "_B")

    def test_function_local_bound_once(self, tmp_path):
        value, trace = _evaluate(tmp_path, "", 'sql = "SELECT 1"\nself.execute(sql)')
        assert value == Str("SELECT 1")
        assert trace.names == ("sql",)

    def test_class_attribute_through_self(self, tmp_path):
        value, trace = _evaluate(
            tmp_path, "", "self.execute(self._SQL)", class_body='_SQL = "SELECT 1"'
        )
        assert value == Str("SELECT 1")
        assert trace.names == ("_SQL",)

    def test_class_attribute_may_read_a_module_constant(self, tmp_path):
        value, _ = _evaluate(
            tmp_path,
            '_BASE = "SELECT "',
            "self.execute(self._SQL)",
            class_body='_SQL = _BASE + "1"',
        )
        assert value == Str("SELECT 1")

    def test_a_class_attribute_of_the_same_name_does_not_shadow_the_module_constant(self, tmp_path):
        """Class scope is invisible inside methods; Python reads the module name here."""
        value, _ = _evaluate(
            tmp_path, 'DDL = "module"', "self.execute(DDL)", class_body='DDL = "class"'
        )
        assert value == Str("module")

    def test_fstring_over_a_static_local(self, tmp_path):
        value, _ = _evaluate(
            tmp_path, "", 'table = "t"\nself.execute(f"DROP TABLE IF EXISTS {table}")'
        )
        assert value == Str("DROP TABLE IF EXISTS t", is_fstring=True)


class TestNamesThatAreRefused:
    def test_module_name_bound_twice(self, tmp_path):
        value, _ = _evaluate(tmp_path, 'DDL = "a"\nDDL = "b"', "self.execute(DDL)")
        _refused(value, Refusal.MULTIPLE_BINDINGS, "`DDL`", "2 times", "module scope")

    def test_augmented_assignment_is_a_second_binding(self, tmp_path):
        value, _ = _evaluate(tmp_path, 'DDL = "a"\nDDL += "b"', "self.execute(DDL)")
        _refused(value, Refusal.MULTIPLE_BINDINGS, "`DDL`", "2 times")

    def test_global_declared_and_assigned_in_a_method(self, tmp_path):
        text_body = "self.execute(DDL)"
        value, _ = _evaluate(
            tmp_path,
            'DDL = "a"',
            text_body,
            class_body='def reset(self) -> None:\n    global DDL\n    DDL = "b"',
        )
        _refused(value, Refusal.GLOBAL_REBIND, "`DDL`", "global", "reset")

    def test_loop_target_shadowing_a_module_constant(self, tmp_path):
        value, _ = _evaluate(tmp_path, 'DDL = "a"', 'for DDL in ("b",):\n    self.execute(DDL)')
        _refused(value, Refusal.OTHER_BINDING, "`DDL`", "for")

    def test_parameter(self, tmp_path):
        value, _ = _evaluate(
            tmp_path,
            'DDL = "module"',
            'self._apply("x")',
            class_body="def _apply(self, DDL: str) -> None:\n    self.execute(DDL)",
        )
        _refused(value, Refusal.PARAMETER, "`DDL`", "_apply")

    def test_comprehension_target(self, tmp_path):
        value, _ = _evaluate(tmp_path, 'DDL = "a"', '[self.execute(DDL) for DDL in ("b",)]')
        _refused(value, Refusal.OTHER_BINDING, "`DDL`")

    def test_walrus(self, tmp_path):
        value, _ = _evaluate(tmp_path, "", 'if (sql := "a"):\n    self.execute(sql)')
        _refused(value, Refusal.OTHER_BINDING, "`sql`", ":=")

    def test_tuple_unpack(self, tmp_path):
        value, _ = _evaluate(tmp_path, "", 'sql, other = "a", "b"\nself.execute(sql)')
        _refused(value, Refusal.OTHER_BINDING, "`sql`", "unpack")

    def test_import_alias(self, tmp_path):
        value, _ = _evaluate(tmp_path, "from os import sep as DDL", "self.execute(DDL)")
        _refused(value, Refusal.OTHER_BINDING, "`DDL`", "import")

    def test_nested_def_of_the_same_name(self, tmp_path):
        value, _ = _evaluate(tmp_path, 'DDL = "a"', "def DDL():\n    pass\nself.execute(DDL)")
        _refused(value, Refusal.OTHER_BINDING, "`DDL`", "def")

    def test_binding_inside_a_block_is_conditional(self, tmp_path):
        value, _ = _evaluate(tmp_path, 'if True:\n    DDL = "a"', "self.execute(DDL)")
        _refused(value, Refusal.CONDITIONAL_BINDING, "`DDL`", "block")

    def test_unbound_name(self, tmp_path):
        value, _ = _evaluate(tmp_path, "", "self.execute(sql)")
        _refused(value, Refusal.UNBOUND, "`sql`", "not defined")

    def test_self_reference_is_a_cycle(self, tmp_path):
        value, _ = _evaluate(tmp_path, 'DDL = DDL + "x"', "self.execute(DDL)")
        _refused(value, Refusal.CYCLE, "`DDL`")

    def test_mutual_reference_is_a_cycle(self, tmp_path):
        value, _ = _evaluate(tmp_path, "A = B\nB = A", "self.execute(A)")
        _refused(value, Refusal.CYCLE)

    def test_chain_deeper_than_the_cap(self, tmp_path):
        chain = "\n".join(f"N{i} = N{i + 1}" for i in range(12)) + '\nN12 = "x"'
        value, _ = _evaluate(tmp_path, chain, "self.execute(N0)")
        _refused(value, Refusal.DEPTH)

    def test_non_string_module_constant(self, tmp_path):
        value, _ = _evaluate(tmp_path, "TIMEOUT = 30", "self.execute(TIMEOUT)")
        _refused(value, Refusal.NON_STRING, "int")

    def test_class_attribute_assigned_through_self_anywhere(self, tmp_path):
        value, _ = _evaluate(
            tmp_path,
            "",
            "self.execute(self._SQL)",
            class_body='_SQL = "a"\n\ndef reset(self) -> None:\n    self._SQL = "b"',
        )
        _refused(value, Refusal.ATTRIBUTE_STORE, "`self._SQL`", "assigned")

    def test_class_attribute_that_is_not_bound_in_the_class(self, tmp_path):
        value, _ = _evaluate(tmp_path, "", "self.execute(self._SQL)")
        _refused(value, Refusal.NOT_CLASS_ATTRIBUTE, "`self._SQL`")

    def test_subscript_with_a_non_literal_key(self, tmp_path):
        value, _ = _evaluate(
            tmp_path, 'SQL = {"a": "x"}', "for k in SQL:\n    self.execute(SQL[k])"
        )
        _refused(value, Refusal.SUBSCRIPT)

    def test_unsupported_expression_names_its_kind(self, tmp_path):
        value, _ = _evaluate(tmp_path, "", 'self.execute("a" if True else "b")')
        _refused(value, Refusal.UNSUPPORTED, "IfExp")


class TestPathValues:
    """Path arithmetic, before any file is read."""

    def test_dunder_file_is_the_migration_path(self, tmp_path):
        value, _ = _evaluate(tmp_path, "", "self.execute(Path(__file__))")
        assert isinstance(value, PathV)
        assert value.path.name == "20260101000000_m.py"


# --------------------------------------------------------------------------- #
# File reads through the shared, confined resolver                              #
# --------------------------------------------------------------------------- #


class TestFileReads:
    def test_literal_path_read_from_a_foreign_cwd(self, tmp_path, monkeypatch):
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)

        value, _ = _evaluate(tmp_path, "", 'self.execute(Path("db/schema/fn.sql").read_text())')

        assert isinstance(value, Str)
        assert value.text == "CREATE TABLE IF NOT EXISTS from_file (id int);"
        assert value.from_file == (tmp_path / "project" / "db" / "schema" / "fn.sql").resolve()

    def test_module_constant_path_arithmetic(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        value, trace = _evaluate(
            tmp_path,
            '_SCHEMA = Path(__file__).resolve().parent.parent / "schema"',
            'self.execute((_SCHEMA / "fn.sql").read_text())',
        )
        assert isinstance(value, Str)
        assert value.from_file is not None
        assert trace.names == ("_SCHEMA",)

    def test_pathlib_variants(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        value, _ = _evaluate(
            tmp_path,
            "import pathlib\n_ROOT = pathlib.Path(__file__).parents[2]",
            'self.execute(_ROOT.joinpath("db", "schema", "fn.sql").resolve().read_text(encoding="utf-8"))',
        )
        assert isinstance(value, Str)
        assert value.from_file is not None

    def test_str_of_a_path_is_a_string(self, tmp_path):
        value, _ = _evaluate(tmp_path, "", 'self.execute(str(Path("db") / "x.sql"))')
        assert value == Str("db/x.sql")

    def test_missing_file_names_the_bases(self, tmp_path, monkeypatch):
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)

        value, _ = _evaluate(tmp_path, "", 'self.execute(Path("db/schema/nope.sql").read_text())')

        _refused(value, Refusal.FILE_MISSING, str(tmp_path / "project"), "next to the migration")
        assert value.hint == "file_missing"
        assert str(elsewhere) not in value.reason

    def test_escape_is_refused_and_never_read(self, tmp_path, monkeypatch):
        secret = tmp_path / "outside.sql"
        secret.write_text("SECRET")
        original = Path.read_text

        def _guarded(self_path: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
            if self_path.resolve() == secret.resolve():
                raise AssertionError(f"read forbidden file {self_path!r}")
            return original(self_path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", _guarded)
        monkeypatch.chdir(tmp_path / "project") if (tmp_path / "project").exists() else None

        value, _ = _evaluate(tmp_path, "", 'self.execute(Path("../outside.sql").read_text())')

        _refused(value, Refusal.FILE_ESCAPED, "read_text", "outside project_root")
        assert value.hint == "file_escaped"

    def test_read_text_on_an_unresolved_receiver_carries_the_inner_reason(self, tmp_path):
        value, _ = _evaluate(tmp_path, "", "for p in ():\n    self.execute(Path(p).read_text())")
        _refused(value, Refusal.READ_TEXT_RECEIVER, "`p`", "for")
        assert value.hint == "read_text"

    def test_read_text_with_positional_arguments_is_refused(self, tmp_path):
        value, _ = _evaluate(
            tmp_path, "", 'self.execute(Path("db/schema/fn.sql").read_text("utf-8"))'
        )
        _refused(value, Refusal.UNSUPPORTED_CALL, "read_text")
        assert value.hint == "read_text"


# --------------------------------------------------------------------------- #
# Pure string operations on static inputs                                       #
# --------------------------------------------------------------------------- #


class TestPureStringOperations:
    def test_replace_chain_on_a_constant(self, tmp_path):
        value, _ = _evaluate(
            tmp_path,
            '_T = "CREATE TABLE __T__ (id int)"\n'
            'DDL = _T.replace("__T__", "a").replace("TABLE", "TABLE IF NOT EXISTS")',
            "self.execute(DDL)",
        )
        assert value == Str("CREATE TABLE IF NOT EXISTS a (id int)")

    def test_replace_with_a_count(self, tmp_path):
        value, _ = _evaluate(tmp_path, "", 'self.execute("a a a".replace("a", "b", 2))')
        assert value == Str("b b a")

    def test_format_with_static_arguments(self, tmp_path):
        value, _ = _evaluate(
            tmp_path, "", 'self.execute("DROP TABLE IF EXISTS {}.{name}".format("s", name="t"))'
        )
        assert value == Str("DROP TABLE IF EXISTS s.t")

    def test_format_with_a_runtime_argument_carries_the_inner_reason(self, tmp_path):
        value, _ = _evaluate(
            tmp_path, "", 'for t in ():\n    self.execute("DROP TABLE {}".format(t))'
        )
        _refused(value, Refusal.OTHER_BINDING, "`t`")

    def test_format_with_mismatched_placeholders(self, tmp_path):
        value, _ = _evaluate(tmp_path, "", 'self.execute("DROP TABLE {} {}".format("a"))')
        _refused(value, Refusal.UNSUPPORTED_CALL, "format")

    def test_join_over_a_static_sequence(self, tmp_path):
        value, _ = _evaluate(
            tmp_path, 'STMTS = ("SELECT 1", "SELECT 2")', 'self.execute(";\\n".join(STMTS))'
        )
        assert value == Str("SELECT 1;\nSELECT 2")

    def test_dedent_and_strip(self, tmp_path):
        value, _ = _evaluate(
            tmp_path,
            "from textwrap import dedent",
            'self.execute(dedent("""\n    SELECT 1\n    """).strip())',
        )
        assert value == Str("SELECT 1")

    def test_textwrap_dedent_spelled_out(self, tmp_path):
        value, _ = _evaluate(
            tmp_path, "import textwrap", 'self.execute(textwrap.dedent("  SELECT 1").upper())'
        )
        assert value == Str("SELECT 1")

    def test_a_string_operation_keeps_file_provenance(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        value, _ = _evaluate(
            tmp_path, "", 'self.execute(Path("db/schema/fn.sql").read_text().strip())'
        )
        assert isinstance(value, Str)
        assert value.from_file is not None

    def test_a_method_outside_the_whitelist_is_refused(self, tmp_path):
        value, _ = _evaluate(tmp_path, "", 'self.execute("select 1".title())')
        _refused(value, Refusal.UNSUPPORTED_CALL, "title")

    def test_a_string_method_on_a_path_is_refused(self, tmp_path):
        value, _ = _evaluate(tmp_path, "", 'self.execute(Path("x").replace("a", "b"))')
        _refused(value, Refusal.UNSUPPORTED_CALL, "replace")


# --------------------------------------------------------------------------- #
# One-line reader helpers                                                       #
# --------------------------------------------------------------------------- #

_SCHEMA_CONST = '_SCHEMA = Path(__file__).resolve().parent.parent / "schema"'


class TestReaderHelpers:
    def test_module_function_with_star_parts(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        value, trace = _evaluate(
            tmp_path,
            f"{_SCHEMA_CONST}\n\n\ndef _read_sql(*parts: str) -> str:\n"
            '    """Read a schema file."""\n'
            "    return (_SCHEMA / Path(*parts)).read_text()",
            'self.execute(_read_sql("fn.sql"))',
        )
        assert isinstance(value, Str)
        assert value.from_file is not None
        assert trace.names == ("_read_sql", "_SCHEMA")

    def test_module_function_with_a_named_parameter(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        value, _ = _evaluate(
            tmp_path,
            f"{_SCHEMA_CONST}\n\n\ndef _sql(name: str) -> str:\n    return (_SCHEMA / name).read_text()",
            'self.execute(_sql(name="fn.sql"))',
        )
        assert isinstance(value, Str)
        assert value.from_file is not None

    def test_method_helper_reading_a_class_attribute_directory(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        value, trace = _evaluate(
            tmp_path,
            _SCHEMA_CONST,
            'self.execute(self._read("fn.sql"))',
            class_body="_DIR = _SCHEMA\n\ndef _read(self, rel: str) -> str:\n    return (self._DIR / rel).read_text()",
        )
        assert isinstance(value, Str)
        assert value.from_file is not None
        assert trace.names == ("_read", "_DIR", "_SCHEMA")

    def test_fstring_wrapper_helper(self, tmp_path):
        value, _ = _evaluate(
            tmp_path,
            'DDL = "CREATE TABLE IF NOT EXISTS a (id int)"\n\n\n'
            "def _guard(sql: str) -> str:\n"
            '    return f"DO $$ BEGIN {sql}; END $$"',
            "self.execute(_guard(DDL))",
        )
        assert value == Str(
            "DO $$ BEGIN CREATE TABLE IF NOT EXISTS a (id int); END $$", is_fstring=True
        )

    def test_default_parameter_value(self, tmp_path):
        value, _ = _evaluate(
            tmp_path,
            'def _stmt(name: str, ext: str = ".sql") -> str:\n    return "-- " + name + ext',
            'self.execute(_stmt("fn"))',
        )
        assert value == Str("-- fn.sql")

    def test_parameter_shadows_a_module_constant_inside_the_helper(self, tmp_path):
        value, _ = _evaluate(
            tmp_path,
            'DDL = "module"\n\n\ndef _same(DDL: str) -> str:\n    return DDL',
            'self.execute(_same("call"))',
        )
        assert value == Str("call")

    def test_two_statement_helper_is_refused(self, tmp_path):
        value, _ = _evaluate(
            tmp_path,
            f"{_SCHEMA_CONST}\n\n\ndef _read(name: str) -> str:\n"
            "    text = (_SCHEMA / name).read_text()\n"
            "    return text.strip()",
            'self.execute(_read("fn.sql"))',
        )
        _refused(value, Refusal.HELPER_SHAPE, "_read", "single `return")

    def test_decorated_helper_is_refused(self, tmp_path):
        value, _ = _evaluate(
            tmp_path,
            "import functools\n\n\n@functools.cache\ndef _read(name: str) -> str:\n    return name",
            'self.execute(_read("x"))',
        )
        _refused(value, Refusal.HELPER_SHAPE, "_read", "decorat")

    def test_wrong_arity_is_refused(self, tmp_path):
        value, _ = _evaluate(
            tmp_path, "def _one(a: str) -> str:\n    return a", 'self.execute(_one("x", "y"))'
        )
        _refused(value, Refusal.HELPER_ARGUMENTS, "_one")

    def test_missing_argument_is_refused(self, tmp_path):
        value, _ = _evaluate(
            tmp_path, "def _one(a: str) -> str:\n    return a", "self.execute(_one())"
        )
        _refused(value, Refusal.HELPER_ARGUMENTS, "_one", "`a`")

    def test_mutual_recursion_is_a_cycle(self, tmp_path):
        value, _ = _evaluate(
            tmp_path,
            "def _a() -> str:\n    return _b()\n\n\ndef _b() -> str:\n    return _a()",
            "self.execute(_a())",
        )
        _refused(value, Refusal.CYCLE, "_a")

    def test_helpers_deeper_than_the_cap(self, tmp_path):
        chain = "\n\n\n".join(f"def _h{i}() -> str:\n    return _h{i + 1}()" for i in range(12))
        chain += '\n\n\ndef _h12() -> str:\n    return "x"'
        value, _ = _evaluate(tmp_path, chain, "self.execute(_h0())")
        _refused(value, Refusal.DEPTH)

    def test_a_call_to_something_that_is_not_a_helper_in_this_file(self, tmp_path):
        value, _ = _evaluate(tmp_path, "from helpers import _read", 'self.execute(_read("x"))')
        _refused(value, Refusal.UNSUPPORTED_CALL, "_read", "not a helper defined in this file")

    def test_a_method_that_is_not_defined_in_the_class(self, tmp_path):
        value, _ = _evaluate(tmp_path, "", 'self.execute(self._read("x"))')
        _refused(value, Refusal.UNSUPPORTED_CALL, "_read")


class TestWhenScopeAnalysisIsUnavailable:
    """If symtable and the AST cannot be paired, names refuse — but calls are still found.

    A file whose scopes cannot be paired must not become a silent pass: every
    execute call inside a method still yields a snippet (literal) or a
    warning (anything needing a name), never nothing.
    """

    def test_calls_inside_methods_are_still_reported(self, tmp_path, monkeypatch):
        import symtable as symtable_module

        def _broken(*args, **kwargs):
            raise SyntaxError("simulated symtable failure")

        monkeypatch.setattr(symtable_module, "symtable", _broken)
        root = _project(tmp_path)
        path = root / "db" / "migrations" / "20260101000000_m.py"
        text = _migration('DDL = "SELECT 1"', 'self.execute("SELECT 0")\nself.execute(DDL)')
        path.write_text(text)

        model = ModuleModel(text, path=path, project_root=root)
        calls = list(model.execute_calls())

        assert model.scopes_ok is False
        assert len(calls) == 2
        literal, _ = model.evaluate(calls[0][0].args[0], calls[0][1])
        named, _ = model.evaluate(calls[1][0].args[0], calls[1][1])
        assert literal == Str("SELECT 0")
        _refused(named, Refusal.SCOPE_UNAVAILABLE, "`DDL`")


class TestBoundaryThroughPathArithmetic:
    """The v0.8.4 confinement holds for every grammar path, not just literals."""

    def test_parents_past_the_root_is_refused(self, tmp_path):
        value, _ = _evaluate(tmp_path, "", "self.execute(Path(__file__).parents[40].read_text())")
        _refused(value, Refusal.READ_TEXT_RECEIVER, "parents[40]", "past the root")

    def test_dunder_file_arithmetic_escaping_the_project_is_refused(self, tmp_path, monkeypatch):
        secret = tmp_path / "secret.sql"
        secret.write_text("SECRET")
        original = Path.read_text

        def _guarded(self_path: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
            if self_path.resolve() == secret.resolve():
                raise AssertionError("read forbidden file")
            return original(self_path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", _guarded)

        value, _ = _evaluate(
            tmp_path, "", 'self.execute((Path(__file__).parents[3] / "secret.sql").read_text())'
        )

        _refused(value, Refusal.FILE_ESCAPED, "outside project_root")

    def test_absolute_literal_outside_the_project_is_refused(self, tmp_path):
        secret = tmp_path / "secret.sql"
        secret.write_text("SECRET")

        value, _ = _evaluate(tmp_path, "", f'self.execute(Path("{secret}").read_text())')

        _refused(value, Refusal.FILE_ESCAPED)
