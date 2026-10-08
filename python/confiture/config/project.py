"""The facts true in every environment of a project: ``db/project.yaml``.

An environment file says how to reach one database. What the schema *is* — which
column scopes a row to a tenant, which table holds the tenants, which schemas are
shared reference data — is the same in every environment, so it is written once
here. The file is optional: without it, or with nothing in it, confiture assumes
nothing about tenants. A malformed file is refused as a malformed environment file
is, ``CONFIG_001`` (#468).
"""

from pathlib import Path
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

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


class SoftDeleteConfig(BaseModel):
    """The project soft-deletes, and which column says a row is deleted.

    Declaring it turns the ``softdel`` lint family on for every run.

    Attributes:
        column: The tombstone column: a row whose value in it is not ``NULL`` is
            deleted.
        tables: Which tables soft-delete. ``present``: every table that has the
            column. ``written``: those the tree tombstones — a statement or a routine
            body writes a value other than ``NULL`` to the column (#640). A tree that
            puts the column on every table, reference tables included, wants
            ``written``.
        exclude: Tables that never soft-delete whatever *tables* says, each
            ``schema.table`` or a bare name (any schema).
    """

    model_config = ConfigDict(extra="forbid")

    column: str = "deleted_at"
    tables: Literal["present", "written"] = "present"
    exclude: list[str] = []

    @field_validator("exclude")
    @classmethod
    def _exclude_names_tables(cls, value: list[str]) -> list[str]:
        """Each entry read as SQL reads a name: one part, or a schema and a table."""
        for entry in value:
            if len(sql_lexer.name_parts(entry) or ()) not in (1, 2):
                raise ValueError(
                    f"soft_delete.exclude names a table as schema.table or table, got {entry!r}"
                )
        return value

    @field_validator("column")
    @classmethod
    def _column_is_a_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("soft_delete.column must name a column, got an empty name")
        return value


class TranslationsConfig(BaseModel):
    """The project translates reference data: one table per translated entity (#657).

    Declaring it turns ``i18n_001`` on for every run, and gives the live coverage
    check (:mod:`confiture.core.translations`) its tables and locales.

    Attributes:
        tables: The translation tables, as globs over table names: ``tl_*`` matches
            a name in any schema, ``catalog.tl_*`` one in ``catalog``. One glob, or
            a list.
        locale_fk: The column of each translation table that references the locale.
        locale_table: The table of locales, ``schema.table`` or a bare name.
        locale_column: The column of *locale_table* that holds a locale's code
            (``en-US``), which *required* names.
        required: The locale codes every entity row must have a translation in.
        required_query: A query returning those codes, one text column, run by the
            live check instead of *required* (the two are exclusive). It is the
            project's own SQL, run as written.
    """

    model_config = ConfigDict(extra="forbid")

    tables: list[str] = Field(min_length=1)
    locale_fk: str = "fk_locale"
    locale_table: str
    locale_column: str = "code"
    required: list[str] = []
    required_query: str | None = None

    @field_validator("tables", mode="before")
    @classmethod
    def _one_glob_is_a_list(cls, value: object) -> object:
        return [value] if isinstance(value, str) else value

    @field_validator("tables")
    @classmethod
    def _globs_are_names(cls, value: list[str]) -> list[str]:
        for glob in value:
            if not glob.strip() or glob.count(".") > 1:
                raise ValueError(
                    f"translations.tables holds globs over schema.table or table, got {glob!r}"
                )
        return value

    @field_validator("locale_table")
    @classmethod
    def _locale_table_is_a_name(cls, value: str) -> str:
        if len(sql_lexer.name_parts(value) or ()) not in (1, 2):
            raise ValueError(
                f"translations.locale_table names a table as schema.table or table, got {value!r}"
            )
        return value

    @field_validator("locale_fk", "locale_column")
    @classmethod
    def _column_is_a_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("a translations column must be named, got an empty name")
        return value

    @model_validator(mode="after")
    def _one_source_of_locales(self) -> Self:
        if self.required and self.required_query is not None:
            raise ValueError(
                "translations.required_query and translations.required are exclusive: "
                "name the locales, or the query that returns them"
            )
        return self


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
        soft_delete: Declares the tombstone column of the tables that soft-delete;
            absent, no ``softdel`` rule runs.
        squash: What ``migrate squash`` checks before it cuts; absent, its defaults.
        translations: Declares the translation tables; absent, no ``i18n`` rule runs.
    """

    model_config = ConfigDict(extra="forbid")

    tenancy: TenancyConfig | None = None
    soft_delete: SoftDeleteConfig | None = None
    squash: SquashConfig | None = None
    translations: TranslationsConfig | None = None

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
