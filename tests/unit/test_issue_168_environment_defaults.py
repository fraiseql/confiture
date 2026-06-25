"""Issue #168 (follow-up) — ``Environment`` defaults build-only fields.

The 0.33.0 fix made ``Migrator.from_config(path)`` accept a minimal
``database_url``-only config, but it injected the defaults in the factory.  A
Python-API consumer that builds the model directly —
``Environment.model_validate({"database_url": ...})`` (e.g. fraisier, to inject
a ``database_url`` override) — still hit the required-field wall.

``name`` and ``include_dirs`` are build-only and never read on the migrate
path, so they now default on the model itself.  Build safety is unchanged:
``Environment.load`` injects ``name`` and guards ``include_dirs``, and
``SchemaBuilder`` independently rejects an empty ``include_dirs``.
"""

from __future__ import annotations

import pytest

from confiture.config.environment import Environment


class TestModelDefaults:
    def test_model_validate_accepts_database_url_only(self):
        env = Environment.model_validate({"database_url": "postgresql://localhost/db"})
        assert env.database_url == "postgresql://localhost/db"
        assert env.name == ""
        assert env.include_dirs == []

    def test_model_validate_still_requires_database_url(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            Environment.model_validate({"name": "x"})

    def test_explicit_fields_still_honoured(self):
        env = Environment.model_validate(
            {
                "name": "prod",
                "database_url": "postgresql://localhost/db",
                "include_dirs": ["db/schema"],
            }
        )
        assert env.name == "prod"
        assert env.include_dirs == ["db/schema"]

    def test_database_url_format_still_validated(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="Invalid database_url"):
            Environment.model_validate({"database_url": "not-a-url"})


class TestBuildSafetyPreserved:
    """Defaulting the fields must NOT let a build silently produce an empty
    schema — the builder guards an empty ``include_dirs`` itself."""

    def test_builder_rejects_empty_include_dirs(self):
        from confiture.core.builder import SchemaBuilder
        from confiture.exceptions import SchemaError

        env = Environment.model_validate({"database_url": "postgresql://localhost/db"})
        with pytest.raises(SchemaError, match="include_dirs"):
            SchemaBuilder(env)
