"""The facts true in every environment of a project: ``db/project.yaml``.

An environment file says how to reach one database. What the schema *is* — which
column scopes a row to a tenant, which table holds the tenants, which schemas are
shared reference data — is the same in every environment, so it is written once
here. The file is optional: without it confiture assumes nothing about tenants.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from confiture.config.environment import _read_config_yaml
from confiture.exceptions import ConfigurationError

#: Where the project file lives, relative to the project directory.
PROJECT_FILE = Path("db") / "project.yaml"


class TenancyConfig(BaseModel):
    """The project is tenant-scoped, and how.

    Declaring it turns the ``tenant`` lint family on for every run.

    Attributes:
        discriminator: The column every tenant-scoped relation carries, ``NOT NULL``.
        root: The table of tenants, schema-qualified (``management.tb_organization``):
            its key is the tenant id, so it carries no discriminator of its own.
        global_schemas: Schemas holding shared reference data — every relation in
            them is global, never tenant-scoped.
    """

    model_config = ConfigDict(extra="forbid")

    discriminator: str = "tenant_id"
    root: str | None = None
    global_schemas: list[str] = []

    @field_validator("root")
    @classmethod
    def _root_is_qualified(cls, value: str | None) -> str | None:
        if value is not None and value.count(".") != 1:
            raise ValueError(f"tenancy.root must be schema-qualified (schema.table), got {value!r}")
        return value


class ProjectConfig(BaseModel):
    """``db/project.yaml``: facts about the schema, the same in every environment.

    Attributes:
        tenancy: Declares the project tenant-scoped; absent, no tenant rule runs.
    """

    model_config = ConfigDict(extra="forbid")

    tenancy: TenancyConfig | None = None

    def declared_blocks(self) -> frozenset[str]:
        """The blocks this file declares — what ``LintRule.enabled_by`` names."""
        return frozenset(
            name for name in type(self).model_fields if getattr(self, name) is not None
        )


def load_project_config(project_dir: Path = Path()) -> ProjectConfig:
    """The project's ``db/project.yaml``, or an empty :class:`ProjectConfig` when absent.

    Raises:
        ConfigurationError: The file is not a mapping, names a key confiture does
            not know, or a value is malformed — a typo is never an empty success.
    """
    path = Path(project_dir) / PROJECT_FILE
    if not path.is_file():
        return ProjectConfig()
    data = _read_config_yaml(path)
    try:
        return ProjectConfig.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
        raise ConfigurationError(
            f"Invalid {PROJECT_FILE.as_posix()}: {problems}",
            error_code="CONFIG_010",
            resolution_hint="See docs/reference/configuration.md#dbprojectyaml",
        ) from exc
