"""The severity `--list-rules` prints is the severity the rule emits.

`acl_001` emitted `RuleSeverity.ERROR` and its registry entry declared
`warning` (LINT-01), so the catalogue an operator reads to choose a `--fail-on`
threshold was wrong about the one rule that could reach `error`. Nothing held
the two together.

This does: every registered rule is driven against a fixture that violates it,
through the real CLI, and the emitted severity must equal the declared one — or,
for a rule that declares itself config-escalable, the declared one *and* the
escalated one, both exercised. A rule added to `LINT_RULES` without a fixture
here fails, so the table cannot grow a lie.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.linting.rule_registry import LINT_RULES

runner = CliRunner()

_BASE_ENV = "database_url: postgresql://localhost/test\ninclude_dirs:\n  - path: db/schema\n"


@dataclass(frozen=True)
class Fixture:
    """A project that trips exactly one rule, and how to run that rule against it."""

    schema: dict[str, str]
    env_extra: str = ""
    #: The config that raises the rule above its declared severity, when it has one.
    escalated_env_extra: str | None = None
    migrations: dict[str, str] = field(default_factory=dict)
    #: Files outside `db/schema` and `db/migrations`, keyed by project-relative path.
    extra_files: dict[str, str] = field(default_factory=dict)
    extra_args: tuple[str, ...] = ()


_ACLS = (
    "acls:\n"
    "  lint_enabled: true\n"
    "  expectations:\n"
    "    - schema: public\n"
    "      apply_to: ALL_TABLES\n"
    "      grants:\n"
    "        - role: my_app\n"
    "          privileges: [SELECT]\n"
)

_OWNERSHIP = (
    "ownership:\n"
    "  expected_owner: app_owner\n"
    "  lint_enabled: true\n"
    "  apply_to:\n"
    "    - schema: public\n"
    "      relkinds: [r]\n"
)

_TENANT_SCHEMA = """CREATE TABLE tb_item (id INT PRIMARY KEY, name TEXT, fk_org INT);
CREATE TABLE tv_organization (pk_organization INT PRIMARY KEY);

CREATE VIEW v_item AS
SELECT i.id, i.name, o.pk_organization AS tenant_id
FROM tb_item i
JOIN tv_organization o ON i.fk_org = o.pk_organization;

CREATE FUNCTION fn_create_item() RETURNS VOID AS $$
BEGIN
    INSERT INTO tb_item (id, name) VALUES (1, 'test');
END;
$$ LANGUAGE plpgsql;
"""

FIXTURES: dict[str, Fixture] = {
    "naming_001": Fixture({"010.sql": "CREATE TABLE BadName (id INT PRIMARY KEY);\n"}),
    "naming_002": Fixture({"010.sql": "CREATE TABLE tb_t (id INT PRIMARY KEY, badCol INT);\n"}),
    "pk_001": Fixture({"010.sql": "CREATE TABLE tb_t (id INT);\n"}),
    "doc_001": Fixture({"010.sql": "CREATE TABLE tb_t (id INT PRIMARY KEY);\n"}),
    "doc_002": Fixture(
        {"010.sql": "CREATE FUNCTION fn_f() RETURNS int LANGUAGE sql AS $$ SELECT 1 $$;\n"}
    ),
    "doc_003": Fixture({"010.sql": "CREATE VIEW v_t AS SELECT 1 AS x;\n"}),
    "doc_004": Fixture({"010.sql": "CREATE TYPE ty_t AS (a int);\n"}),
    "build_001": Fixture(
        {
            "010.sql": "CREATE TABLE tb_t (id INT PRIMARY KEY);\n",
            "020.sql": "CREATE TABLE tb_t (id INT PRIMARY KEY);\n",
        }
    ),
    "build_002": Fixture(
        {
            "010.sql": "CREATE FUNCTION fn_f(a int) RETURNS int LANGUAGE sql AS $$ SELECT 1 $$;\n",
            "020.sql": "CREATE FUNCTION fn_f(a text) RETURNS int LANGUAGE sql AS $$ SELECT 1 $$;\n",
        }
    ),
    "build_003": Fixture(
        {
            "010.sql": "CREATE VIEW v_t AS SELECT id FROM app.tb_nobody_creates_this;\n",
        }
    ),
    "sec_001": Fixture({"010.sql": "CREATE TABLE tb_t (id INT PRIMARY KEY, password TEXT);\n"}),
    "qual_001": Fixture(
        {"010.sql": "CREATE FUNCTION fn_f() RETURNS int LANGUAGE sql AS $$ SELECT 1 $$;\n"}
    ),
    "qual_002": Fixture({"010.sql": "CREATE TABLE tb_t (id INT PRIMARY KEY);\n"}),
    "acl_001": Fixture(
        {"010.sql": "CREATE TABLE tb_t (id INT PRIMARY KEY);\n"},
        env_extra=_ACLS,
        migrations={"20260908120000.up.sql": "CREATE TABLE uncovered (id int);"},
    ),
    "tenant_001": Fixture({"010.sql": _TENANT_SCHEMA}),
    "replica_001": Fixture(
        {"010.sql": "CREATE TABLE tb_t (id INT PRIMARY KEY, c INT);\n"},
        escalated_env_extra="infrastructure:\n  replicas:\n    - read-1\n",
        migrations={"20260908120000.up.sql": "ALTER TABLE tb_t DROP COLUMN c;"},
    ),
    "sec_002": Fixture(
        {
            "010.sql": "CREATE FUNCTION fn_f() RETURNS int "
            "LANGUAGE sql SECURITY DEFINER AS $$ SELECT 1 $$;\n"
        },
        env_extra="security_lint:\n  enabled: true\n",
        escalated_env_extra="security_lint:\n  enabled: true\n  severity: error\n",
    ),
    "func_001": Fixture(
        {
            "010.sql": "CREATE FUNCTION fn_f(a int) RETURNS int LANGUAGE sql AS $$ SELECT 1 $$;\n",
            "020.sql": "CREATE FUNCTION fn_f(a int) RETURNS int LANGUAGE sql AS $$ SELECT 2 $$;\n",
        },
        env_extra="function_coverage:\n  enabled: true\n",
    ),
    "own_001": Fixture(
        {"010.sql": "CREATE TABLE tb_t (id INT PRIMARY KEY);\n"},
        env_extra=_OWNERSHIP,
        migrations={"20260908120000.up.sql": "CREATE TABLE public.tb_new (id int);"},
    ),
    "own_002": Fixture(
        {"010.sql": "CREATE TABLE tb_t (id INT PRIMARY KEY);\n"},
        env_extra=_OWNERSHIP,
        migrations={"20260908120000.up.sql": "ALTER TABLE public.tb_old OWNER TO app_owner;"},
    ),
    "tree_001": Fixture(
        {
            "00001_create.sql": "CREATE TABLE tb_a (id INT PRIMARY KEY);\n",
            "00001_update.sql": "CREATE TABLE tb_b (id INT PRIMARY KEY);\n",
        }
    ),
    "tree_002": Fixture({"00001.sql": "CREATE TABLE tb_a (id INT PRIMARY KEY);\n"}),
    "tree_003": Fixture(
        {
            "00001_create.sql": "CREATE TABLE tb_a (id INT PRIMARY KEY);\n",
            "00009_create.sql": "CREATE TABLE tb_b (id INT PRIMARY KEY);\n",
        }
    ),
    "tree_004": Fixture(
        {"00001_create.sql": "CREATE TABLE tb_a (id INT PRIMARY KEY);\n"},
        extra_files={"db/overrides/00002_gone.sql": "-- override of a file that is not there\n"},
        extra_args=("--overrides-dir", "db/overrides"),
    ),
    "tree_005": Fixture(
        {
            "0248_a/00001_create.sql": "CREATE TABLE tb_a (id INT PRIMARY KEY);\n",
            "0248_b/00001_create.sql": "CREATE TABLE tb_b (id INT PRIMARY KEY);\n",
        }
    ),
    "tree_006": Fixture(
        {
            "03_f/034_dim/0341_geo/03452_odd/00001_create.sql": (
                "CREATE TABLE tb_a (id INT PRIMARY KEY);\n"
            ),
        }
    ),
}


def test_every_registered_rule_has_a_violating_fixture() -> None:
    """A rule with no fixture here is a rule nothing holds to its declaration."""
    missing = [rule.code for rule in LINT_RULES if rule.code not in FIXTURES]

    assert missing == [], f"add a violating fixture for: {missing}"


def _build(tmp_path: Path, fixture: Fixture, env_extra: str) -> None:
    (tmp_path / "db" / "schema").mkdir(parents=True, exist_ok=True)
    (tmp_path / "db" / "environments").mkdir(parents=True, exist_ok=True)
    (tmp_path / "db" / "environments" / "local.yaml").write_text(_BASE_ENV + env_extra)
    for name, sql in fixture.schema.items():
        path = tmp_path / "db" / "schema" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(sql)
    if fixture.migrations:
        (tmp_path / "db" / "migrations").mkdir(parents=True, exist_ok=True)
        for name, sql in fixture.migrations.items():
            (tmp_path / "db" / "migrations" / name).write_text(sql)
    for rel, text in fixture.extra_files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


@pytest.fixture
def in_tmp(tmp_path: Path) -> Iterator[Path]:
    old_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old_cwd)


def _emitted(code: str, tmp_path: Path, fixture: Fixture, env_extra: str) -> list[str]:
    _build(tmp_path, fixture, env_extra)
    result = runner.invoke(
        app,
        ["lint", "--select", code, "--format", "json", "--fail-on", "never", *fixture.extra_args],
    )
    assert result.exit_code == 0, result.output
    items = json.loads(result.stdout)["violations"]["items"]
    return [i["severity"] for i in items if i["rule_id"] == code]


@pytest.mark.parametrize("rule", LINT_RULES, ids=lambda r: r.code)
def test_the_rule_emits_the_severity_the_registry_declares(rule, in_tmp: Path) -> None:
    fixture = FIXTURES[rule.code]

    emitted = _emitted(rule.code, in_tmp, fixture, fixture.env_extra)

    assert emitted, f"{rule.code} reported nothing on a fixture that violates it"
    assert set(emitted) == {rule.severity}


@pytest.mark.parametrize("rule", [r for r in LINT_RULES if r.escalates_to], ids=lambda r: r.code)
def test_an_escalable_rule_reaches_the_severity_it_declares(rule, in_tmp: Path) -> None:
    fixture = FIXTURES[rule.code]
    assert fixture.escalated_env_extra is not None, f"{rule.code} declares no escalated config"

    emitted = _emitted(rule.code, in_tmp, fixture, fixture.escalated_env_extra)

    assert emitted, f"{rule.code} reported nothing under {rule.escalated_by}"
    assert set(emitted) == {rule.escalates_to}
