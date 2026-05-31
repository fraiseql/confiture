"""Connection-free configuration validator (issue #144).

`ConfigValidator` answers "is this config (or DSN) syntactically and
semantically valid?" *without ever opening a database connection*. It composes
the existing building blocks — `Environment` Pydantic validation, the
migrations-tree helpers used by preflight — into a structured report.

Each issue is the unified inner issue object (see the batch shared-issue-schema):
``{severity, code, message, actionable, details, migration, file, line}``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from confiture.core._migrator.discovery import (
    _version_from_migration_filename,
    find_duplicate_migration_versions,
)


@dataclass(frozen=True)
class ConfigIssue:
    """A single config-validation finding — the unified inner issue object."""

    severity: str
    code: str
    message: str
    migration: str | None = None
    file: str | None = None
    line: int | None = None
    actionable: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "migration": self.migration,
            "file": self.file,
            "line": self.line,
            "actionable": self.actionable,
            "details": self.details,
        }


@dataclass
class ConfigValidationReport:
    """Result of `validate-config` (issue #144)."""

    valid: bool
    config_source: str  # "yaml-file" | "flags" | "env"
    migrations_path: str
    migration_count: int
    issues: list[ConfigIssue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "config_source": self.config_source,
            "migrations_path": self.migrations_path,
            "migration_count": self.migration_count,
            "issues": [i.to_dict() for i in self.issues],
        }


def _is_dsn(value: str) -> bool:
    return value.startswith(("postgresql://", "postgres://"))


class ConfigValidator:
    """Validate a config source offline (never connects)."""

    def __init__(
        self,
        *,
        config_source: str,
        migrations_path: Path,
        raw: dict[str, Any] | None = None,
        config_path: Path | None = None,
        project_dir: Path | None = None,
        database_url: str | None = None,
        load_error: ConfigIssue | None = None,
    ) -> None:
        self._config_source = config_source
        self._migrations_path = migrations_path
        self._raw = raw
        self._config_path = config_path
        self._project_dir = project_dir
        self._database_url = database_url
        self._load_error = load_error

    # ------------------------------------------------------------------ #
    # Constructors
    # ------------------------------------------------------------------ #

    @classmethod
    def from_config(
        cls, config_path: Path, *, migrations_path: Path | None = None
    ) -> ConfigValidator:
        """Build from a YAML config file (config_source = "yaml-file")."""
        migrations_path = migrations_path or Path("db/migrations")
        # Resolve include_dirs relative to the project root: for the standard
        # db/environments/<env>.yaml layout that is three levels up; otherwise
        # the config file's own directory.
        if (
            config_path.parent.name == "environments"
            and config_path.parent.parent.name == "db"
        ):
            project_dir = config_path.parent.parent.parent
        else:
            project_dir = config_path.parent

        if not config_path.exists():
            return cls(
                config_source="yaml-file",
                migrations_path=migrations_path,
                project_dir=project_dir,
                config_path=config_path,
                load_error=ConfigIssue(
                    severity="error",
                    code="CONFIG_004",
                    message=f"Configuration file not found: {config_path}",
                    actionable=f"Create a YAML config at {config_path} or check the path.",
                ),
            )

        try:
            raw = yaml.safe_load(config_path.read_text())
        except yaml.YAMLError as e:
            return cls(
                config_source="yaml-file",
                migrations_path=migrations_path,
                project_dir=project_dir,
                config_path=config_path,
                load_error=ConfigIssue(
                    severity="error",
                    code="CONFIG_002",
                    message=f"Invalid YAML syntax in {config_path}: {e}",
                    file=str(config_path),
                    actionable="Fix the YAML syntax (indentation / quoting).",
                ),
            )

        if not isinstance(raw, dict):
            return cls(
                config_source="yaml-file",
                migrations_path=migrations_path,
                project_dir=project_dir,
                config_path=config_path,
                load_error=ConfigIssue(
                    severity="error",
                    code="CONFIG_002",
                    message=f"Invalid config format in {config_path}: expected a mapping.",
                    file=str(config_path),
                    actionable="The top-level YAML must be a mapping of keys.",
                ),
            )

        return cls(
            config_source="yaml-file",
            migrations_path=migrations_path,
            project_dir=project_dir,
            config_path=config_path,
            raw=raw,
        )

    @classmethod
    def from_flags(
        cls, *, database_url: str, migrations_path: Path | None = None
    ) -> ConfigValidator:
        """Build from a direct --database-url flag (config_source = "flags")."""
        return cls(
            config_source="flags",
            migrations_path=migrations_path or Path("db/migrations"),
            database_url=database_url,
        )

    @classmethod
    def from_env(
        cls, *, database_url: str, migrations_path: Path | None = None
    ) -> ConfigValidator:
        """Build from a DSN found in the environment (config_source = "env")."""
        return cls(
            config_source="env",
            migrations_path=migrations_path or Path("db/migrations"),
            database_url=database_url,
        )

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #

    def validate(self) -> ConfigValidationReport:
        """Run all offline checks and return the structured report."""
        issues: list[ConfigIssue] = []

        if self._load_error is not None:
            issues.append(self._load_error)
        elif self._raw is not None:
            issues.extend(self._validate_schema(self._raw))
        elif self._database_url is not None:
            issues.extend(self._validate_dsn_format(self._database_url))

        migration_count, tree_issues = self._validate_migrations_tree()
        issues.extend(tree_issues)

        valid = not any(i.severity in ("error", "critical") for i in issues)
        return ConfigValidationReport(
            valid=valid,
            config_source=self._config_source,
            migrations_path=str(self._migrations_path),
            migration_count=migration_count,
            issues=issues,
        )

    def _validate_schema(self, raw: dict[str, Any]) -> list[ConfigIssue]:
        from pydantic import ValidationError

        from confiture.config.environment import Environment
        from confiture.exceptions import ConfigurationError

        # Best-effort env-var expansion so ${VAR} placeholders that are set
        # validate; a missing var stays literal and surfaces as a config issue
        # (a malformed DSN) rather than connecting or crashing.
        expanded = _expand_env(raw)

        issues: list[ConfigIssue] = []
        try:
            env = Environment.model_validate(expanded)
        except ConfigurationError as e:
            issues.append(
                ConfigIssue(
                    severity="error",
                    code=e.error_code or "CONFIG_001",
                    message=str(e),
                    file=str(self._config_path) if self._config_path else None,
                    actionable=e.resolution_hint,
                )
            )
            return issues
        except ValidationError as e:
            issues.extend(self._pydantic_to_issues(e))
            return issues

        issues.extend(self._validate_include_dirs(env))
        return issues

    def _pydantic_to_issues(self, error: Any) -> list[ConfigIssue]:
        """Translate a Pydantic ValidationError into ConfigIssues.

        A missing required field → CONFIG_001; a bad database_url → CONFIG_003;
        anything else → CONFIG_001. The non-filesystem loc path goes in
        ``details.config_path`` (not ``file``).
        """
        issues: list[ConfigIssue] = []
        for err in error.errors():
            loc = list(err.get("loc", ()))
            etype = err.get("type", "")
            field_name = str(loc[0]) if loc else ""
            if etype == "missing":
                code = "CONFIG_001"
                actionable = "Add the required field to your config file."
            elif field_name == "database_url":
                code = "CONFIG_003"
                actionable = "Use format: postgresql://user:password@host:port/database"
            else:
                code = "CONFIG_001"
                actionable = "Fix the field to match the expected type/shape."
            issues.append(
                ConfigIssue(
                    severity="error",
                    code=code,
                    message=f"{'.'.join(map(str, loc)) or 'config'}: {err.get('msg', 'invalid')}",
                    file=str(self._config_path) if self._config_path else None,
                    actionable=actionable,
                    details={"config_path": loc} if loc else {},
                )
            )
        return issues

    def _validate_include_dirs(self, env: Any) -> list[ConfigIssue]:
        issues: list[ConfigIssue] = []
        base = self._project_dir or Path.cwd()
        for item in env.include_dirs:
            path_str = item if isinstance(item, str) else getattr(item, "path", None)
            if not path_str:
                continue
            resolved = Path(path_str)
            if not resolved.is_absolute():
                resolved = base / resolved
            # auto_discover dirs are allowed to be absent (created lazily).
            auto_discover = getattr(item, "auto_discover", False) if not isinstance(item, str) else False
            if not resolved.exists() and not auto_discover:
                issues.append(
                    ConfigIssue(
                        severity="error",
                        code="CONFIG_001",
                        message=f"Include directory does not exist: {resolved}",
                        file=str(resolved),
                        actionable="Create the directory or correct the include_dirs path.",
                    )
                )
        return issues

    def _validate_dsn_format(self, database_url: str) -> list[ConfigIssue]:
        if _is_dsn(database_url):
            return []
        return [
            ConfigIssue(
                severity="error",
                code="CONFIG_003",
                message=f"Invalid database URL format: {database_url}",
                actionable="Use format: postgresql://user:password@host:port/database",
            )
        ]

    def _validate_migrations_tree(self) -> tuple[int, list[ConfigIssue]]:
        issues: list[ConfigIssue] = []
        migrations_dir = self._migrations_path
        if not migrations_dir.exists():
            # Not an error by itself — a project may have no migrations yet.
            return 0, issues

        sql_files = sorted(migrations_dir.glob("*.up.sql"))
        py_files = sorted(
            f
            for f in migrations_dir.glob("*.py")
            if f.name != "__init__.py" and not f.name.startswith("_")
        )
        files = sql_files + py_files

        for f in files:
            version = _version_from_migration_filename(f.name)
            if not version or version == f.name.split(".")[0]:
                # No parseable {version}_{name} prefix.
                base = f.name.split(".")[0]
                if "_" not in base:
                    issues.append(
                        ConfigIssue(
                            severity="error",
                            code="MIGR_102",
                            message=f"Migration filename is not well-formed: {f.name} "
                            f"(expected <version>_<name>.up.sql or .py).",
                            file=str(f),
                            migration=version or None,
                            actionable="Rename to <version>_<name>.up.sql (e.g. "
                            "20260531120000_add_users.up.sql).",
                        )
                    )

        duplicates = find_duplicate_migration_versions(migrations_dir)
        for version, dup_files in duplicates.items():
            issues.append(
                ConfigIssue(
                    severity="error",
                    code="MIGR_106",
                    message=f"Duplicate migration version {version}: "
                    f"{', '.join(f.name for f in dup_files)}.",
                    migration=version,
                    actionable="Rename files to use unique version prefixes.",
                    details={"files": [f.name for f in dup_files]},
                )
            )

        return len(files), issues


def _expand_env(value: Any) -> Any:
    """Recursively expand ${VAR} in strings (best-effort; missing → literal)."""
    if isinstance(value, str):
        return os.path.expandvars(value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value
