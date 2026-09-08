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
from confiture.url_redaction import redact_url

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
# Must start with a word character: a leading `-` would make the destination an
# option to ssh, a leading `.` or `@` is never a login name.
_VALID_SSH_USER_RE = re.compile(r"^[a-zA-Z0-9_][a-zA-Z0-9_\-\.@]*$")


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
    """Build configuration options.

    Attributes:
        validate_comments: Block-comment validation before a build (``enabled``, ``fail_on_unclosed_blocks``, ``fail_on_spillover``).
        separators: How file boundaries are marked in the built schema (``style``: block_comment, line_comment, mysql, custom; ``custom_template``).
        lint: Lint run as part of ``confiture build`` (``enabled``, ``fail_on_error``, ``fail_on_warning``, ``rules``).
    """

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
        transaction_mode: "savepoint" (one transaction, a savepoint per file — a failure
            rolls back that file only) or "transaction" (each file commits on its own,
            so files before a failure stay applied)
        profiles: Named seed subsets (see :class:`SeedProfile`). Absent ⇒ today's
            apply-all behaviour is unchanged.
    """

    execution_mode: str = "concatenate"  # "concatenate" | "sequential"
    continue_on_error: bool = False
    transaction_mode: Literal["savepoint", "transaction"] = "savepoint"
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


class BackfillConfig(BaseModel):
    """How the online runner's backfill stage runs (issue #200).

    Attributes:
        batch_size: Rows per committed batch of a backfill (default: 5000).
        max_lock_ms: Pause, in milliseconds, between batches while another session waits for a lock on the table; unset disables the guard. ``--max-lock-ms`` on ``migrate steps --resume`` and ``migrate up --online`` overrides it per run.
    """

    batch_size: int = 5000
    max_lock_ms: int | None = None


class MigrationConfig(BaseModel):
    """Migration configuration options.

    Attributes:
        rebuild_threshold: Number of pending migrations above which ``migrate status --check-rebuild`` recommends a rebuild from DDL (default: 50).
        grant_dir: Directory holding GRANT/REVOKE files that grant-accompaniment and the ACL lint read (default: ``db/grants``).
        allow_unsafe_under_replication: Downgrade replica-unsafe preflight findings to warnings even when ``infrastructure.replicas`` are declared.
        strict_mode: Whether to fail on warnings/notices (default: False)
        destructive: What ``migrate diff --generate`` does with a change that loses data (a dropped table or column, a narrowed type): ``gated`` (default) writes it marked ``-- confiture:destructive`` so ``migrate up`` needs ``--allow-destructive``; ``allow`` writes it unmarked; ``forbid`` refuses to generate (``DIFFER_401``). ``--allow-destructive`` / ``--forbid-destructive`` on ``migrate diff`` override it per run.
        backfill: The online runner's backfill settings (batch size, lock-waiter guard)
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
    destructive: Literal["gated", "allow", "forbid"] = "gated"
    backfill: BackfillConfig = Field(default_factory=BackfillConfig)
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

    Attributes:
        replicas: Read replicas of this environment (hostnames or DSNs); declaring any makes replica-unsafe DDL a preflight error.
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
                "Start with a letter, digit or underscore; then letters, digits, "
                "hyphens, underscores, dots, or @."
            )
        return v

    remote_port: int = 5432
    remote_socket: str | None = None
    local_port: int = 0
    identity_file: str | None = None
    timeout_s: int = 10


class DirectoryConfig(BaseModel):
    """Directory configuration with pattern matching.

    Attributes:
        path: Directory to read, relative to the project root.
        recursive: Descend into subdirectories (default: true).
        include: Glob patterns a file must match to be built (default: ``**/*.sql``).
        exclude: Glob patterns that remove files from the build.
        auto_discover: Discover files by the include/exclude globs; ``false`` builds only what ``order`` and explicit names select.
        order: Sort key among directories in the build; lower runs first (default: 0).
    """

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

    # Carries a password: pydantic must not echo rejected input back in error text.
    model_config = ConfigDict(hide_input_in_errors=True)

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

        # Parse URL: postgresql://user:pass@host:port/dbname
        pattern = r"(?:postgresql|postgres)://(?:([^:]+):([^@]+)@)?([^:/]+)(?::(\d+))?/(.+)"
        match = re.match(pattern, url)

        if not match:
            raise ValueError(f"Invalid PostgreSQL URL: {redact_url(url)}")

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

    Attributes:
        role: Database role the privileges are granted to.
        privileges: Table privileges the role must hold (SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER, ALL); case-insensitive in YAML.
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

    Attributes:
        schema_: Schema the entry applies to (YAML key ``schema``).
        apply_to: ``ALL_TABLES`` or an explicit list of table names in that schema.
        ignore: Table names in the schema that are exempt from the expectation.
        grants: The roles and privileges every in-scope table must carry.
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

    Attributes:
        schema_: Schema the ownership expectation applies to (YAML key ``schema``).
        relkinds: ``pg_class.relkind`` letters to check (default: r tables, S sequences, v views, m materialized views).
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


class LintSettings(BaseModel):
    """The ``lint:`` block in environment YAML: what the lint rules resolve against.

    Only ``build_003`` reads it today. That rule subtracts the objects a body
    references from the objects the build creates, and the build is not the
    only thing that creates objects: a migration does, and so does an
    extension. A live database answers for both when one is reachable; this is
    what a project uses when none is.

    Attributes:
        ignore_objects: ``fnmatch`` globs over ``schema.name``. A reference
            matching one is never reported as unresolved — the escape hatch
            for an object created outside the DDL tree
            (``public.gen_random_uuid``, ``pg_stat_statements*``).
    """

    model_config = ConfigDict(extra="forbid")

    ignore_objects: list[str] = Field(default_factory=list)


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


class DriftConfig(BaseModel):
    """``drift:`` — how ``confiture drift`` and ``migrate validate --check-live-drift`` judge column order (#226).

    ``ignore_column_order`` turns the ``column_order_mismatch`` item off;
    ``column_order_severity`` is ``warning`` (default, never fails a run on its
    own) or ``critical`` (fails like a missing column). ``--ignore-column-order``
    on either command wins over the file.

    Attributes:
        ignore_column_order: Never report ``column_order_mismatch`` (default: false).
        column_order_severity: Severity of a ``column_order_mismatch`` item: ``warning`` (default) or ``critical`` (fails the run).
    """

    ignore_column_order: bool = False
    column_order_severity: Literal["warning", "critical"] = "warning"


def _read_config_yaml(config_path: Path) -> dict[str, Any]:
    """The YAML mapping at ``config_path``; anything else is a ``ConfigurationError``."""
    try:
        with Path(config_path).open() as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigurationError(f"Invalid YAML in {config_path}: {e}") from e

    if not isinstance(data, dict):
        raise ConfigurationError(
            f"Invalid config format in {config_path}: expected dictionary, got {type(data)}"
        )
    return data


def _resolve_dir_items(
    items: list[Any], project_dir: Path, config_path: Path, field_name: str, *, check_exists: bool
) -> list[str | dict[str, Any]]:
    """Resolve a directory list (strings or ``{path: …}`` dicts) to absolute paths.

    With ``check_exists`` a missing directory is an error unless the item sets
    ``auto_discover`` (the ``include_dirs`` rule); the superuser lists are not
    checked at load time.
    """
    resolved: list[str | dict[str, Any]] = []
    for item in items:
        if isinstance(item, str):
            abs_path = (project_dir / item).resolve()
            if check_exists and not abs_path.exists():
                raise ConfigurationError(
                    f"Include directory does not exist: {abs_path}\nSpecified in {config_path}"
                )
            resolved.append(str(abs_path))
        elif isinstance(item, dict):
            path_str = item.get("path")
            if not path_str:
                raise ConfigurationError(
                    f"Missing 'path' field in {field_name} item: {item}\nIn {config_path}"
                )
            abs_path = (project_dir / path_str).resolve()
            if check_exists and not abs_path.exists() and not item.get("auto_discover", True):
                raise ConfigurationError(
                    f"Include directory does not exist: {abs_path}\nSpecified in {config_path}"
                )
            resolved_item = item.copy()
            resolved_item["path"] = str(abs_path)
            resolved.append(resolved_item)
        else:
            raise ConfigurationError(
                f"Invalid {field_name} item type: {type(item)}. Expected str or dict.\nIn {config_path}"
            )
    return resolved


def _normalize_acls(data: dict[str, Any]) -> None:
    """Flatten a nested ``acls:`` block into the model's split fields.

    Two shapes are accepted: a flat list (legacy) ``acls: [ {...}, {...} ]`` and
    the preferred nested dict ``acls: { lint_enabled: true, expectations: [...] }``.
    The rest of the loader (env-var expansion, Pydantic validation) then sees
    one shape.
    """
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


class Environment(BaseModel):
    """Environment configuration

    Loaded from db/environments/{env_name}.yaml files.

    Attributes:
        superuser_dirs: Directories whose files run in the superuser phase of ``build_split()`` (extensions, roles); excluded from the schema hash.
        infrastructure: Deployment topology — the read replicas the replica-safety policy takes into account (``infrastructure.replicas``).
        drift: How ``confiture drift`` and ``migrate validate --check-live-drift`` judge column order (``drift.ignore_column_order``, ``drift.column_order_severity``).
        ssh_tunnel: SSH tunnel to reach a database that is not directly routable; ``null`` means connect directly.
        acls: Expected table grants per schema for ``drift --check-acls`` and the ``acl_001`` lint (list of ``AclTableExpectation``).
        acls_lint_enabled: Run the static ``acl_001`` grant-coverage lint over migrations; ``acls:`` alone only feeds ``drift --check-acls``.
        ownership: Expected relation ownership per schema for ``drift --check-ownership`` and the ``own_001`` lint; ``null`` disables both.
        function_coverage: Which schemas' functions the function-uniqueness check covers (``migrate validate --check-function-uniqueness``).
        security_lint: The ``sec_002`` SECURITY DEFINER lint: enabled flag, schema scope, ignore globs and severity.
        lint: What the lint rules resolve against — ``lint.ignore_objects`` excuses a name ``build_003`` cannot find in the build.
        name: Environment name (e.g., "local", "production")
        database_url: PostgreSQL connection URL
        include_dirs: Directories to include when building schema (supports both string and dict formats)
        superuser_post_dirs: Directories routed to the post-schema superuser phase in build_split()
        exclude_dirs: Directories to exclude from schema build
        build: Build configuration options
        migration: Migration configuration options (includes tracking_table)
        seed: Seed data application configuration
    """

    # `database_url` may embed a password: pydantic must not echo rejected input
    # back in error text; the validators quote a redacted form instead.
    model_config = ConfigDict(hide_input_in_errors=True)

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
    build: BuildConfig = Field(default_factory=BuildConfig)
    migration: MigrationConfig = Field(default_factory=MigrationConfig)
    infrastructure: InfrastructureConfig = Field(default_factory=InfrastructureConfig)
    seed: SeedConfig = Field(default_factory=SeedConfig)
    drift: DriftConfig = Field(default_factory=DriftConfig)
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
    # Issue #246 — what ``build_003`` resolves references against when the
    # build inventory and a live database cannot answer.
    lint: LintSettings = Field(default_factory=LintSettings)

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
                "Invalid database_url: must start with postgresql:// or postgres://, "
                f"got: {redact_url(v)}"
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

        data = _read_config_yaml(config_path)

        # Validate required fields
        if "database_url" not in data:
            raise ConfigurationError(f"Missing required field 'database_url' in {config_path}")

        if "include_dirs" not in data:
            raise ConfigurationError(f"Missing required field 'include_dirs' in {config_path}")

        # Resolve include_dirs paths to absolute (a missing directory is an error
        # unless the item opts into auto-discovery)
        data["include_dirs"] = _resolve_dir_items(
            data["include_dirs"], project_dir, config_path, "include_dirs", check_exists=True
        )

        # Resolve exclude_dirs if present
        if "exclude_dirs" in data:
            data["exclude_dirs"] = [
                str((project_dir / dir_path).resolve()) for dir_path in data["exclude_dirs"]
            ]

        for field_name in ("superuser_dirs", "superuser_post_dirs"):
            if field_name in data:
                data[field_name] = _resolve_dir_items(
                    data[field_name], project_dir, config_path, field_name, check_exists=False
                )

        # Set environment name
        data["name"] = env_name

        _normalize_acls(data)

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
        except (TypeError, ValueError) as e:
            raise ConfigurationError(f"Invalid configuration in {config_path}: {e}") from e
