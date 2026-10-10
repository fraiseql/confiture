"""Validate ``migrate diff --format json`` output against its schema (issue #196)."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from typer.testing import CliRunner

from confiture.cli.main import app

SCHEMA_FILE = "migrate-diff.schema.json"
FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "desired_state" / "emit_ddl"


def _load(schemas_dir: Path, name: str) -> dict:
    return json.loads((schemas_dir / name).read_text())


def _validator(schemas_dir, registry) -> Draft202012Validator:
    return Draft202012Validator(_load(schemas_dir, SCHEMA_FILE), registry=registry)


def test_schema_is_valid_draft_2020_12(schemas_dir):
    Draft202012Validator.check_schema(_load(schemas_dir, SCHEMA_FILE))


def test_diff_against_an_artifact_validates(tmp_path, schemas_dir, schema_registry):
    current = tmp_path / "current.sql"
    current.write_text((FIXTURE / "user.sql").read_text())
    result = CliRunner().invoke(
        app, ["migrate", "diff", "--from", str(current), "--to", str(FIXTURE), "--format", "json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    _validator(schemas_dir, schema_registry).validate(payload)
    assert payload["source"] == {"kind": "sql", "path": str(FIXTURE)}


def test_generated_migration_payload_validates(tmp_path, schemas_dir, schema_registry):
    current = tmp_path / "current.sql"
    current.write_text((FIXTURE / "user.sql").read_text())
    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "diff",
            "--from",
            str(current),
            "--to",
            str(FIXTURE),
            "--generate",
            "--name",
            "add_posts",
            "--migrations-dir",
            str(tmp_path / "migrations"),
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    _validator(schemas_dir, schema_registry).validate(payload)
    assert payload["migration_generated"] is True


def test_failure_payload_validates(tmp_path, schemas_dir, schema_registry):
    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "diff",
            "--from",
            str(tmp_path / "absent.sql"),
            "--to",
            str(FIXTURE),
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 1
    payload = json.loads(result.output)
    _validator(schemas_dir, schema_registry).validate(payload)
    assert payload["success"] is False and payload["source"] is None


def test_a_duplicate_definition_is_published_as_a_warning(tmp_path, schemas_dir, schema_registry):
    """#313: an object defined twice in one tree is warned, never silently collapsed."""
    current = tmp_path / "current.sql"
    current.write_text("CREATE TABLE t (id INT);\n")
    desired = tmp_path / "desired.sql"
    desired.write_text("CREATE TABLE t (id INT);\nCREATE TABLE IF NOT EXISTS t (id INT, b TEXT);\n")
    result = CliRunner().invoke(
        app,
        ["migrate", "diff", "--from", str(current), "--to", str(desired), "--format", "json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    _validator(schemas_dir, schema_registry).validate(payload)
    assert [w["code"] for w in payload["warnings"]] == ["DIFFER_402"]
    assert payload["warnings"][0]["severity"] == "warning"


def test_a_clean_diff_publishes_an_empty_warnings_array(tmp_path, schemas_dir, schema_registry):
    """Present and empty, never absent-on-success (the `was_skipped` precedent, #311)."""
    current = tmp_path / "current.sql"
    # The artifact's indexes on a table it does not declare are on both sides: no warning.
    current.write_text(
        (FIXTURE / "user.sql").read_text() + (FIXTURE / "90_indexes.sql").read_text()
    )
    result = CliRunner().invoke(
        app, ["migrate", "diff", "--from", str(current), "--to", str(FIXTURE), "--format", "json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    _validator(schemas_dir, schema_registry).validate(payload)
    assert payload["warnings"] == []


def test_an_index_on_an_undeclared_table_publishes_differ_405(
    tmp_path, schemas_dir, schema_registry
):
    """The index the migration carries onto a table neither side declares is named (#679)."""
    current = tmp_path / "current.sql"
    current.write_text((FIXTURE / "user.sql").read_text())
    result = CliRunner().invoke(
        app, ["migrate", "diff", "--from", str(current), "--to", str(FIXTURE), "--format", "json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    _validator(schemas_dir, schema_registry).validate(payload)
    assert [(w["code"], w["severity"]) for w in payload["warnings"]] == [("DIFFER_405", "warning")]
    assert "ix_tv_product_name_fr" in payload["warnings"][0]["message"]


def test_a_desired_state_indexing_a_relation_it_drops_publishes_differ_406(tmp_path, schemas_dir):
    """The contradiction is refused in the error envelope, exit 5 (#679)."""
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    current = tmp_path / "current.sql"
    current.write_text("CREATE TABLE tv_product (id int, data jsonb);\n")
    result = CliRunner().invoke(
        app, ["migrate", "diff", "--from", str(current), "--to", str(FIXTURE), "--format", "json"]
    )
    assert result.exit_code == 5, result.output
    payload = json.loads(result.stdout)
    issue = Resource.from_contents(
        _load(schemas_dir, "issue-object.schema.json"), default_specification=DRAFT202012
    )
    Draft202012Validator(
        _load(schemas_dir, "error-envelope.schema.json"),
        registry=Registry().with_resource(uri="issue-object.schema.json", resource=issue),
    ).validate(payload)
    assert payload["error"]["code"] == "DIFFER_406"
    assert "ix_tv_product_name_fr" in payload["error"]["message"]


def test_an_index_on_a_tview_publishes_differ_407(tmp_path, schemas_dir, schema_registry):
    tree = "CREATE TABLE tb_p (id int);\nCREATE TABLE tv_p AS SELECT id FROM tb_p;\n"
    current, desired = tmp_path / "current.sql", tmp_path / "desired.sql"
    current.write_text(tree)
    desired.write_text(tree + "CREATE INDEX ix_tv_p_id ON tv_p (id);\n")
    result = CliRunner().invoke(
        app, ["migrate", "diff", "--from", str(current), "--to", str(desired), "--format", "json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    _validator(schemas_dir, schema_registry).validate(payload)
    assert [(w["code"], w["severity"]) for w in payload["warnings"]] == [("DIFFER_407", "warning")]
    assert payload["changes"] == []
