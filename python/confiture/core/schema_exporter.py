"""Generate JSON Schema v7 from Confiture result model to_dict() contracts.

Pre-generated schemas ship in confiture/schemas/ and can be loaded with::

    from importlib.resources import files
    import json
    schema = json.loads(
        files("confiture.schemas").joinpath("migrate_up_result.json").read_text()
    )

You can also regenerate them at any time::

    from confiture.core.schema_exporter import export_all
    from pathlib import Path
    export_all(Path("my-schemas/"))
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, get_args, get_origin


def _python_type_to_json_schema(t: Any) -> dict[str, Any]:
    """Convert a Python type annotation to a JSON Schema v7 fragment.

    Handles: str, int, float, bool, None/NoneType, list[X], dict[K,V], X|None.
    Falls back to {} (any type) for complex generics.
    """
    if t is type(None):
        return {"type": "null"}
    if t is str:
        return {"type": "string"}
    if t is int:
        return {"type": "integer"}
    if t is float:
        return {"type": "number"}
    if t is bool:
        return {"type": "boolean"}

    origin = get_origin(t)
    args = get_args(t)

    # Union / Optional (X | None)
    if origin is type(None):
        return {"type": "null"}

    # Python 3.10+ union: X | Y
    import types as _types

    if isinstance(t, _types.UnionType) or origin is _types.UnionType:
        schemas = [_python_type_to_json_schema(a) for a in args]
        if len(schemas) == 2 and {"type": "null"} in schemas:
            non_null = [s for s in schemas if s != {"type": "null"}][0]
            return {"anyOf": [non_null, {"type": "null"}]}
        return {"anyOf": schemas}

    # typing.Union
    try:
        import typing

        if origin is typing.Union:
            schemas = [_python_type_to_json_schema(a) for a in args]
            if len(schemas) == 2 and {"type": "null"} in schemas:
                non_null = [s for s in schemas if s != {"type": "null"}][0]
                return {"anyOf": [non_null, {"type": "null"}]}
            return {"anyOf": schemas}
    except AttributeError:
        pass

    if origin is list:
        item_schema = _python_type_to_json_schema(args[0]) if args else {}
        return {"type": "array", "items": item_schema}

    if origin is dict:
        return {"type": "object"}

    return {}


def _build_migration_applied_schema() -> dict[str, Any]:
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "MigrationApplied",
        "description": "A single migration that was applied or rolled back.",
        "type": "object",
        "required": ["version", "name", "duration_ms", "rows_affected"],
        "properties": {
            "version": {"type": "string"},
            "name": {"type": "string"},
            "duration_ms": {"type": "integer"},
            "rows_affected": {"type": "integer"},
        },
        "additionalProperties": False,
    }


def _ref(name: str) -> dict[str, Any]:
    return {"$ref": f"#/definitions/{name}"}


def generate_schema(model_name: str) -> dict[str, Any]:
    """Generate a JSON Schema v7 document for a named Confiture result model.

    The schema faithfully describes the structure returned by the model's
    ``to_dict()`` method, which is what agents consume from CLI ``--format json``
    output or library API calls.

    Args:
        model_name: One of the registered model names (e.g. "MigrateUpResult").

    Returns:
        JSON Schema v7 dict.

    Raises:
        KeyError: If model_name is not recognised.
    """
    schemas = _all_schemas()
    if model_name not in schemas:
        msg = f"Unknown model: {model_name!r}. Available: {sorted(schemas)}"
        raise KeyError(msg)
    return schemas[model_name]


def _migration_applied_def() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["version", "name", "duration_ms", "rows_affected"],
        "properties": {
            "version": {"type": "string"},
            "name": {"type": "string"},
            "duration_ms": {"type": "integer"},
            "rows_affected": {"type": "integer"},
        },
        "additionalProperties": False,
    }


def _all_schemas() -> dict[str, dict[str, Any]]:
    """Return a dict mapping model name → JSON Schema v7 dict."""
    applied_def = _migration_applied_def()
    applied_array = {"type": "array", "items": applied_def}

    return {
        "MigrationApplied": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "MigrationApplied",
            "description": "A single migration that was applied or rolled back.",
            **applied_def,
        },
        "MigrationInfo": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "MigrationInfo",
            "description": "Status of a single migration file.",
            "type": "object",
            "required": ["version", "name", "status", "applied_at"],
            "properties": {
                "version": {"type": "string"},
                "name": {"type": "string"},
                "status": {"type": "string", "enum": ["applied", "pending", "unknown"]},
                "applied_at": {
                    "anyOf": [{"type": "string", "format": "date-time"}, {"type": "null"}]
                },
            },
            "additionalProperties": False,
        },
        "StatusResult": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "StatusResult",
            "description": "Result of migrate status operation.",
            "type": "object",
            "required": ["tracking_table", "tracking_table_exists", "migrations", "summary"],
            "properties": {
                "tracking_table": {"type": "string"},
                "tracking_table_exists": {"type": "boolean"},
                "migrations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["version", "name", "status", "applied_at"],
                        "properties": {
                            "version": {"type": "string"},
                            "name": {"type": "string"},
                            "status": {"type": "string"},
                            "applied_at": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                        },
                    },
                },
                "summary": {
                    "type": "object",
                    "required": ["applied", "pending", "total"],
                    "properties": {
                        "applied": {"type": "integer"},
                        "pending": {"type": "integer"},
                        "total": {"type": "integer"},
                    },
                },
                "rebuild_recommended": {"type": "boolean"},
                "rebuild_reasons": {"type": "array", "items": {"type": "string"}},
            },
            "additionalProperties": False,
        },
        "BuildResult": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "BuildResult",
            "description": "Result of confiture build (schema build from DDL).",
            "type": "object",
            "required": ["success", "files_processed", "schema_size_bytes", "output_path"],
            "properties": {
                "success": {"type": "boolean"},
                "files_processed": {"type": "integer"},
                "schema_size_bytes": {"type": "integer"},
                "output_path": {"type": "string"},
                "hash": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "execution_time_ms": {"type": "integer"},
                "seed_files_applied": {"type": "integer"},
                "warnings": {"type": "array", "items": {"type": "string"}},
                "error": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            },
            "additionalProperties": False,
        },
        "MigrateUpResult": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "MigrateUpResult",
            "description": "Result of migrate up (apply pending migrations).",
            "type": "object",
            "required": [
                "success",
                "applied",
                "skipped",
                "errors",
                "total_duration_ms",
                "checksums_verified",
                "dry_run",
                "warnings",
            ],
            "properties": {
                "success": {"type": "boolean"},
                "applied": applied_array,
                "skipped": {"type": "array", "items": {"type": "string"}},
                "errors": {"type": "array", "items": {"type": "string"}},
                "total_duration_ms": {"type": "integer"},
                "checksums_verified": {"type": "boolean"},
                "dry_run": {"type": "boolean"},
                "warnings": {"type": "array", "items": {"type": "string"}},
            },
            "additionalProperties": False,
        },
        "MigrateDownResult": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "MigrateDownResult",
            "description": "Result of migrate down (roll back migrations).",
            "type": "object",
            "required": [
                "success",
                "rolled_back",
                "total_duration_ms",
                "checksums_verified",
                "warnings",
            ],
            "properties": {
                "success": {"type": "boolean"},
                "rolled_back": applied_array,
                "total_duration_ms": {"type": "integer"},
                "checksums_verified": {"type": "boolean"},
                "warnings": {"type": "array", "items": {"type": "string"}},
                "error": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            },
            "additionalProperties": False,
        },
        "MigrateReinitResult": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "MigrateReinitResult",
            "description": "Result of migrate reinit (reset tracking table).",
            "type": "object",
            "required": ["success", "deleted_count", "marked", "total_duration_ms", "dry_run"],
            "properties": {
                "success": {"type": "boolean"},
                "deleted_count": {"type": "integer"},
                "marked": applied_array,
                "total_duration_ms": {"type": "integer"},
                "dry_run": {"type": "boolean"},
                "warnings": {"type": "array", "items": {"type": "string"}},
                "error": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            },
            "additionalProperties": False,
        },
        "MigrateRebuildResult": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "MigrateRebuildResult",
            "description": "Result of migrate rebuild (rebuild from DDL).",
            "type": "object",
            "required": [
                "success",
                "schemas_dropped",
                "ddl_statements_executed",
                "marked",
                "total_duration_ms",
                "dry_run",
            ],
            "properties": {
                "success": {"type": "boolean"},
                "schemas_dropped": {"type": "array", "items": {"type": "string"}},
                "ddl_statements_executed": {"type": "integer"},
                "marked": applied_array,
                "total_duration_ms": {"type": "integer"},
                "dry_run": {"type": "boolean"},
                "warnings": {"type": "array", "items": {"type": "string"}},
                "error": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "seeds_applied": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                "verified": {"anyOf": [{"type": "boolean"}, {"type": "null"}]},
            },
            "additionalProperties": False,
        },
        "DriftItem": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "DriftItem",
            "description": "A single schema drift item.",
            "type": "object",
            "required": ["type", "severity", "object", "message"],
            "properties": {
                "type": {"type": "string"},
                "severity": {"type": "string", "enum": ["critical", "warning", "info"]},
                "object": {"type": "string"},
                "expected": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "actual": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "message": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "DriftReport": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "DriftReport",
            "description": "Report of schema drift detection between live DB and expected state.",
            "type": "object",
            "required": [
                "database_name",
                "expected_schema_source",
                "has_drift",
                "has_critical_drift",
                "critical_count",
                "warning_count",
                "info_count",
                "tables_checked",
                "columns_checked",
                "indexes_checked",
                "detection_time_ms",
                "drift_items",
            ],
            "properties": {
                "database_name": {"type": "string"},
                "expected_schema_source": {"type": "string"},
                "has_drift": {"type": "boolean"},
                "has_critical_drift": {"type": "boolean"},
                "critical_count": {"type": "integer"},
                "warning_count": {"type": "integer"},
                "info_count": {"type": "integer"},
                "tables_checked": {"type": "integer"},
                "columns_checked": {"type": "integer"},
                "indexes_checked": {"type": "integer"},
                "detection_time_ms": {"type": "integer"},
                "drift_items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string"},
                            "severity": {"type": "string"},
                            "object": {"type": "string"},
                            "expected": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                            "actual": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                            "message": {"type": "string"},
                        },
                    },
                },
            },
            "additionalProperties": False,
        },
        "IntrospectedColumn": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "IntrospectedColumn",
            "description": "A single column from schema introspection.",
            "type": "object",
            "required": ["name", "data_type", "is_nullable", "ordinal_position"],
            "properties": {
                "name": {"type": "string"},
                "data_type": {"type": "string"},
                "is_nullable": {"type": "boolean"},
                "ordinal_position": {"type": "integer"},
                "column_default": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "character_maximum_length": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                "is_primary_key": {"type": "boolean"},
            },
        },
        "IntrospectedTable": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "IntrospectedTable",
            "description": "A single table from schema introspection.",
            "type": "object",
            "required": ["name", "schema", "columns", "foreign_keys"],
            "properties": {
                "name": {"type": "string"},
                "schema": {"type": "string"},
                "columns": {"type": "array", "items": {}},
                "foreign_keys": {"type": "array", "items": {}},
                "row_count": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
            },
        },
        "IntrospectionResult": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "IntrospectionResult",
            "description": "Top-level result of schema introspection.",
            "type": "object",
            "required": ["database", "schema", "introspected_at", "tables"],
            "properties": {
                "database": {"type": "string"},
                "schema": {"type": "string"},
                "introspected_at": {"type": "string", "format": "date-time"},
                "tables": {"type": "array", "items": {}},
            },
        },
        "ApplyResult": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "ApplyResult",
            "description": "Result of seed apply operation.",
            "type": "object",
            "required": ["total", "succeeded", "failed", "failed_files", "success"],
            "properties": {
                "total": {"type": "integer"},
                "succeeded": {"type": "integer"},
                "failed": {"type": "integer"},
                "failed_files": {"type": "array", "items": {"type": "string"}},
                "success": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
        "VerifyResult": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "VerifyResult",
            "description": "Result of verifying a single migration's post-conditions.",
            "type": "object",
            "required": ["version", "name", "status"],
            "properties": {
                "version": {"type": "string"},
                "name": {"type": "string"},
                "status": {"type": "string", "enum": ["passed", "failed", "skipped", "error"]},
                "actual_value": {},
                "verify_file": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "error": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            },
        },
        "VerifyAllResult": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "VerifyAllResult",
            "description": "Result of verifying all applied migrations.",
            "type": "object",
            "required": [
                "verified_count",
                "failed_count",
                "skipped_count",
                "total_applied",
                "results",
            ],
            "properties": {
                "verified_count": {"type": "integer"},
                "failed_count": {"type": "integer"},
                "skipped_count": {"type": "integer"},
                "total_applied": {"type": "integer"},
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "version": {"type": "string"},
                            "name": {"type": "string"},
                            "status": {"type": "string"},
                            "actual_value": {},
                            "verify_file": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                            "error": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                        },
                    },
                },
            },
            "additionalProperties": False,
        },
    }


#: All registered model names.
SCHEMA_NAMES: list[str] = [
    "MigrationApplied",
    "MigrationInfo",
    "StatusResult",
    "BuildResult",
    "MigrateUpResult",
    "MigrateDownResult",
    "MigrateReinitResult",
    "MigrateRebuildResult",
    "DriftItem",
    "DriftReport",
    "IntrospectedColumn",
    "IntrospectedTable",
    "IntrospectionResult",
    "ApplyResult",
    "VerifyResult",
    "VerifyAllResult",
]

_FILENAME_MAP: dict[str, str] = {
    "MigrationApplied": "migration_applied.json",
    "MigrationInfo": "migration_info.json",
    "StatusResult": "status_result.json",
    "BuildResult": "build_result.json",
    "MigrateUpResult": "migrate_up_result.json",
    "MigrateDownResult": "migrate_down_result.json",
    "MigrateReinitResult": "migrate_reinit_result.json",
    "MigrateRebuildResult": "migrate_rebuild_result.json",
    "DriftItem": "drift_item.json",
    "DriftReport": "drift_report.json",
    "IntrospectedColumn": "introspected_column.json",
    "IntrospectedTable": "introspected_table.json",
    "IntrospectionResult": "introspection_result.json",
    "ApplyResult": "apply_result.json",
    "VerifyResult": "verify_result.json",
    "VerifyAllResult": "verify_all_result.json",
}


def export_all(output_dir: Path) -> list[Path]:
    """Generate all result model schemas and write to output_dir.

    Creates one ``*.json`` file per model. The directory is created
    if it does not already exist.

    Args:
        output_dir: Target directory for the JSON Schema files.

    Returns:
        List of paths to the written files.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    schemas = _all_schemas()
    written: list[Path] = []
    for model_name, schema in schemas.items():
        filename = _FILENAME_MAP[model_name]
        dest = output_dir / filename
        dest.write_text(json.dumps(schema, indent=2))
        written.append(dest)
    return written
