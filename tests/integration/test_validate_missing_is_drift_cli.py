"""``migrate validate --check-signatures [--missing-is-drift]`` end to end (#303).

The three things a deploy gate needs from this, on a real database:

* with **default flags** and a pristine database, `missing_from_db` is empty —
  which it was not, because a trigger function was filtered out of the live side
  only and `--schemas` defaulted to `public` while the DDL declared `core`;
* the verdict is in the payload whether or not the flag was passed;
* with `--missing-is-drift`, a genuinely undeployed routine exits 1, and without
  it the exit code is unchanged.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import psycopg
import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.psql_applier import apply_sql_via_psql

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "live_drift_corpus"
FILES = ("010_schema.sql", "020_tables.sql", "030_types.sql", "050_objects.sql")

runner = CliRunner()


@pytest.fixture
def project(fresh_database: str, tmp_path: Path) -> tuple[Path, Path, str]:
    """``(config, schema file, url)`` for a database built from the corpus."""
    sql = "\n".join((CORPUS / name).read_text(encoding="utf-8") for name in FILES)
    apply_sql_via_psql(fresh_database, sql=sql)

    schema_file = tmp_path / "schema.sql"
    schema_file.write_text(sql, encoding="utf-8")
    config = tmp_path / "confiture.yaml"
    config.write_text(
        textwrap.dedent(f"""\
        name: test
        database_url: {fresh_database}
        include_dirs: []
        """)
    )
    return config, schema_file, fresh_database


def validate(config: Path, schema_file: Path, *extra: str):
    return runner.invoke(
        app,
        [
            "migrate",
            "validate",
            "--check-signatures",
            "--config",
            str(config),
            "--schema",
            str(schema_file),
            "--format",
            "json",
            *extra,
        ],
    )


def signature_payload(result) -> dict:
    payload = json.loads(result.stdout)
    checks = payload.get("checks", payload)
    if isinstance(checks, dict) and "function_signature_drift" in checks:
        return checks["function_signature_drift"]
    return payload


def test_a_pristine_database_is_missing_nothing_with_default_flags(project) -> None:
    config, schema_file, _url = project
    result = validate(config, schema_file)
    payload = signature_payload(result)
    assert payload["missing_from_db"] == [], result.stdout
    assert payload["has_undeployed"] is False
    assert result.exit_code == 0, result.stdout


def test_the_schemas_checked_are_the_ones_the_source_declares(project) -> None:
    config, schema_file, _url = project
    payload = signature_payload(validate(config, schema_file))
    assert payload["schemas_checked"] == ["core"], payload


def test_an_explicit_schemas_still_wins(project) -> None:
    config, schema_file, _url = project
    payload = signature_payload(validate(config, schema_file, "--schemas", "public"))
    assert payload["schemas_checked"] == ["public"], payload


def test_an_undeployed_routine_without_the_flag_is_informational(project) -> None:
    config, schema_file, url = project
    with psycopg.connect(url) as conn:
        conn.execute("DROP FUNCTION core.fn_gone(bigint)")
        conn.commit()
    result = validate(config, schema_file)
    payload = signature_payload(result)
    assert payload["missing_from_db"] == ["core.fn_gone(bigint)"]
    assert payload["has_undeployed"] is True
    assert payload["has_critical_drift"] is False
    assert result.exit_code == 0, result.stdout


def test_an_undeployed_routine_with_the_flag_fails(project) -> None:
    config, schema_file, url = project
    with psycopg.connect(url) as conn:
        conn.execute("DROP FUNCTION core.fn_gone(bigint)")
        conn.commit()
    result = validate(config, schema_file, "--missing-is-drift")
    payload = signature_payload(result)
    assert payload["has_critical_drift"] is True
    assert payload["missing_is_drift"] is True
    assert result.exit_code == 1, result.stdout


def test_the_flag_requires_check_signatures(project) -> None:
    """The same guard, and the same exit code, as ``--check-body``'s.

    ``_FLAG_DEPENDENCIES`` raises ``CONFIG_001``, which the error boundary maps
    to **5**. Matching the flag that already exists matters more than matching a
    number: a caller who learns one learns both.
    """
    config, _schema_file, _url = project
    for modifier in ("--missing-is-drift", "--check-body"):
        result = runner.invoke(app, ["migrate", "validate", modifier, "--config", str(config)])
        assert result.exit_code == 5, (modifier, result.stdout)
