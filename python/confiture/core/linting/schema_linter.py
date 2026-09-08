"""Schema linting engine - validates PostgreSQL schemas against best practices.

This module provides the SchemaLinter class which validates database schemas
against configurable rules for naming conventions, primary keys, documentation,
and other best practices.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import pglast
import pglast.parser
import psycopg

from confiture.config.environment import Environment
from confiture.core import builder as _core_builder
from confiture.core import sql_lexer
from confiture.core.linting.inventory import (
    Inventory,
    SchemaObject,
    attribute_files,
    build_inventory,
    distinct,
    label_for,
)
from confiture.core.parser_info import parse_error_line
from confiture.exceptions import ConfiturError

logger = logging.getLogger(__name__)

#: How long ``build_003``'s live tier waits for a connection. A lint runs in a
#: pre-commit hook; a server that is not there must cost a moment, not a minute.
_LIVE_TIER_TIMEOUT_S = 3


def _first_line(exc: Exception) -> str:
    """A driver's error, trimmed to the sentence a summary line can carry."""
    return str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__


class RuleSeverity(Enum):
    """Severity levels for linting violations."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class LintViolation:
    """Represents a single linting violation."""

    rule_id: str
    rule_name: str
    severity: RuleSeverity
    object_type: str  # table, column, index, etc.
    object_name: str
    message: str
    file_path: str | None = None
    line_number: int | None = None
    suggested_fix: str | None = None

    def __str__(self) -> str:
        """String representation of violation."""
        prefix = f"[{self.severity.value.upper()}]"
        return f"{prefix} {self.rule_name}: {self.message} ({self.object_type}: {self.object_name})"


@dataclass(frozen=True)
class RuleStatus:
    """A rule that could not run, or could not run in full, and why.

    ``state`` is ``skipped`` — the rule did not run at all — or ``degraded``:
    it ran, but one of the things it resolves against was unavailable, so it
    can over-report. Both are the same three fields because both answer the
    same question for a reader, and a report that quietly omits either is a
    report whose counts mean something other than what they say.
    """

    code: str
    state: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "state": self.state, "reason": self.reason}


@dataclass
class LintReport:
    """Result of schema linting."""

    errors: list[LintViolation] = field(default_factory=list)
    warnings: list[LintViolation] = field(default_factory=list)
    info: list[LintViolation] = field(default_factory=list)
    #: What the inventory read — the counts the JSON payload reports.
    tables_checked: int = 0
    columns_checked: int = 0
    #: Rules that did not run, and rules that ran without one of their tiers.
    skipped: list[RuleStatus] = field(default_factory=list)
    degraded: list[RuleStatus] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        """Check if report contains errors."""
        return len(self.errors) > 0

    @property
    def has_warnings(self) -> bool:
        """Check if report contains warnings."""
        return len(self.warnings) > 0

    @property
    def has_info(self) -> bool:
        """Check if report contains info messages."""
        return len(self.info) > 0

    @property
    def total_violations(self) -> int:
        """Total number of violations."""
        return len(self.errors) + len(self.warnings) + len(self.info)

    def add_violation(self, violation: LintViolation) -> None:
        """Add a violation to the report."""
        if violation.severity == RuleSeverity.ERROR:
            self.errors.append(violation)
        elif violation.severity == RuleSeverity.WARNING:
            self.warnings.append(violation)
        else:
            self.info.append(violation)


class LintConfig:
    """Configuration for schema linting."""

    def __init__(
        self,
        enabled: bool = True,
        fail_on_error: bool = True,
        fail_on_warning: bool = False,
        check_naming: bool = True,
        check_primary_keys: bool = True,
        check_documentation: bool = True,
        check_indexes: bool = True,
        check_constraints: bool = True,
        check_security: bool = True,
        check_tenant_isolation: bool = False,
        check_acl_coverage: bool = True,
        check_duplicates: bool = True,
        check_qualification: bool = True,
        check_qualification_relations: bool = False,
        check_references: bool = True,
        check_bodies: bool = False,
        check_body_warnings: bool = False,
        server_url: str | None = None,
    ):
        """Initialize linting configuration.

        Args:
            enabled: Whether linting is enabled
            fail_on_error: Exit with error code if errors found
            fail_on_warning: Exit with error code if warnings found
            check_naming: Check naming conventions (snake_case)
            check_primary_keys: Ensure all tables have primary keys
            check_documentation: Check for COMMENT documentation
            check_indexes: Check indexes on foreign keys
            check_constraints: Check constraint definitions
            check_security: Check for security issues (passwords, tokens)
            check_tenant_isolation: Detect INSERTs missing tenant FK columns
                (multi-tenant rule, ``tenant_001``). Opt-in (default off).
            check_acl_coverage: Allow the ACL coverage rule (``acl_001``) to run.
            check_duplicates: Report objects defined more than once in one build
                (``build_001`` / ``build_002``).
                Default True, i.e. unchanged: the rule additionally requires
                ``acls.lint_enabled: true`` in the environment YAML. Set False to
                suppress it (``confiture lint --ignore acl``).
            check_qualification: Report routines created without a schema
                (``qual_001``). On by default, like the rule.
            check_qualification_relations: Report relations and types created
                without a schema (``qual_002``). Off by default, like the rule —
                the volume in an existing project is much higher, so it is
                adopted on its own with ``--select qual_002``.
            check_references: Report objects a body names that no file in the
                build creates (``build_003``). On by default, like the rule.
            check_bodies: Report plpgsql bodies that do not resolve
                (``body_001``). Off by default, like the rule: it needs a
                writable maintenance server carrying ``plpgsql_check``.
            check_body_warnings: Report the same analyser's opinions about a
                body that works — an unused variable, a shadowed declaration
                (``body_002``). Off by default and separately selectable.
            server_url: The writable maintenance server the ``body`` family
                builds its scratch database on (``--server-url``). ``None``
                falls back to the environment's own URL, whose *database* is
                never touched — only the server, and only to create and drop a
                throwaway database beside it.
        """
        self.enabled = enabled
        self.fail_on_error = fail_on_error
        self.fail_on_warning = fail_on_warning
        self.check_naming = check_naming
        self.check_primary_keys = check_primary_keys
        self.check_documentation = check_documentation
        self.check_indexes = check_indexes
        self.check_constraints = check_constraints
        self.check_security = check_security
        self.check_tenant_isolation = check_tenant_isolation
        self.check_acl_coverage = check_acl_coverage
        self.check_duplicates = check_duplicates
        self.check_qualification = check_qualification
        self.check_qualification_relations = check_qualification_relations
        self.check_references = check_references
        self.check_bodies = check_bodies
        self.check_body_warnings = check_body_warnings
        self.server_url = server_url


class SchemaLinter:
    """Lints PostgreSQL schema against best practices.

    Provides comprehensive schema validation including:
    - Naming convention enforcement (snake_case)
    - Primary key requirements
    - Documentation (COMMENT statements)
    - Index requirements on foreign keys
    - Constraint validation
    - Security issue detection

    Example:
        >>> config = LintConfig(enabled=True)
        >>> linter = SchemaLinter(env="local", config=config)
        >>>
        >>> # Option 1: Load schema from files
        >>> report = linter.lint()
        >>>
        >>> # Option 2: Pass schema directly
        >>> schema = "CREATE TABLE users (id INT PRIMARY KEY, name VARCHAR(255));"
        >>> report = linter.lint(schema=schema)
        >>>
        >>> if report.has_errors:
        ...     print(f"Found {len(report.errors)} errors")
    """

    def __init__(
        self,
        env: str = "local",
        project_dir: Path | None = None,
        config: LintConfig | None = None,
    ):
        """Initialize linter.

        Args:
            env: Environment name (local, test, production)
            project_dir: Project root directory
            config: Linting configuration (optional)
        """
        self.env = env
        self.project_dir = project_dir or Path()
        self.config = config or LintConfig()

        # Load environment configuration
        self.environment = Environment.load(env, project_dir=project_dir)

        # Schema cache
        self._schema_sql: str | None = None
        self._inventory: Inventory = Inventory()
        self._tables: dict[str, dict[str, Any]] | None = None
        self._schema_files: list[Path] = []
        self._file_objects: list[SchemaObject] = []
        self._file_schemas: list[SchemaObject] = []

    def lint(self, schema: str | None = None) -> LintReport:
        """Run linting and return report.

        Args:
            schema: Optional schema SQL to lint. If not provided, loads from files.

        Returns:
            LintReport with all violations found
        """
        report = LintReport()

        if not self.config.enabled:
            return report

        # Use provided schema or load from files
        if schema is not None:
            self._schema_sql = schema
            self._schema_files = []
        else:
            self._load_schema()

        if not self._schema_sql:
            logger.warning("No schema SQL found, skipping linting")
            return report

        # A schema PostgreSQL's own parser rejects can never lint clean: the
        # rules below read what they can, and this notice says the rest was
        # not read (ANA-02).
        self._inventory = Inventory()
        self._file_objects, self._file_schemas = self._inventory_per_file()
        try:
            self._inventory = build_inventory(self._schema_sql)
            attribute_files(self._inventory, self._file_objects)
        except pglast.parser.ParseError as exc:
            report.add_violation(
                LintViolation(
                    rule_id="UNPARSEABLE",
                    rule_name="Unparseable SQL",
                    severity=RuleSeverity.INFO,
                    object_type="schema",
                    object_name="schema",
                    message=f"pglast could not parse the schema: {exc}",
                    line_number=parse_error_line(self._schema_sql, exc),
                    suggested_fix="Fix the SQL syntax; rules cannot see past a parse error.",
                )
            )

        report.tables_checked = len(self._inventory.tables)
        report.columns_checked = sum(len(t.columns) for t in self._inventory.tables)

        # One table rather than a chain of ifs: a rule is its switch and its
        # method, and adding one is a row.
        for enabled, check in (
            (self.config.check_naming, self._check_naming_conventions),
            (self.config.check_primary_keys, self._check_primary_keys),
            (self.config.check_documentation, self._check_documentation),
            (self.config.check_indexes, self._check_indexes),
            (self.config.check_security, self._check_security),
            (self.config.check_duplicates, self._check_duplicates),
            (
                self.config.check_qualification or self.config.check_qualification_relations,
                self._check_qualification,
            ),
            (self.config.check_references, self._check_references),
            (
                self.config.check_bodies or self.config.check_body_warnings,
                self._check_bodies,
            ),
            (self.config.check_tenant_isolation, self._check_tenant_isolation),
        ):
            if enabled:
                check(report)

        # ACL coverage (ACL001) — opt-in via ``acls.lint_enabled: true`` in
        # the environment YAML.  The mere presence of an ``acls:`` block
        # used to auto-fire this rule, but that surprised users who set
        # ``acls:`` only for ``confiture drift --check-acls``.  Explicit
        # opt-in keeps the two surfaces independently controllable.
        if (
            self.config.check_acl_coverage
            and self.environment.acls_lint_enabled
            and self.environment.acls
        ):
            migrations_dir = self.project_dir / "db" / "migrations"
            if migrations_dir.exists():
                grant_dir_str = self.environment.migration.grant_dir
                grant_dir = (self.project_dir / grant_dir_str).resolve()
                for violation in self.lint_migrations(
                    migrations_dir=migrations_dir,
                    expectations=self.environment.acls,
                    grant_dir=grant_dir if grant_dir.exists() else None,
                ).errors:
                    report.add_violation(violation)

        return report

    def _inventory_per_file(self) -> tuple[list[SchemaObject], list[SchemaObject]]:
        """``(objects, CREATE SCHEMA declarations)``, each knowing the file it is in.

        Both empty for a whole-string lint (``lint(schema=...)``), which has no
        files and therefore no locations to report.
        """
        # Reason: import cycle (duplicates imports this module's inventory at module level)
        from confiture.core.linting.duplicates import inventory_files

        if not self._schema_files:
            return [], []
        objects, schemas, _unparseable = inventory_files(self._schema_files, root=self.project_dir)
        return objects, schemas

    def _load_schema(self) -> None:
        """Load schema SQL from files."""
        try:
            builder = _core_builder.SchemaBuilder(env=self.env, project_dir=self.project_dir)
            self._schema_files = builder.find_sql_files()
            self._schema_sql = builder.build()
        except (ConfiturError, OSError) as e:
            logger.error(f"Failed to load schema: {e}")
            self._schema_sql = ""

    def _check_naming_conventions(self, report: LintReport) -> None:
        """Check naming conventions (snake_case for identifiers) on the inventory."""
        for table in distinct(self._inventory.tables):
            if not self._is_snake_case(table.name):
                report.add_violation(
                    LintViolation(
                        rule_id="naming_001",
                        rule_name="Table Naming Convention",
                        severity=RuleSeverity.WARNING,
                        object_type="table",
                        object_name=table.qualified,
                        message=(
                            f"Table name '{table.qualified}' should be lowercase with "
                            "underscores (snake_case)"
                        ),
                        file_path=table.file,
                        line_number=table.line,
                    )
                )
            self._check_column_names(table, report)

    def _check_column_names(self, table: SchemaObject, report: LintReport) -> None:
        """Check column naming conventions in a table."""
        for column in table.columns:
            if not self._is_snake_case(column.name):
                report.add_violation(
                    LintViolation(
                        rule_id="naming_002",
                        rule_name="Column Naming Convention",
                        severity=RuleSeverity.WARNING,
                        object_type="column",
                        object_name=f"{table.qualified}.{column.name}",
                        message=(
                            f"Column '{column.name}' should be lowercase with underscores (snake_case)"
                        ),
                        file_path=table.file,
                        line_number=column.line,
                    )
                )

    def _check_primary_keys(self, report: LintReport) -> None:
        """Every table has a primary key — a partition inherits its parent's."""
        for table in distinct(self._inventory.tables):
            if table.has_primary_key or table.is_partition:
                continue
            if self._is_likely_junction_table(table.name):
                continue
            report.add_violation(
                LintViolation(
                    rule_id="pk_001",
                    rule_name="Missing Primary Key",
                    severity=RuleSeverity.WARNING,
                    object_type="table",
                    object_name=table.qualified,
                    message=f"Table '{table.qualified}' should have a PRIMARY KEY",
                    file_path=table.file,
                    line_number=table.line,
                )
            )

    def _check_documentation(self, report: LintReport) -> None:
        """The ``doc`` family: every commentable object carries a COMMENT (#217)."""
        # Reason: import cycle (the module is partially initialised when this import runs at module level)
        from confiture.core.linting.documentation import documentation_findings

        for violation in documentation_findings(self._inventory):
            report.add_violation(violation)

    def _check_duplicates(self, report: LintReport) -> None:
        """``build_001`` / ``build_002``: an object defined more than once in one build (#218).

        File-backed runs inventory each schema file on its own so a finding can
        name the files; a run on one string reports offsets into that string.
        """
        # Reason: import cycle (the module is partially initialised when this import runs at module level)
        from confiture.core.linting.duplicates import duplicate_violations, find_duplicates

        objects = self._file_objects or self._inventory.objects
        for violation in duplicate_violations(find_duplicates(objects)):
            report.add_violation(violation)

    def _check_qualification(self, report: LintReport) -> None:
        """``qual_001`` / ``qual_002``: a ``CREATE`` that names no schema (#248)."""
        # Reason: import cycle (the module is partially initialised when this import runs at module level)
        from confiture.core.linting.qualification import (
            DIRECTIVE,
            RELATION_KINDS,
            ROUTINE_KINDS,
            qualification_findings,
        )

        kinds: set[str] = set()
        if self.config.check_qualification:
            kinds |= ROUTINE_KINDS
        if self.config.check_qualification_relations:
            kinds |= RELATION_KINDS
        findings = qualification_findings(
            self._file_objects or self._inventory.objects,
            kinds,
            schemas=self._file_schemas or self._inventory.schemas,
            exempt=self._directive_lines(DIRECTIVE),
        )
        for violation in findings:
            report.add_violation(violation)

    def _check_references(self, report: LintReport) -> None:
        """``build_003``: a body names an object no file in the build creates (#246).

        Three tiers, in order (D4): the build inventory, then
        ``lint.ignore_objects``, then — only for what is still outstanding — a
        live database, which is the one thing that can answer for an object
        created by a migration or owned by an extension. A tier that could not
        answer is reported as a degradation rather than left to be read as
        certainty.
        """
        # Reason: import cycle (the module is partially initialised when this import runs at module level)
        from confiture.core.linting.references import referenced_objects

        # Reason: import cycle (unresolved imports LintViolation from this module at module level)
        from confiture.core.linting.unresolved import reference_findings, unresolved_references

        located = [
            (label, reference)
            for label, text in self._sources()
            for reference in referenced_objects(text)
        ]
        candidates = unresolved_references(
            located,
            self._file_objects or self._inventory.objects,
            ignore=self.environment.lint.ignore_objects,
            search_path=self.environment.lint.search_path,
        )
        if candidates:
            candidates = self._after_live_tier(candidates, report)
        for violation in reference_findings(candidates):
            report.add_violation(violation)

    def _check_bodies(self, report: LintReport) -> None:
        """``body_001`` / ``body_002``: what ``plpgsql_check`` says about each body (#245).

        The analysis needs a database, and the extension that does it is in no
        stock PostgreSQL — so the first thing this establishes is whether it can
        run at all, and the answer to "no" is a stated skip rather than an empty
        finding list that reads like a clean bill of health.
        """
        # Reason: CLI start-up: the rules are opt-in, so their import is deferred until one is selected
        from confiture.core.linting import bodies

        server = self._maintenance_server()
        reason = bodies.unavailable(server)
        if reason is not None:
            self._skip_body_rules(report, reason)
            return
        try:
            diagnoses = bodies.diagnose(
                server,
                self._schema_sql or "",
                search_path=self.environment.lint.search_path,
            )
        except (psycopg.Error, OSError, ConfiturError) as exc:
            self._skip_body_rules(report, bodies.BUILD_FAILED + _first_line(exc))
            return
        wanted = set(self._selected_body_rules())
        where = bodies.locations(self._sources())
        for violation in bodies.findings(diagnoses, where):
            if violation.rule_id in wanted:
                report.add_violation(violation)

    def _skip_body_rules(self, report: LintReport, reason: str) -> None:
        """One ``skipped`` entry per selected ``body`` code, all with the same reason."""
        report.skipped.extend(
            RuleStatus(code=code, state="skipped", reason=reason)
            for code in self._selected_body_rules()
        )

    def _maintenance_server(self) -> str:
        """Where the scratch database is built: ``--server-url``, else the env's own.

        The environment's URL names a *server*, and only its server is used —
        :class:`~confiture.core.temp_database.TempDatabase` creates and drops a
        database beside the configured one and never opens it.
        """
        return self.config.server_url or str(self.environment.database_url)

    def _selected_body_rules(self) -> list[str]:
        """The ``body`` codes this run asked for, in catalogue order."""
        # Reason: CLI start-up: the rules are opt-in, so their import is deferred until one is selected
        from confiture.core.linting import bodies

        return [
            code
            for code, wanted in (
                (bodies.RULE_ID, self.config.check_bodies),
                (bodies.WARNING_RULE_ID, self.config.check_body_warnings),
            )
            if wanted
        ]

    def _after_live_tier(
        self,
        candidates: list[tuple[str | None, Any]],
        report: LintReport,
    ) -> list[tuple[str | None, Any]]:
        """*candidates* minus what a live database has, or all of them and a notice.

        The connection is opened only because something was outstanding, and
        with a short timeout: a lint is not the place to wait on a server, and
        a database reachable only through the configured SSH tunnel counts as
        unreachable — deliberately, since starting a tunnel is not what an
        operator asked for by typing ``confiture lint``.
        """
        # Reason: import cycle (unresolved imports LintViolation from this module at module level)
        from confiture.core.linting.unresolved import RULE_ID, probe_live

        search_path = self.environment.lint.search_path
        try:
            live = self._probe(candidates, probe_live, search_path)
        except (psycopg.Error, OSError, ConfiturError) as exc:
            report.degraded.append(
                RuleStatus(
                    code=RULE_ID,
                    state="degraded",
                    reason=(
                        "no database answered, so an object created by a migration or owned "
                        f"by an extension is reported as missing: {_first_line(exc)}"
                    ),
                )
            )
            return candidates
        return [pair for pair in candidates if not live.holds(pair[1], search_path)]

    def _probe(
        self, candidates: list[tuple[str | None, Any]], probe: Any, search_path: Sequence[str]
    ) -> Any:
        """One connection, one round trip, closed before anything else runs."""
        with psycopg.connect(
            str(self.environment.database_url), connect_timeout=_LIVE_TIER_TIMEOUT_S
        ) as connection:
            return probe(connection, candidates, search_path)

    def _sources(self) -> list[tuple[str | None, str]]:
        """``(project-relative label, text)`` per schema file, or the one string linted.

        Every rule that reads the files *as files* — rather than the build they
        concatenate into — needs the same pair, and a whole-string lint
        (``lint(schema=...)``) has no file to name, so its label is ``None``.
        """
        if not self._schema_files:
            return [(None, self._schema_sql or "")]
        return [
            (label_for(path, self.project_dir), path.read_text(encoding="utf-8"))
            for path in self._schema_files
        ]

    def _directive_lines(self, name: str) -> frozenset[tuple[str | None, int]]:
        """``(file, statement line)`` of every statement carrying ``-- confiture:<name>``.

        Read per file, because that is how the objects it exempts are
        identified; a whole-string lint has no files and keys on ``None``. The
        directive attaches to the statement below it, blank lines and other
        comments in between included — :func:`sql_lexer.directives` decides
        that, not a walk of its own.
        """
        return frozenset(
            (label, directive.statement_line)
            for label, text in self._sources()
            for directive in sql_lexer.directives(text)
            if directive.name == name and directive.statement_line is not None
        )

    def _check_indexes(self, _report: LintReport) -> None:
        """Check for indexes on foreign keys.

        Args:
            _report: Report to add violations to
        """
        if not self._schema_sql:
            return

        # Find foreign key definitions
        fk_pattern = r"REFERENCES\s+(\w+)\s*\((\w+)\)"
        fk_matches = list(re.finditer(fk_pattern, self._schema_sql, re.IGNORECASE))

        if not fk_matches:
            return

        # Check for CREATE INDEX statements
        index_pattern = r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+\w+\s+ON\s+(\w+)\s*\(([^)]+)\)"
        indexes = {}

        for match in re.finditer(index_pattern, self._schema_sql, re.IGNORECASE):
            table = match.group(1)
            columns = match.group(2)
            if table not in indexes:
                indexes[table] = []
            indexes[table].append(columns)

        # Warn if foreign keys lack indexes
        # This is simplified - a full implementation would parse more thoroughly
        # For now, just note that checking for indexes on FK columns is important
        for _fk_match in fk_matches:
            pass

    def _check_security(self, report: LintReport) -> None:
        """Columns whose names suggest sensitive data, read from the inventory."""
        security_patterns = [
            (r"password", "password"),
            (r"token", "token"),
            (r"secret", "secret"),
            (r"api_key", "API key"),
            (r"credit_card", "credit card"),
            (r"ssn", "social security number"),
        ]
        for table in self._inventory.tables:
            for column in table.columns:
                for pattern, description in security_patterns:
                    if not re.search(pattern, column.name, re.IGNORECASE):
                        continue
                    report.add_violation(
                        LintViolation(
                            rule_id="sec_001",
                            rule_name="Sensitive Data Column",
                            severity=RuleSeverity.WARNING,
                            object_type="column",
                            object_name=column.name,
                            message=(
                                f"Column '{column.name}' appears to store {description} - "
                                "ensure proper encryption and access controls"
                            ),
                            file_path=table.file,
                            line_number=column.line,
                        )
                    )

    @staticmethod
    def _is_snake_case(identifier: str) -> bool:
        """Check if identifier is in snake_case.

        Args:
            identifier: Identifier to check

        Returns:
            True if identifier is snake_case, False otherwise
        """
        # Allow uppercase letters for backward compatibility with existing code
        # but prefer lowercase
        if identifier != identifier.lower() and "_" not in identifier:
            return False

        # Check that it only contains alphanumeric and underscore
        return bool(re.match(r"^[a-z_][a-z0-9_]*$", identifier, re.IGNORECASE))

    def lint_tree(
        self,
        schema_dir: Path,
        overrides_dir: Path | None = None,
    ) -> LintReport:
        """Lint a schema file tree for structural consistency (``tree_001``–``tree_004``).

        The convenience spelling of
        :func:`~confiture.core.linting.libraries.generate.tree_violations` for a
        caller holding a directory rather than the build's file list: it walks
        *schema_dir* for ``*.sql`` and runs all four rules. A command that knows
        which files the build reads passes them to ``tree_violations`` directly,
        so the environment's exclusions are honoured.

        Args:
            schema_dir: Root of the schema tree to scan.
            overrides_dir: Optional overrides mirror directory (for ``tree_004``).

        Returns:
            LintReport with all violations found.
        """
        # Reason: import cycle (the module is partially initialised when this import runs at module level)
        from confiture.core.linting.libraries.generate import tree_violations

        report = LintReport()
        for violation in tree_violations(
            sorted(f for f in schema_dir.rglob("*.sql") if f.is_file()),
            schema_dirs=[schema_dir],
            overrides_dir=overrides_dir,
        ):
            report.add_violation(violation)
        return report

    def _check_tenant_isolation(self, report: LintReport) -> None:
        """Detect function INSERTs missing tenant FK columns (``tenant_001``).

        Delegates to :class:`TenantIsolationRule`, which parses the built
        schema for tenant-scoped views and the function INSERTs that should
        carry their FK columns. The schema blob holds both, so it is passed
        as both the view and function source.

        Args:
            report: Report to add violations to
        """
        if not self._schema_sql:
            return

        # Reason: import cycle (the module is partially initialised when this import runs at module level)
        from confiture.core.linting.tenant.tenant_isolation_rule import TenantIsolationRule

        TenantIsolationRule().run(
            view_sqls=[self._schema_sql],
            function_sqls=[self._schema_sql],
            report=report,
        )

    def lint_migrations(
        self,
        migrations_dir: Path,
        expectations: list[Any],
        grant_dir: Path | None = None,
    ) -> LintReport:
        """Lint a migrations directory for ACL coverage (ACL001).

        No-op when ``expectations`` is empty — projects without an
        ``acls:`` block see zero violations regardless of what their
        migrations contain.

        Args:
            migrations_dir: Directory of ``*.up.sql`` migration files.
            expectations: Parsed ``acls:`` block (list of
                :class:`~confiture.config.environment.AclExpectation`).
            grant_dir: Optional global grant sweep directory (typically
                ``db/7_grant``).

        Returns:
            :class:`LintReport` with any ACL001 violations.
        """
        # Reason: import cycle (the module is partially initialised when this import runs at module level)
        from confiture.core.linting.libraries.acl import Acl001GrantCoverage

        report = LintReport()
        for violation in Acl001GrantCoverage(expectations=expectations, grant_dir=grant_dir).check(
            migrations_dir
        ):
            report.add_violation(violation)
        return report

    @staticmethod
    def _is_likely_junction_table(table_name: str) -> bool:
        """Check if table looks like a junction/bridge table.

        Args:
            table_name: Name of table to check

        Returns:
            True if table appears to be a junction table
        """
        # Common junction table patterns
        patterns = [
            r"^(.+)_(.+)$",  # Format: singular_singular or table1_table2
            r"^link_",  # Starts with link_
            r"_assoc",  # Ends with _assoc
            r"_join",  # Ends with _join
            r"_rel",  # Ends with _rel
        ]

        # Count underscores - junction tables often have multiple
        if table_name.count("_") >= 2:
            for pattern in patterns:
                if re.match(pattern, table_name, re.IGNORECASE):
                    return True

        return False
