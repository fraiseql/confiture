"""Environment configuration management

Handles loading and validation of environment-specific configuration from YAML files.
"""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from confiture.exceptions import ConfigurationError


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
    validate_comments: CommentValidationConfig = Field(default_factory=CommentValidationConfig)
    separators: SeparatorConfig = Field(default_factory=SeparatorConfig)
    lint: BuildLintConfig = Field(default_factory=BuildLintConfig)


class SeedConfig(BaseModel):
    """Seed data application configuration.

    Controls how seed files are executed (concatenated vs sequential).
    Sequential mode executes each file independently within its own savepoint,
    avoiding PostgreSQL parser limits for large files (650+ rows).

    Attributes:
        execution_mode: Execution strategy ("concatenate" | "sequential")
        continue_on_error: Continue applying files if one fails (default: False)
        transaction_mode: Transaction isolation ("savepoint" | "transaction")
    """

    execution_mode: str = "concatenate"  # "concatenate" | "sequential"
    continue_on_error: bool = False
    transaction_mode: str = "savepoint"  # "savepoint" | "transaction"


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
        tracking_table: Name of the confiture tracking table, optionally schema-qualified
            (e.g. ``public.tb_confiture``). Defaults to ``tb_confiture``.
    """

    strict_mode: bool = False  # Whether to fail on warnings/notices
    locking: LockingConfig = Field(default_factory=LockingConfig)
    view_helpers: str = "manual"  # "auto" | "manual" | "off"
    migration_generators: dict[str, MigrationGeneratorConfig] = Field(default_factory=dict)
    snapshot_history: bool = True
    snapshots_dir: str = "db/schema_history"
    tracking_table: str = "tb_confiture"
    rebuild_threshold: int = 5


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


class Environment(BaseModel):
    """Environment configuration

    Loaded from db/environments/{env_name}.yaml files.

    Attributes:
        name: Environment name (e.g., "local", "production")
        database_url: PostgreSQL connection URL
        include_dirs: Directories to include when building schema (supports both string and dict formats)
        exclude_dirs: Directories to exclude from schema build
        auto_backup: Whether to automatically backup before migrations
        require_confirmation: Whether to require user confirmation for risky operations
        build: Build configuration options
        migration: Migration configuration options (includes tracking_table)
        pggit: pgGit integration configuration (development/staging only)
        seed: Seed data application configuration
    """

    name: str
    database_url: str
    include_dirs: list[str | DirectoryConfig]
    exclude_dirs: list[str] = Field(default_factory=list)
    auto_backup: bool = True
    require_confirmation: bool = True
    build: BuildConfig = Field(default_factory=BuildConfig)
    migration: MigrationConfig = Field(default_factory=MigrationConfig)
    pggit: PgGitConfig = Field(default_factory=PgGitConfig)
    seed: SeedConfig = Field(default_factory=SeedConfig)

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

        # Set environment name
        data["name"] = env_name

        # Create Environment instance
        try:
            return cls(**data)
        except Exception as e:
            raise ConfigurationError(f"Invalid configuration in {config_path}: {e}") from e
