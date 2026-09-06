"""The JSON schemas confiture publishes, and the one place they come from.

``python/confiture/schemas/*.schema.json`` (shipped in the wheel, loadable with
:func:`load_schema`) is the source; ``docs/reference/json-schemas/`` is a
byte-identical copy written by ``scripts/gen_schemas.py`` and checked in CI.
:data:`MODEL_SCHEMAS` names the result model behind each schema whose payload is
that model's ``to_dict()``; a test populates every such model and validates it.
:data:`CLI_BUILT_SCHEMAS` are the payloads a command assembles itself.
"""

from __future__ import annotations

import filecmp
import importlib
import json
from importlib.resources import as_file, files
from pathlib import Path
from typing import Any

# model name -> (module, class); the payload is ``instance.to_dict()``
_MODELS: dict[str, tuple[str, str]] = {
    "MigrateUpResult": ("confiture.models.results", "MigrateUpResult"),
    "DownToResult": ("confiture.models.results", "DownToResult"),
    "VerifyAllResult": ("confiture.models.results", "VerifyAllResult"),
    "CurrentRevision": ("confiture.models.results", "CurrentRevision"),
    "PreflightIssue": ("confiture.models.results", "PreflightIssue"),
    "BuildResult": ("confiture.models.results", "BuildResult"),
    "SyncResult": ("confiture.models.results", "SyncResult"),
    "DriftReport": ("confiture.core.drift", "DriftReport"),
    "IntrospectionResult": ("confiture.models.introspection", "IntrospectionResult"),
    "LintReport": ("confiture.models.lint", "LintReport"),
}

MODEL_SCHEMAS: dict[str, str] = {
    "MigrateUpResult": "migrate-up.schema.json",
    "DownToResult": "migrate-down-to.schema.json",
    "VerifyAllResult": "migrate-verify.schema.json",
    "CurrentRevision": "migrate-current.schema.json",
    "PreflightIssue": "issue-object.schema.json",
    "BuildResult": "build.schema.json",
    "SyncResult": "sync.schema.json",
    "DriftReport": "drift.schema.json",
    "IntrospectionResult": "introspect.schema.json",
    "LintReport": "lint.schema.json",
}

# Payloads a command assembles from several sources; validated by the CLI tests.
CLI_BUILT_SCHEMAS: tuple[str, ...] = (
    "drift-check-acls.schema.json",
    "error-envelope.schema.json",
    "lint-list-rules.schema.json",
    "migrate-fix.schema.json",
    "migrate-introspect.schema.json",
    "migrate-preflight-against.schema.json",
    "migrate-preflight.schema.json",
    "migrate-status.schema.json",
    "migrate-validate-check-acl-coverage.schema.json",
    "migrate-validate-check-function-uniqueness.schema.json",
    "migrate-validate-composed.schema.json",
    "migrate-validate-grant.schema.json",
    "migrate-validate-idempotent.schema.json",
    "migrate-validate-list-patterns.schema.json",
    "validate-config.schema.json",
    "verify-checksums.schema.json",
)

SCHEMA_NAMES: tuple[str, ...] = tuple(MODEL_SCHEMAS)


def schema_files() -> list[str]:
    """Every packaged schema file name, shared ``_*`` sub-schemas included."""
    return sorted(p.name for p in files("confiture.schemas").iterdir() if p.name.endswith(".json"))


def load_schema(filename: str) -> dict[str, Any]:
    """A packaged schema by file name (``migrate-up.schema.json``)."""
    return json.loads(files("confiture.schemas").joinpath(filename).read_text(encoding="utf-8"))


def generate_schema(model_name: str) -> dict[str, Any]:
    """The schema of a result model's ``to_dict()`` payload.

    Raises:
        KeyError: ``model_name`` is not one of :data:`SCHEMA_NAMES`.
    """
    if model_name not in MODEL_SCHEMAS:
        msg = f"Unknown model: {model_name!r}. Available: {sorted(MODEL_SCHEMAS)}"
        raise KeyError(msg)
    return load_schema(MODEL_SCHEMAS[model_name])


def model_class(model_name: str) -> type:
    module, attr = _MODELS[model_name]
    return getattr(importlib.import_module(module), attr)


def payload_of(instance: Any) -> dict[str, Any]:
    """What the command prints for this model: its ``to_dict()``."""
    return instance.to_dict()


def export_all(output_dir: Path) -> list[Path]:
    """Copy every packaged schema into ``output_dir`` (created if needed)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name in schema_files():
        dest = output_dir / name
        dest.write_text(files("confiture.schemas").joinpath(name).read_text(encoding="utf-8"))
        written.append(dest)
    return written


def docs_out_of_sync(docs_dir: Path) -> list[str]:
    """Names that differ between the packaged source and ``docs_dir``, or exist on one side only."""
    source = set(schema_files())
    docs = {p.name for p in docs_dir.glob("*.json")} if docs_dir.exists() else set()
    out = sorted(source ^ docs)
    for name in sorted(source & docs):
        with as_file(files("confiture.schemas").joinpath(name)) as src_path:
            if not filecmp.cmp(src_path, docs_dir / name, shallow=False):
                out.append(name)
    return out


def sync_docs(docs_dir: Path) -> list[Path]:
    """Make ``docs_dir`` a byte-identical copy of the packaged schemas."""
    docs_dir.mkdir(parents=True, exist_ok=True)
    keep = set(schema_files())
    for stale in docs_dir.glob("*.json"):
        if stale.name not in keep:
            stale.unlink()
    return export_all(docs_dir)


__all__ = [
    "CLI_BUILT_SCHEMAS",
    "MODEL_SCHEMAS",
    "SCHEMA_NAMES",
    "docs_out_of_sync",
    "export_all",
    "generate_schema",
    "load_schema",
    "model_class",
    "payload_of",
    "schema_files",
    "sync_docs",
]
