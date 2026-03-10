"""Tests for JSON Schema generation from Confiture result models."""

from __future__ import annotations

import json
from pathlib import Path


# ── B-1: generate_schema returns valid schema for each known model ────────────


def test_generate_schema_migrate_up_result():
    from confiture.core.schema_exporter import generate_schema

    schema = generate_schema("MigrateUpResult")
    assert schema["type"] == "object"
    assert "success" in schema["properties"]
    assert "applied" in schema["properties"]
    assert "total_duration_ms" in schema["properties"]


def test_generate_schema_apply_result():
    from confiture.core.schema_exporter import generate_schema

    schema = generate_schema("ApplyResult")
    assert schema["properties"]["total"]["type"] == "integer"
    assert schema["properties"]["success"]["type"] == "boolean"


def test_generate_schema_all_names():
    from confiture.core.schema_exporter import SCHEMA_NAMES, generate_schema

    for name in SCHEMA_NAMES:
        schema = generate_schema(name)
        assert "type" in schema or "$schema" in schema, f"{name} missing type/$schema"


def test_generate_schema_unknown_raises():
    from confiture.core.schema_exporter import generate_schema

    try:
        generate_schema("NonExistentModel")
        raise AssertionError("Should have raised KeyError")
    except KeyError:
        pass


# ── B-2: export_all writes expected files ─────────────────────────────────────


def test_export_all_writes_expected_files(tmp_path: Path):
    from confiture.core.schema_exporter import _FILENAME_MAP, export_all

    written = export_all(tmp_path)
    filenames = {p.name for p in written}

    for expected_filename in _FILENAME_MAP.values():
        assert expected_filename in filenames, f"Missing: {expected_filename}"


def test_export_all_files_are_valid_json(tmp_path: Path):
    from confiture.core.schema_exporter import export_all

    written = export_all(tmp_path)
    for path in written:
        content = path.read_text()
        parsed = json.loads(content)
        assert isinstance(parsed, dict), f"{path.name} is not a JSON object"


def test_export_all_schemas_have_required_keys(tmp_path: Path):
    from confiture.core.schema_exporter import export_all

    written = export_all(tmp_path)
    for path in written:
        schema = json.loads(path.read_text())
        assert "$schema" in schema, f"{path.name} missing '$schema'"
        assert "title" in schema, f"{path.name} missing 'title'"
        assert "type" in schema, f"{path.name} missing 'type'"


# ── B-3: committed schemas match generated ────────────────────────────────────


def test_committed_schemas_match_generated(tmp_path: Path):
    """Regression: committed schemas match what export_all() generates.

    Fails if models change without regenerating schemas via:
        python -c "from confiture.core.schema_exporter import export_all; \\
                   from pathlib import Path; export_all(Path('python/confiture/schemas'))"
    """
    from importlib.resources import files

    from confiture.core.schema_exporter import _FILENAME_MAP, _all_schemas

    schemas_package = files("confiture.schemas")
    generated = _all_schemas()

    for model_name, filename in _FILENAME_MAP.items():
        committed_text = schemas_package.joinpath(filename).read_text()
        committed = json.loads(committed_text)
        regenerated = generated[model_name]
        assert committed == regenerated, (
            f"Committed schema for {model_name} ({filename}) is out of date. "
            "Regenerate with: python -c \"from confiture.core.schema_exporter import "
            "export_all; from pathlib import Path; "
            "export_all(Path('python/confiture/schemas'))\""
        )


# ── B-4: importlib.resources access ──────────────────────────────────────────


def test_schemas_accessible_via_importlib_resources():
    from importlib.resources import files

    resource = files("confiture.schemas").joinpath("migrate_up_result.json")
    content = resource.read_text()
    schema = json.loads(content)
    assert schema["title"] == "MigrateUpResult"


# ── B-5: public API ───────────────────────────────────────────────────────────


def test_generate_schema_in_public_api():
    import confiture

    assert "generate_schema" in confiture.__all__
    schema = confiture.generate_schema("StatusResult")
    assert schema["title"] == "StatusResult"


def test_export_all_schemas_in_public_api(tmp_path: Path):
    import confiture

    assert "export_all_schemas" in confiture.__all__
    written = confiture.export_all_schemas(tmp_path)
    assert len(written) == 16


# ── B-6: schemas validate real to_dict() output ──────────────────────────────


def test_migrate_up_result_matches_schema():
    """MigrateUpResult.to_dict() validates against generated schema."""
    from confiture.core.schema_exporter import generate_schema
    from confiture.models.results import MigrateUpResult

    result = MigrateUpResult(
        success=True,
        migrations_applied=[],
        total_execution_time_ms=42,
        checksums_verified=True,
        dry_run=False,
        warnings=[],
        skipped=[],
        errors=[],
    )
    output = result.to_dict()
    schema = generate_schema("MigrateUpResult")

    # Validate required keys are present
    for key in schema.get("required", []):
        assert key in output, f"Required key '{key}' missing from to_dict() output"

    # Validate types on key fields
    assert isinstance(output["success"], bool)
    assert isinstance(output["applied"], list)
    assert isinstance(output["total_duration_ms"], int)


def test_apply_result_matches_schema():
    from confiture.core.schema_exporter import generate_schema
    from confiture.core.seed_applier import ApplyResult

    result = ApplyResult(total=3, succeeded=2, failed=1, failed_files=["bad.sql"])
    output = result.to_dict()
    schema = generate_schema("ApplyResult")

    for key in schema.get("required", []):
        assert key in output, f"Required key '{key}' missing from to_dict() output"
