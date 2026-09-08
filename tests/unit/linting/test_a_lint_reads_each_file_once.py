"""Adding a rule to the linter must not add a trip to disk.

The campaign added six rules to a linter that already had fourteen, and each new
one needs the files *as files* — a `build_003` body's line number, a `qual_001`
statement's location, a `-- confiture:` directive — rather than the single string
the build concatenates them into. Every one asked `_sources()` for that, and
`_sources()` went to disk each time it was asked. A default lint opened every
file **five** times on a schema tree that is routinely thousands of files.

Three reads remain, and each is a different question asked of the same bytes:

1. the builder validates comments across the files it is about to join;
2. the builder reads them again to join them;
3. the linter reads them once, for every rule that wants a location.

The first two belong to `confiture build` and are the same on a build with no
lint at all. The third is this module's, and the invariant worth holding is that
it stays *one* however many rules run — which is why the selections below are
compared against each other and not only against a number.
"""

from __future__ import annotations

import collections
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from confiture.cli.commands.schema import _linter_config
from confiture.core.linting.gate import Threshold
from confiture.core.linting.rule_registry import resolve_selection
from confiture.core.linting.schema_linter import SchemaLinter

_ENV = "database_url: postgresql://127.0.0.1:1/x\ninclude_dirs:\n  - path: db/schema\n"
_TABLES = """CREATE SCHEMA IF NOT EXISTS app;
CREATE TABLE app.tb_widget (pk_widget BIGINT PRIMARY KEY);
COMMENT ON TABLE app.tb_widget IS 'A widget the catalogue offers.';
"""
_ROUTINE = (
    "CREATE FUNCTION app.fn_x() RETURNS int LANGUAGE sql "
    "AS $$ SELECT pk_widget FROM app.tb_widget $$;\n"
)

#: One read for the comment validation, one for the concatenation, one for the
#: rules. See this module's docstring for which is whose.
_READS_PER_FILE = 3


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Path]:
    (tmp_path / "db" / "schema").mkdir(parents=True)
    (tmp_path / "db" / "environments").mkdir(parents=True)
    (tmp_path / "db" / "environments" / "local.yaml").write_text(_ENV)
    (tmp_path / "db" / "schema" / "010.sql").write_text(_TABLES)
    (tmp_path / "db" / "schema" / "020.sql").write_text(_ROUTINE)

    old = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old)


def _reads(selectors: list[str] | None, monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    counts: collections.Counter[str] = collections.Counter()
    original = Path.read_text

    def counted(self: Path, *args: object, **kwargs: object) -> str:
        if self.suffix == ".sql":
            counts[self.name] += 1
        return original(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", counted)
    config = _linter_config(resolve_selection(selectors, ()), Threshold.NEVER)
    SchemaLinter(env="local", project_dir=Path(), config=config).lint()
    return dict(counts)


def test_a_default_lint_reads_each_file_three_times(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = {"010.sql": _READS_PER_FILE, "020.sql": _READS_PER_FILE}

    assert _reads(None, monkeypatch) == expected


def test_the_rules_between_them_account_for_exactly_one_of_those(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One rule reading only the inventory costs what nineteen rules cost.

    `pk_001` wants no file text at all; the default set wants locations for
    nine rules; `qual_002` adds a tenth. If any of them reached disk on its own
    behalf these three would differ.
    """
    only_inventory = _reads(["pk_001"], monkeypatch)
    by_default = _reads(None, monkeypatch)
    everything_static = _reads(["default,qual_002"], monkeypatch)

    assert only_inventory == by_default == everything_static


def test_a_reused_linter_sees_the_file_as_it_is_now(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The text is held for one lint, not for the linter's lifetime."""
    linter = SchemaLinter(
        env="local",
        project_dir=Path(),
        config=_linter_config(resolve_selection(None, ()), Threshold.NEVER),
    )
    assert [v.rule_id for v in linter.lint().errors] == []

    (project / "db" / "schema" / "030.sql").write_text(
        "CREATE TABLE app.tb_widget (pk_widget BIGINT PRIMARY KEY);\n"
    )

    assert [v.rule_id for v in linter.lint().errors] == ["build_001"]
