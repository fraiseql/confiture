"""Configuration models for Confiture.

This module defines the schema for Confiture YAML configuration files.

Configuration Structure
=======================

::

    name: local
    database_url: postgresql://localhost/myapp_local

    include_dirs:
      - db/schema

    migration:
      tracking_table: public.tb_confiture

    build:
      linting:
        enabled: true
        strict: false
      output_path: db/generated/schema.sql

    seed:
      execution_mode: concatenate  # or "sequential"

    rebuild:
      threshold: 5
      backup: true

    locking:
      enabled: true
      timeout_ms: 30000

Environment Variables
====================

All ``database_url`` values support ``${VAR}`` substitution::

    database_url: ${DATABASE_URL}

File Discovery
==============

``Migrator.from_config()`` accepts:

1. Path: ``"db/environments/prod.yaml"``
2. ``Environment`` instance (pre-loaded config)
"""

import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from confiture.config._env_vars import expand_env_vars
from confiture.exceptions import ConfigurationError

# Privileges that PostgreSQL's GRANT statement allows on tables.  Sequences,
# functions, schemas, etc. use a different vocabulary and are out of scope
# for the ACL coverage feature (see #120 README "Out of scope").
_TABLE_PRIVILEGES: tuple[str, ...] = (
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "TRUNCATE",
    "REFERENCES",
    "TRIGGER",
)
_TablePrivilege = Literal[
    "SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"
]

# SSH parameter validation patterns
_VALID_SSH_HOST_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9\-._]*$")
_VALID_SSH_USER_RE = re.compile(r"^[a-zA-Z0-9_\-\.@]+$")


class CommentValidationConfig(BaseModel):
    """Comment validation configuration for schema builder.

    Detects unclosed block comments in SQL files that would corrupt
    concatenated schemas.

    Attributes:
        enabled: Whether to validate comments (default: True)
        fail_on_unclosed_blocks: Fail if unclosed block comments found (default: True)
        fail_on_spillover: Fail if file ends inside unclosed comment (default: True)
    """

    enabled: bool = True
    fail_on_unclosed_blocks: bool = True
    fail_on_spillover: bool = True


class SeparatorConfig(BaseModel):
    """File separator configuration for schema builder.

    Controls the style of separators between concatenated SQL files.

    Attributes:
        style: Separator style (block_comment, line_comment, mysql, custom)
        custom_template: Custom template for separators (only used if style=custom)
    """

    style: str = "block_comment"  # Options: block_comment, line_comment, mysql, custom
    custom_template: str | None = None


class BuildLintConfig(BaseModel):
    """SQL linting configuration for schema builder.

    Runs schema validation during build to catch issues early.

    Attributes:
        enabled: Whether to lint schema (default: False - disabled by default)
        fail_on_error: Fail build if linting errors found (default: True)
        fail_on_warning: Fail build if linting warnings found (default: False)
        rules: List of linting rules to apply
    """

    enabled: bool = False  # Default: disabled (opt-in)
    fail_on_error: bool = True
    fail_on_warning: bool = False
    rules: list[str] = Field(
        default_factory=lambda: [
            "naming_convention",
            "primary_key",
            "documentation",
            "missing_index",
            "security",
        ]
    )


class BuildConfig(BaseModel):
    """Build configuration options."""

    sort_mode: str = "alphabetical"  # Options: alphabetical, hex
    two_pass: bool = False  # Two-pass FK emission (issue #94)
    validate_comments: CommentValidationConfig = Field(default_factory=CommentValidationConfig)
    separators: SeparatorConfig = Field(default_factory=SeparatorConfig)
    lint: BuildLintConfig = Field(default_factory=BuildLintConfig)


class SeedProfile(BaseModel):
    """A named subset of seed files, selected by glob patterns.

    Patterns match seed *filenames* (seed discovery is top-level, non-recursive).
    Selection is include-then-exclude: an empty ``include`` starts from all
    files; ``exclude`` then removes matches. Lets CI apply a lean test seed
    (e.g. excluding large ETL-statistics partitions) for faster, higher-parallel
    test databases.

    Attributes:
        include: Globs a file must match to be included (empty = all files).
        exclude: Globs that remove an otherwise-included file.
    """

    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)


class SeedConfig(BaseModel):
    """Seed data application configuration.

    Controls how seed files are executed (concatenated vs sequential).
    Sequential mode executes each file independently within its own savepoint,
    avoiding PostgreSQL parser limits for large files (650+ rows).

    Attributes:
        execution_mode: Execution strategy ("concatenate" | "sequential")
        continue_on_error: Continue applying files if one fails (default: False)
        transaction_mode: Transaction isolation ("savepoint" | "transaction")
        profiles: Named seed subsets (see :class:`SeedProfile`). Absent ⇒ today's
            apply-all behaviour is unchanged.
    """

    execution_mode: str = "concatenate"  # "concatenate" | "sequential"
    continue_on_error: bool = False
    transaction_mode: str = "savepoint"  # "savepoint" | "transaction"
    profiles: dict[str, SeedProfile] = Field(default_factory=dict)

    def get_profile(self, name: str) -> SeedProfile:
        """Return the named seed profile, or raise a clear configuration error.

        Args:
            name: Profile name to resolve.

        Returns:
            The matching :class:`SeedProfile`.

        Raises:
            ConfigurationError: If no profile by that name is defined.
        """
        try:
            return self.profiles[name]
        except KeyError:
            defined = ", ".join(sorted(self.profiles)) or "(none defined)"
            raise ConfigurationError(
                f"Unknown seed profile: {name!r}. Defined profiles: {defined}.",
                error_code="CONFIG_010",
                resolution_hint="Define it under seed.profiles.<name> in the environment "
                "config, or omit --profile/--seed-profile.",
            ) from None


class LockingConfig(BaseModel):
    """Distributed locking configuration.

    Controls how Confiture acquires locks to prevent concurrent migrations
    in multi-pod Kubernetes deployments.

    Attributes:
        enabled: Whether locking is enabled (default: True)
        timeout_ms: Lock acquisition timeout in milliseconds (default: 30000)
    """

    enabled: bool = True
    timeout_ms: int = 30000  # 30 seconds default


class MigrationGeneratorConfig(BaseModel):
    """Config for one named external migration generator.

    Attributes:
        command: Shell command template with {from}, {to}, {output} placeholders
        description: Human-readable label for the generator
    """

    command: str
    description: str = ""

    @field_validator("command")
    @classmethod
    def validate_command(cls, v: str) -> str:
        """Validate command is non-empty and contains all required placeholders."""
        if not v:
            raise ValueError("command must not be empty")
        missing = [p for p in ("{from}", "{to}", "{output}") if p not in v]
        if missing:
            raise ValueError(f"command is missing required placeholder(s): {', '.join(missing)}")
        return v


class MigrationConfig(BaseModel):
    """Migration configuration options.

    Attributes:
        strict_mode: Whether to fail on warnings/notices (default: False)
        locking: Distributed locking configuration
        view_helpers: View helper installation mode ("auto", "manual", "off")
        migration_generators: Named external generator commands
        snapshot_history: Write schema snapshot alongside each generated migration (default: True)
        snapshots_dir: Directory for schema history snapshots (default: db/schema_history)
        live_snapshot: Use live-snapshot mode (temp DB + pg_dump) by default (default: False)
        tracking_table: Name of the confiture tracking table, optionally schema-qualified
            (e.g. ``public.tb_confiture``). Defaults to ``tb_confiture``.
    """

    strict_mode: bool = False  # Whether to fail on warnings/notices
    locking: LockingConfig = Field(default_factory=LockingConfig)
    view_helpers: Literal["auto", "manual", "off"] = "auto"
    migration_generators: dict[str, MigrationGeneratorConfig] = Field(default_factory=dict)
    snapshot_history: bool = True
    snapshots_dir: str = "db/schema_history"
    live_snapshot: bool = False
    tracking_table: str = "tb_confiture"
    rebuild_threshold: int = 5
    grant_dir: str = "db/7_grant"
    # Issue #139 — replica-aware forward-compatibility lint. When True, unsafe
    # operations are downgraded from errors to warnings even if replicas are
    # declared. RISK: you accept that a single-step DDL change may surface
    # errors on read replicas during the replication-lag window.
    allow_unsafe_under_replication: bool = False


class InfrastructureConfig(BaseModel):
    """Deployment-topology declarations confiture reads (issue #139).

    ``replicas`` lists declared read-replica identifiers. Its mere presence
    (non-empty) makes the replica-safety lint error rather than warn — the
    project is telling confiture it runs under replication. The deploy tool
    (fraisier) owns the live topology; confiture only reads this declaration.
    """

    replicas: list[str] = Field(default_factory=list)


class SshTunnelConfig(BaseModel):
    """SSH tunnel configuration for remote database access.

    When set, confiture opens an SSH tunnel before connecting to the database.
    The tunnel is torn down automatically after the operation completes.

    This is the standard configuration for self-hosted production databases
    accessed via ``ssh user@host psql -d dbname``.

    Attributes:
        host: SSH server hostname (e.g. "printoptim.io")
        user: SSH username. Defaults to the current OS user if omitted.
        remote_host: PostgreSQL host on the remote side (default: localhost).
            Ignored when ``remote_socket`` is set.
        remote_port: PostgreSQL port on the remote side (default: 5432).
            Ignored when ``remote_socket`` is set.
        remote_socket: Unix domain socket path on the remote side
            (e.g. ``/var/run/postgresql/.s.PGSQL.5432``).  When set, the
            tunnel forwards a local TCP port to this socket instead of a
            TCP ``remote_host:remote_port`` pair.  Requires OpenSSH ≥ 6.7.
        local_port: Local port to bind. 0 = pick a free port automatically (default: 0)
        identity_file: Path to SSH private key. If omitted, uses ssh-agent / default key.
        timeout_s: Seconds to wait for the tunnel to open (default: 10)

    Example config (TCP remote port)::

        ssh_tunnel:
          host: printoptim.io
          user: lionel
          remote_port: 5432
          local_port: 0          # auto-assign

    Example config (Unix socket on remote)::

        ssh_tunnel:
          host: printoptim.io
          user: lionel
          remote_socket: /var/run/postgresql/.s.PGSQL.5432
          local_port: 0          # auto-assign
    """

    host: str
    user: str | None = None
    remote_host: str = "localhost"

    @field_validator("host")
    @classmethod
    def validate_host(cls, v: str) -> str:
        """Reject hostnames that contain shell metacharacters."""
        if not _VALID_SSH_HOST_RE.match(v):
            raise ValueError(
                f"Invalid SSH hostname: {v!r}. "
                "Use only letters, digits, hyphens, dots, and underscores."
            )
        return v

    @field_validator("user")
    @classmethod
    def validate_user(cls, v: str | None) -> str | None:
        """Reject usernames that contain shell metacharacters."""
        if v is not None and not _VALID_SSH_USER_RE.match(v):
            raise ValueError(
                f"Invalid SSH username: {v!r}. "
                "Use only letters, digits, hyphens, underscores, dots, or @."
            )
        return v

    remote_port: int = 5432
    remote_socket: str | None = None
    local_port: int = 0
    identity_file: str | None = None
    timeout_s: int = 10


class PgGitConfig(BaseModel):
    """pgGit integration configuration.

    pgGit provides Git-like version control for PostgreSQL schemas.
    This is intended for DEVELOPMENT and STAGING databases only.
    Do NOT enable pgGit on production databases.

    Attributes:
        enabled: Whether pgGit integration is enabled (default: False)
        auto_init: Automatically initialize pgGit if extension exists but not initialized
        default_branch: Default branch name for new repositories (default: "main")
        auto_commit: Automatically commit schema changes after migrations
        commit_message_template: Template for auto-commit messages
        require_branch: Require being on a branch before making schema changes
        protected_branches: Branches that cannot be deleted or force-pushed
    """

    enabled: bool = False
    auto_init: bool = True
    default_branch: str = "main"
    auto_commit: bool = False
    commit_message_template: str = "Migration: {migration_name}"
    require_branch: bool = False
    protected_branches: list[str] = Field(default_factory=lambda: ["main", "master"])


class DirectoryConfig(BaseModel):
    """Directory configuration with pattern matching."""

    path: str
    recursive: bool = True
    include: list[str] = Field(default_factory=lambda: ["**/*.sql"])
    exclude: list[str] = Field(default_factory=list)
    auto_discover: bool = True
    order: int = 0


class DatabaseConfig(BaseModel):
    """Database connection configuration.

    Can be initialized from a connection URL or individual parameters.
    """

    host: str = "localhost"
    port: int = 5432
    database: str = "postgres"
    user: str = "postgres"
    password: str = ""

    @classmethod
    def from_url(cls, url: str) -> "DatabaseConfig":
        """Parse database configuration from PostgreSQL URL.

        Args:
            url: PostgreSQL connection URL (postgresql://user:pass@host:port/dbname)

        Returns:
            DatabaseConfig instance

        Example:
            >>> config = DatabaseConfig.from_url("postgresql://user:pass@localhost:5432/mydb")
            >>> config.host
            'localhost'
        """
        import re

        # Parse URL: postgresql://user:pass@host:port/dbname
        pattern = r"(?:postgresql|postgres)://(?:([^:]+):([^@]+)@)?([^:/]+)(?::(\d+))?/(.+)"
        match = re.match(pattern, url)

        if not match:
            raise ValueError(f"Invalid PostgreSQL URL: {url}")

        user, password, host, port, database = match.groups()

        return cls(
            host=host or "localhost",
            port=int(port) if port else 5432,
            database=database,
            user=user or "postgres",
            password=password or "",
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for use with create_connection."""
        return {
            "database": {
                "host": self.host,
                "port": self.port,
                "database": self.database,
                "user": self.user,
                "password": self.password,
            }
        }


class AclGrant(BaseModel):
    """A single role's expected privileges on a table.

    Privileges are normalized uppercase regardless of YAML casing; the
    PostgreSQL grant vocabulary is case-insensitive but mixing styles in
    config is noisy, so we pick one.
    """

    model_config = ConfigDict(extra="forbid")

    role: str
    privileges: list[_TablePrivilege]

    @field_validator("privileges", mode="before")
    @classmethod
    def _normalize_privileges(cls, value: Any) -> Any:
        """Uppercase incoming privilege names so YAML can be case-insensitive."""
        if isinstance(value, list):
            return [v.upper() if isinstance(v, str) else v for v in value]
        return value


class AclTableExpectation(BaseModel):
    """One ``acls:`` entry — a schema-scoped set of expected table grants.

    Named ``AclTableExpectation`` to leave namespace open for future
    column-level (``AclColumnExpectation``) and sequence-level
    (``AclSequenceExpectation``) variants.  The legacy ``AclExpectation``
    alias remains importable for back-compat through the 0.12.x line.

    ``apply_to`` is either the literal string ``"ALL_TABLES"`` (every base
    table in the schema except those matching ``ignore``) or a list of
    ``fnmatch`` glob patterns evaluated against the bare relname.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    # ``schema`` shadows ``BaseModel.schema`` (the JSON-schema accessor) so we
    # store it on the attribute ``schema_`` and let YAML use the natural key.
    schema_: str = Field(alias="schema")
    apply_to: Literal["ALL_TABLES"] | list[str]
    ignore: list[str] = Field(default_factory=list)
    grants: list[AclGrant]


# Back-compat alias.  Kept as a plain assignment (not a subclass) so
# ``isinstance(x, AclExpectation)`` and ``isinstance(x, AclTableExpectation)``
# behave identically — they're the same class.
AclExpectation = AclTableExpectation


# Postgres ``pg_class.relkind`` values in scope for ownership coverage
# (table, sequence, view, materialized view).  Functions and procedures
# have separate ownership semantics — not in scope for v1.
_OWNERSHIP_RELKINDS: frozenset[str] = frozenset({"r", "S", "v", "m"})

# Strict regex for a Postgres role identifier: unquoted ``[a-z_][a-z0-9_]*``
# (matches the unquoted-identifier rule), or any double-quoted form
# ``"..."`` permitting whitespace and mixed case.
_ROLE_IDENT_RE = re.compile(r'^("[^"]+"|[a-z_][a-z0-9_]*)$')


class OwnershipApplyTo(BaseModel):
    """One schema-scoped entry in the ``ownership.apply_to`` list (issue #124).

    ``relkinds`` accepts only ``r`` (regular table), ``S`` (sequence),
    ``v`` (view), or ``m`` (materialized view).  Default covers all four.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_: str = Field(alias="schema")
    relkinds: list[str] = Field(default_factory=lambda: ["r", "S", "v", "m"])

    @field_validator("relkinds")
    @classmethod
    def _validate_relkinds(cls, v: list[str]) -> list[str]:
        bad = set(v) - _OWNERSHIP_RELKINDS
        if bad:
            raise ValueError(
                f"Invalid relkinds: {sorted(bad)}. "
                f"Must be a subset of {sorted(_OWNERSHIP_RELKINDS)}."
            )
        return v


class FunctionCoverage(BaseModel):
    """The ``function_coverage:`` block in environment YAML (issue #136).

    Enables the ``func_001`` lint rule that walks the configured DDL
    directories and flags any fully-qualified function/procedure
    signature defined in more than one ``.sql`` file.

    Opt-in by default (``enabled=False``) to avoid surprising existing
    projects with pre-existing duplicates.  Documented upgrade path:
    enable, run, fix or opt out per call site with
    ``-- confiture:func-allow-duplicate``, then leave on.

    Attributes:
        enabled: Master switch.  When False the rule is a no-op even if
            scope-matching files contain duplicates.
        apply_to: Schema-name patterns (``fnmatch``-style) that scope
            the check.  ``["*"]`` covers every schema; ``["public",
            "stat_etl"]`` covers only those two.
        ignore: Object-path globs (``schema.name``) that opt specific
            callables out of detection regardless of how many files
            define them.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    apply_to: list[str] = Field(default_factory=lambda: ["*"])
    ignore: list[str] = Field(default_factory=list)


class SecurityLinting(BaseModel):
    """The ``security_lint:`` block in environment YAML (issue #161).

    Enables the ``sec_002`` lint rule that flags ``SECURITY DEFINER``
    functions and procedures that do not pin ``search_path``.

    Opt-in by default (``enabled=False``).  Set ``enabled: true`` to
    activate.  Use ``severity: error`` to make the check a hard CI gate
    (default ``warning`` is advisory).

    Attributes:
        enabled: Master switch.
        apply_to: Schema-name patterns (``fnmatch``-style) that scope
            the check.  ``["*"]`` covers every schema.
        ignore: Object-path globs (``schema.name``) that opt specific
            callables out of detection for deliberate exceptions.
        severity: Violation severity — ``"warning"`` (advisory, exit 0)
            or ``"error"`` (hard gate, exit 1).
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    apply_to: list[str] = Field(default_factory=lambda: ["*"])
    ignore: list[str] = Field(default_factory=list)
    severity: str = "warning"

    @field_validator("severity")
    @classmethod
    def _check_severity(cls, v: str) -> str:
        if v not in ("warning", "error"):
            raise ValueError(f"severity must be 'warning' or 'error', got {v!r}")
        return v


_PRIVILEGE_KEYWORDS: frozenset[str] = frozenset(
    {
        "SELECT",
        "INSERT",
        "UPDATE",
        "DELETE",
        "TRUNCATE",
        "REFERENCES",
        "TRIGGER",
        "EXECUTE",
        "USAGE",
    }
)


class OwnershipExpectation(BaseModel):
    """The ``ownership:`` block in environment YAML (issue #124).

    A single declaration — unlike :class:`AclExpectation` which is a
    list — because ownership has exactly one canonical owner per
    environment.

    Mirrors the structure of :class:`AclTableExpectation` (#120) but on
    the ownership axis.  Opt-in by default: ``lint_enabled`` defaults
    to ``True`` per the issue's Definition of done.

    Attributes:
        expected_owner: Canonical role that should own every in-scope
            relation in the environment.
        apply_to: Per-schema scope entries (which relkinds to check).
        ignore: Object-path globs that opt specific relations out of
            both static lint and runtime drift detection.
        lint_enabled: Master switch for the static ``own_001`` rule.
        bootstrap_connection_url: Optional superuser URL used by
            ``confiture bootstrap`` (issue #137).  Required for
            ``--apply`` because ``CREATE ROLE`` and ``REASSIGN OWNED``
            both need superuser.  Falls back to the env's main URL
            only when the user passes the explicit override; we never
            guess.  Supports ``${VAR}`` expansion at load time.
        default_privileges: Mapping of ``schema -> role ->
            [PRIVILEGE, ...]`` used to plan ``ALTER DEFAULT PRIVILEGES``
            statements in ``confiture bootstrap`` (issue #137 part 1).
            ``None`` means the bootstrap step is skipped with a one-line
            notice.  Privilege strings are validated against the
            standard PostgreSQL allow-list.
    """

    model_config = ConfigDict(extra="forbid")

    expected_owner: str
    apply_to: list[OwnershipApplyTo]
    ignore: list[str] = Field(default_factory=list)
    lint_enabled: bool = True
    bootstrap_connection_url: str | None = None
    default_privileges: dict[str, dict[str, list[str]]] | None = None

    @field_validator("expected_owner")
    @classmethod
    def _validate_owner_name(cls, v: str) -> str:
        if not _ROLE_IDENT_RE.match(v):
            raise ValueError(
                f"Invalid role identifier: {v!r}. "
                f"Use an unquoted ``[a-z_][a-z0-9_]*`` form, or a double-quoted "
                f'``"Name"`` form for mixed-case roles.'
            )
        return v

    @field_validator("default_privileges")
    @classmethod
    def _validate_default_privileges(
        cls, v: dict[str, dict[str, list[str]]] | None
    ) -> dict[str, dict[str, list[str]]] | None:
        if v is None:
            return None
        for schema, role_map in v.items():
            for role, privs in role_map.items():
                unknown = {p.upper() for p in privs} - _PRIVILEGE_KEYWORDS
                if unknown:
                    raise ValueError(
                        f"Invalid privilege keyword(s) for {schema}.{role}: "
                        f"{sorted(unknown)}. Allowed: "
                        f"{sorted(_PRIVILEGE_KEYWORDS)}."
                    )
        return v


class Environment(BaseModel):
    """Environment configuration

    Loaded from db/environments/{env_name}.yaml files.

    Attributes:
        name: Environment name (e.g., "local", "production")
        database_url: PostgreSQL connection URL
        include_dirs: Directories to include when building schema (supports both string and dict formats)
        superuser_post_dirs: Directories routed to the post-schema superuser phase in build_split()
        exclude_dirs: Directories to exclude from schema build
        auto_backup: Whether to automatically backup before migrations
        require_confirmation: Whether to require user confirmation for risky operations
        build: Build configuration options
        migration: Migration configuration options (includes tracking_table)
        pggit: pgGit integration configuration (development/staging only)
        seed: Seed data application configuration
    """

    # ``name`` and ``include_dirs`` are build-only fields and are never read on
    # the migrate path (``MigratorSession`` uses only ``database_url`` and
    # ``migration.tracking_table``).  They default here so a migrate-only
    # Python-API consumer can ``Environment.model_validate({"database_url": …})``
    # without supplying build metadata — matching the CLI's lenient config
    # loader (issue #168).  Build safety is unaffected: ``Environment.load``
    # injects ``name`` and guards a missing ``include_dirs``, and
    # ``SchemaBuilder`` independently rejects an empty ``include_dirs``.
    name: str = ""
    database_url: str
    include_dirs: list[str | DirectoryConfig] = Field(default_factory=list)
    superuser_dirs: list[str | DirectoryConfig] = Field(default_factory=list)
    superuser_post_dirs: list[str | DirectoryConfig] = Field(default_factory=list)
    exclude_dirs: list[str] = Field(default_factory=list)
    auto_backup: bool = True
    require_confirmation: bool = True
    build: BuildConfig = Field(default_factory=BuildConfig)
    migration: MigrationConfig = Field(default_factory=MigrationConfig)
    infrastructure: InfrastructureConfig = Field(default_factory=InfrastructureConfig)
    pggit: PgGitConfig = Field(default_factory=PgGitConfig)
    seed: SeedConfig = Field(default_factory=SeedConfig)
    ssh_tunnel: SshTunnelConfig | None = None
    acls: list[AclExpectation] = Field(default_factory=list)
    # Opt-in switch for the ACL coverage lint rule.  Defaults to False so a
    # project that merely defines ``acls:`` for the drift command doesn't
    # have lint failures injected without explicitly asking for them.  Set
    # via the nested YAML shape ``acls: { lint_enabled: true, expectations:
    # [...] }``; the flat-list form (``acls: [...]``) keeps this False.
    acls_lint_enabled: bool = False
    # Issue #124 — ownership coverage.  Single declaration (one canonical
    # owner per env), unlike ``acls:`` which is a list.  ``None`` means
    # the project hasn't opted into ownership coverage at all.
    ownership: OwnershipExpectation | None = None
    # Issue #136 — function-uniqueness lint (``func_001``).  ``None``
    # leaves the rule disabled; set ``function_coverage.enabled: true``
    # in the env YAML to opt in.
    function_coverage: FunctionCoverage | None = None
    # Issue #161 — SECURITY DEFINER / search_path lint (``sec_002``).  ``None``
    # leaves the rule disabled; set ``security_lint.enabled: true`` in the env
    # YAML to opt in.
    security_lint: SecurityLinting | None = None

    @property
    def database(self) -> DatabaseConfig:
        """Get database configuration from database_url.

        Returns:
            DatabaseConfig instance
        """
        return DatabaseConfig.from_url(self.database_url)

    @model_validator(mode="before")
    @classmethod
    def _reject_legacy_migration_table(cls, data: Any) -> Any:
        """Reject the legacy top-level ``migration_table`` key with an actionable error.

        Before Issue #60, some documentation showed ``migration_table:`` at the
        top level of the environment YAML.  Pydantic would silently ignore it
        (unknown field).  This validator turns that silent misconfiguration into
        a clear ``ConfigurationError`` so users know exactly what to fix.

        Correct form::

            migration:
              tracking_table: public.tb_confiture
        """
        if isinstance(data, dict) and "migration_table" in data:
            raise ConfigurationError(
                "Unknown config key 'migration_table' at top level.\n"
                "Move it under 'migration:' and rename to 'tracking_table':\n\n"
                "  migration:\n"
                "    tracking_table: " + str(data["migration_table"])
            )
        return data

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        """Validate PostgreSQL connection URL format"""
        if not v.startswith(("postgresql://", "postgres://")):
            raise ValueError(
                f"Invalid database_url: must start with postgresql:// or postgres://, got: {v}"
            )
        return v

    @classmethod
    def load(cls, env_name: str, project_dir: Path | None = None) -> "Environment":
        """Load environment configuration from YAML file

        Args:
            env_name: Environment name (e.g., "local", "production")
            project_dir: Project root directory. If None, uses current directory.

        Returns:
            Environment configuration object

        Raises:
            ConfigurationError: If config file not found, invalid, or missing required fields

        Example:
            >>> env = Environment.load("local")
            >>> print(env.database_url)
            postgresql://localhost/myapp_local
        """
        if project_dir is None:
            project_dir = Path.cwd()

        # Find config file
        config_path = project_dir / "db" / "environments" / f"{env_name}.yaml"

        if not config_path.exists():
            raise ConfigurationError(
                f"Environment config not found: {config_path}\n"
                f"Expected: db/environments/{env_name}.yaml"
            )

        # Load YAML
        try:
            with open(config_path) as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ConfigurationError(f"Invalid YAML in {config_path}: {e}") from e

        if not isinstance(data, dict):
            raise ConfigurationError(
                f"Invalid config format in {config_path}: expected dictionary, got {type(data)}"
            )

        # Validate required fields
        if "database_url" not in data:
            raise ConfigurationError(f"Missing required field 'database_url' in {config_path}")

        if "include_dirs" not in data:
            raise ConfigurationError(f"Missing required field 'include_dirs' in {config_path}")

        # Resolve include_dirs paths to absolute
        resolved_include_dirs: list[str | dict[str, Any]] = []
        for include_item in data["include_dirs"]:
            if isinstance(include_item, str):
                # Simple string format - resolve to absolute path
                abs_path = (project_dir / include_item).resolve()
                if not abs_path.exists():
                    raise ConfigurationError(
                        f"Include directory does not exist: {abs_path}\nSpecified in {config_path}"
                    )
                resolved_include_dirs.append(str(abs_path))
            elif isinstance(include_item, dict):
                # Dict format - resolve the path field and keep as dict
                path_str = include_item.get("path")
                if not path_str:
                    raise ConfigurationError(
                        f"Missing 'path' field in include_dirs item: {include_item}\nIn {config_path}"
                    )
                abs_path = (project_dir / path_str).resolve()
                auto_discover = include_item.get("auto_discover", True)
                if not abs_path.exists() and not auto_discover:
                    raise ConfigurationError(
                        f"Include directory does not exist: {abs_path}\nSpecified in {config_path}"
                    )
                # Keep the dict format but with resolved path
                resolved_item = include_item.copy()
                resolved_item["path"] = str(abs_path)
                resolved_include_dirs.append(resolved_item)
            else:
                raise ConfigurationError(
                    f"Invalid include_dirs item type: {type(include_item)}. Expected str or dict.\nIn {config_path}"
                )

        data["include_dirs"] = resolved_include_dirs

        # Resolve exclude_dirs if present
        if "exclude_dirs" in data:
            exclude_dirs = []
            for dir_path in data["exclude_dirs"]:
                abs_path = (project_dir / dir_path).resolve()
                exclude_dirs.append(str(abs_path))
            data["exclude_dirs"] = exclude_dirs

        # Resolve superuser_dirs if present
        if "superuser_dirs" in data:
            resolved_superuser_dirs: list[str | dict[str, Any]] = []
            for item in data["superuser_dirs"]:
                if isinstance(item, str):
                    abs_path = (project_dir / item).resolve()
                    resolved_superuser_dirs.append(str(abs_path))
                elif isinstance(item, dict):
                    path_str = item.get("path")
                    if not path_str:
                        raise ConfigurationError(
                            f"Missing 'path' field in superuser_dirs item: {item}\nIn {config_path}"
                        )
                    abs_path = (project_dir / path_str).resolve()
                    resolved_item = item.copy()
                    resolved_item["path"] = str(abs_path)
                    resolved_superuser_dirs.append(resolved_item)
                else:
                    raise ConfigurationError(
                        f"Invalid superuser_dirs item type: {type(item)}. Expected str or dict.\nIn {config_path}"
                    )
            data["superuser_dirs"] = resolved_superuser_dirs

        # Resolve superuser_post_dirs if present
        if "superuser_post_dirs" in data:
            resolved_superuser_post_dirs: list[str | dict[str, Any]] = []
            for item in data["superuser_post_dirs"]:
                if isinstance(item, str):
                    abs_path = (project_dir / item).resolve()
                    resolved_superuser_post_dirs.append(str(abs_path))
                elif isinstance(item, dict):
                    path_str = item.get("path")
                    if not path_str:
                        raise ConfigurationError(
                            f"Missing 'path' field in superuser_post_dirs item: {item}\nIn {config_path}"
                        )
                    abs_path = (project_dir / path_str).resolve()
                    resolved_item = item.copy()
                    resolved_item["path"] = str(abs_path)
                    resolved_superuser_post_dirs.append(resolved_item)
                else:
                    raise ConfigurationError(
                        f"Invalid superuser_post_dirs item type: {type(item)}. Expected str or dict.\nIn {config_path}"
                    )
            data["superuser_post_dirs"] = resolved_superuser_post_dirs

        # Set environment name
        data["name"] = env_name

        # Normalize the ``acls:`` block — accept both shapes:
        #   1. Flat list (legacy)       :  ``acls: [ {...}, {...} ]``
        #   2. Nested dict (preferred)  :  ``acls: { lint_enabled: true, expectations: [...] }``
        # Flatten the nested form into the model's split fields so the rest
        # of the loader (env-var expansion, Pydantic validation) stays
        # blissfully unaware of the dual shape.
        if "acls" in data and isinstance(data["acls"], dict):
            acl_block = data["acls"]
            unknown = set(acl_block) - {"lint_enabled", "expectations"}
            if unknown:
                raise ConfigurationError(
                    f"Unknown key(s) in acls block: {sorted(unknown)}. "
                    f"Allowed: 'lint_enabled', 'expectations'."
                )
            data["acls_lint_enabled"] = bool(acl_block.get("lint_enabled", False))
            data["acls"] = acl_block.get("expectations", [])

        # Expand ${VAR} placeholders inside the acls: subtree at load time —
        # role names commonly parameterize across envs.  Missing variables
        # raise ConfigurationError; we never substitute empty strings.
        if "acls" in data:
            data["acls"] = expand_env_vars(data["acls"], context="acls")

        # Same treatment for the ``ownership:`` subtree (issue #124) — the
        # ``expected_owner`` field commonly parameterizes across envs.
        if "ownership" in data and data["ownership"] is not None:
            data["ownership"] = expand_env_vars(data["ownership"], context="ownership")

        # Same treatment for the ``function_coverage:`` subtree (issue #136).
        if "function_coverage" in data and data["function_coverage"] is not None:
            data["function_coverage"] = expand_env_vars(
                data["function_coverage"], context="function_coverage"
            )

        # Create Environment instance
        try:
            return cls(**data)
        except Exception as e:
            raise ConfigurationError(f"Invalid configuration in {config_path}: {e}") from e
