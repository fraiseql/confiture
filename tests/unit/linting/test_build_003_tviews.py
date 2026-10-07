"""``build_003``/``build_004``: a pg_tviews TVIEW is a relation the build creates (#651).

A tree declares one with ``pg_tviews_create_or_replace('s.tv_x', …)`` or with
``CREATE TABLE s.tv_x AS SELECT …``; the inventory holds both as one ``tview``. A
view or routine reading ``tv_x`` reads a relation the build creates.
"""

from pathlib import Path

import pytest

from confiture.core.linting.schema_linter import LintConfig, SchemaLinter

TABLES = (
    "CREATE TABLE public.tb_order (pk_order bigint PRIMARY KEY, id uuid NOT NULL, name text);\n"
    "CREATE VIEW public.v_order AS SELECT pk_order, id, name FROM public.tb_order;\n"
)
SPELLINGS = {
    "call": "SELECT tviews.pg_tviews_create_or_replace('public.tv_order', $tview$\n"
    "SELECT pk_order, id, name FROM public.v_order\n$tview$, '{\"logged\": true}');\n",
    "create-table-as": "CREATE TABLE public.tv_order AS SELECT pk_order, id, name "
    "FROM public.v_order;\n",
}
READERS = {
    "view": "CREATE VIEW public.v_order_names AS SELECT name FROM public.tv_order;\n",
    "routine": "CREATE FUNCTION public.fn_names() RETURNS SETOF text LANGUAGE sql AS "
    "$$ SELECT name FROM public.tv_order $$;\n",
}


def _findings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, files: dict[str, str]) -> list:
    schema = tmp_path / "db" / "schema"
    schema.mkdir(parents=True)
    (tmp_path / "db" / "environments").mkdir()
    (tmp_path / "db" / "environments" / "local.yaml").write_text(
        "name: local\ndatabase_url: postgresql:///unused?host=/nonexistent\n"
        "include_dirs:\n  - ./db/schema\n"
    )
    for name, text in files.items():
        (schema / name).write_text(text)
    monkeypatch.chdir(tmp_path)
    config = LintConfig(check_references=True, check_forward_references=True)
    report = SchemaLinter(env="local", config=config).lint()
    return [
        v
        for v in (*report.errors, *report.warnings, *report.info)
        if v.rule_id in {"build_003", "build_004"}
    ]


@pytest.mark.parametrize("spelling", sorted(SPELLINGS))
@pytest.mark.parametrize("reader", sorted(READERS))
def test_a_reader_of_a_tview_resolves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, spelling: str, reader: str
) -> None:
    files = {
        "01_tables.sql": TABLES,
        "02_tview.sql": SPELLINGS[spelling],
        "03_reader.sql": READERS[reader],
    }
    assert _findings(tmp_path, monkeypatch, files) == []


@pytest.mark.parametrize("spelling", sorted(SPELLINGS))
def test_a_reader_before_the_tview_is_a_forward_reference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, spelling: str
) -> None:
    files = {
        "01_tables.sql": TABLES,
        "02_reader.sql": READERS["view"],
        "03_tview.sql": SPELLINGS[spelling],
    }
    assert [v.rule_id for v in _findings(tmp_path, monkeypatch, files)] == ["build_004"]
