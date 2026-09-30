"""The facts true in every environment of a project: ``db/project.yaml``.

An environment file says how to reach one database. What the schema *is* — which
column scopes a row to a tenant, which table holds the tenants, which schemas are
shared reference data — is the same in every environment, so it is written once
here. The file is optional: without it, or with nothing in it, confiture assumes
nothing about tenants. A malformed file is refused as a malformed environment file
is, ``CONFIG_001`` (#468).
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from confiture.config.environment import _read_config_yaml
from confiture.core import sql_lexer
from confiture.exceptions import ConfigurationError

#: Where the project file lives, relative to the project directory.
PROJECT_FILE = Path("db") / "project.yaml"


class TenancyConfig(BaseModel):
    """The project is tenant-scoped, and how.

    Declaring it turns the ``tenant`` lint family on for every run.

    Attributes:
        discriminator: The column every tenant-scoped relation carries, ``NOT NULL``.
        root: The table of tenants, schema-qualified (``management.tb_organization``,
            or ``"my.schema".tb_org`` quoted as SQL quotes it): its key is the
            tenant id, so it carries no discriminator of its own.
        global_schemas: Schemas holding shared reference data — every relation in
            them is global, never tenant-scoped.
    """

    model_config = ConfigDict(extra="forbid")

    discriminator: str = "tenant_id"
    root: str | None = None
    global_schemas: list[str] = []

    @field_validator("discriminator")
    @classmethod
    def _discriminator_is_a_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("tenancy.discriminator must name a column, got an empty name")
        return value

    @field_validator("root")
    @classmethod
    def _root_is_qualified(cls, value: str | None) -> str | None:
        """Read as SQL reads a name, so a dot inside a quoted part is not counted (#468)."""
        if value is None:
            return value
        match sql_lexer.name_parts(value):
            case [_schema, _table]:
                return value
            case _:
                raise ValueError(
                    f"tenancy.root must be schema-qualified (schema.table), got {value!r}"
                )


class SquashConfig(BaseModel):
    """How far back ``migrate squash`` may cut, and which environments it asks first.

    Attributes:
        min_age_days: The cut must have been applied at least this many days ago in
            every environment the squash asks: a restore from a backup taken before
            that replays the history the baseline replaced. With no environment
            asked, the age of a timestamp version is its own date.
        skip_environments: ``db/environments/<name>.yaml`` files the squash does not
            connect to, because they cannot be reached from where it runs. Each is
            named in its output; ``migrate up`` still refuses a baseline there when
            the ledger holds part of its history.
    """

    model_config = ConfigDict(extra="forbid")

    min_age_days: int = Field(default=90, ge=0)
    skip_environments: list[str] = []


class ProjectConfig(BaseModel):
    """``db/project.yaml``: facts about the schema, the same in every environment.

    Attributes:
        tenancy: Declares the project tenant-scoped; absent, no tenant rule runs.
        squash: What ``migrate squash`` checks before it cuts; absent, its defaults.
    """

    model_config = ConfigDict(extra="forbid")

    tenancy: TenancyConfig | None = None
    squash: SquashConfig | None = None

    def declared_blocks(self) -> frozenset[str]:
        """The blocks this file declares — what ``LintRule.enabled_by`` names."""
        return frozenset(
            name for name in type(self).model_fields if getattr(self, name) is not None
        )


def load_project_config(project_dir: Path = Path()) -> ProjectConfig:
    """The project's ``db/project.yaml``, or an empty :class:`ProjectConfig` when absent.

    An empty (or comment-only) file declares no block. A block written with no
    body (``tenancy:`` alone) is declared, with its defaults: the key is there,
    and YAML reading it as ``null`` does not make it absent.

    Raises:
        ConfigurationError: ``CONFIG_001``, as for an environment file — the file
            is not a mapping, names a key confiture does not know, or a value is
            malformed. A typo is never an empty success.
    """
    path = Path(project_dir) / PROJECT_FILE
    if not path.is_file():
        return ProjectConfig()
    data = _read_config_yaml(path, allow_empty=True)
    data |= {block: {} for block in ProjectConfig.model_fields if data.get(block, ()) is None}
    try:
        return ProjectConfig.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
        raise ConfigurationError(
            f"Invalid {PROJECT_FILE.as_posix()}: {problems}",
            resolution_hint="See docs/reference/configuration.md#dbprojectyaml",
        ) from exc
