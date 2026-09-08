"""How ``build_003`` stays quiet about a legitimate reference, and says when it cannot (D4).

Tier (a) is the build inventory. It is complete for a project whose objects all
come from the DDL tree and wrong for every other kind — an object created by a
migration, or owned by an extension, is real and absent from the tree. So there
are two tiers under it: an optional live database, consulted once per run and
only for the names the build could not answer, and ``lint.ignore_objects`` in
the environment YAML for a project that has neither.

The part that matters as much as the tiers is the honesty. A run where the live
tier did not answer is a *degraded* run, and saying "12 unresolved references"
without saying "and six of them may be created by migrations I could not see"
is how a rule loses its reader. The degradation is stated in the table and in
the JSON, in the shape a check that could not run at all uses too.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.linting.schema_linter import LintReport, RuleStatus

runner = CliRunner()

#: A database name nothing is listening on: the live tier cannot answer.
_UNREACHABLE = "database_url: postgresql://127.0.0.1:1/confiture_no_such_server\n"
_ENV = _UNREACHABLE + "include_dirs:\n  - path: db/schema\n"

EXTENSION_CALLER = """CREATE SCHEMA IF NOT EXISTS app;
CREATE FUNCTION app.fn_id() RETURNS uuid LANGUAGE sql AS $$
    SELECT public.gen_random_uuid()
$$;
"""


def _project(root: Path, files: dict[str, str], env: str = _ENV) -> None:
    (root / "db" / "schema").mkdir(parents=True, exist_ok=True)
    (root / "db" / "environments").mkdir(parents=True, exist_ok=True)
    (root / "db" / "environments" / "local.yaml").write_text(env)
    for name, sql in files.items():
        (root / "db" / "schema" / name).write_text(sql)


@pytest.fixture
def in_tmp(tmp_path: Path) -> Iterator[Path]:
    old = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old)


def _payload(*args: str) -> dict:
    result = runner.invoke(
        app, ["lint", "--select", "build_003", "--format", "json", "--fail-on", "never", *args]
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def _codes(payload: dict) -> list[str]:
    return [i["location"] for i in payload["violations"]["items"] if i["rule_id"] == "build_003"]


def test_an_extension_function_reports_under_the_build_inventory_alone(in_tmp: Path) -> None:
    """Tier (a) knows only the tree: ``public.gen_random_uuid`` is not in it."""
    _project(in_tmp, {"010_fn.sql": EXTENSION_CALLER})

    assert _codes(_payload()) == ["app.fn_id() -> public.gen_random_uuid"]


def test_a_run_without_the_live_tier_says_so_in_json(in_tmp: Path) -> None:
    """A degraded run is a stated degradation, not a silent one."""
    _project(in_tmp, {"010_fn.sql": EXTENSION_CALLER})

    degraded = _payload()["degraded"]

    assert [d["code"] for d in degraded] == ["build_003"]
    assert "no database" in degraded[0]["reason"]


def test_a_run_without_the_live_tier_says_so_in_the_table(in_tmp: Path) -> None:
    _project(in_tmp, {"010_fn.sql": EXTENSION_CALLER})

    result = runner.invoke(app, ["lint", "--select", "build_003", "--fail-on", "never"])

    assert result.exit_code == 0
    assert "build_003 ran without the live tier" in result.output


def test_nothing_is_said_when_every_name_resolved(in_tmp: Path) -> None:
    """With nothing left to ask about, no connection is attempted and none is reported.

    The live tier can only ever *remove* findings, so a run that found none was
    not weakened by its absence.
    """
    _project(
        in_tmp,
        {
            "010_fn.sql": (
                "CREATE SCHEMA IF NOT EXISTS app;\n"
                "CREATE TABLE app.tb_t (id int PRIMARY KEY);\n"
                "CREATE FUNCTION app.fn_c() RETURNS bigint LANGUAGE sql AS $$\n"
                "    SELECT id FROM app.tb_t\n"
                "$$;\n"
            )
        },
    )

    assert _payload().get("degraded", []) == []


def test_ignore_objects_silences_a_name_the_project_creates_elsewhere(in_tmp: Path) -> None:
    """Tier (c): the escape hatch for a project with no reachable database."""
    _project(
        in_tmp,
        {"010_fn.sql": EXTENSION_CALLER},
        env=_ENV + "lint:\n  ignore_objects:\n    - public.gen_random_uuid\n",
    )

    assert _codes(_payload()) == []


def test_ignore_objects_accepts_a_glob(in_tmp: Path) -> None:
    """``fnmatch`` over ``schema.name``, so a whole schema can be excused at once."""
    _project(
        in_tmp,
        {"010_fn.sql": EXTENSION_CALLER},
        env=_ENV + "lint:\n  ignore_objects:\n    - 'public.*'\n",
    )

    assert _codes(_payload()) == []


def test_an_ignored_name_does_not_make_the_run_degraded(in_tmp: Path) -> None:
    """Tier (c) is an answer, not a gap: nothing was left for the live tier."""
    _project(
        in_tmp,
        {"010_fn.sql": EXTENSION_CALLER},
        env=_ENV + "lint:\n  ignore_objects:\n    - public.gen_random_uuid\n",
    )

    assert _payload().get("degraded", []) == []


class TestTheStatusShape:
    """``skipped`` and ``degraded`` are one shape: a check that could not run at all
    needs the same three fields as one that ran short of a tier."""

    def test_a_report_starts_with_neither(self) -> None:
        report = LintReport()

        assert report.skipped == []
        assert report.degraded == []

    def test_a_status_carries_a_code_and_a_reason(self) -> None:
        status = RuleStatus(code="body_001", state="skipped", reason="plpgsql_check not installed")

        assert status.to_dict() == {
            "code": "body_001",
            "state": "skipped",
            "reason": "plpgsql_check not installed",
        }
