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
from typing import TYPE_CHECKING, Any

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
from confiture.core.linting.rule_registry import LINT_RULES, UNPARSEABLE_RULE_ID
from confiture.core.sql_lexer import blank_copy_blocks, blank_preserving_lines
from confiture.exceptions import ConfiturError

if TYPE_CHECKING:
    from confiture.core.linting.duplicates import Rejected

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
    #: What the ``doc`` family measured, when it ran: how much of the schema
    #: carries a comment and how long those comments are (#250). ``None`` when
    #: the family was not selected — absent, not zero.
    documentation: dict[str, Any] | None = None
    #: ``(file, line)`` of every ``UNPARSEABLE`` already held. Six rules open
    #: files of their own, so one broken file used to be reported by each of
    #: them *and* by the build — several identical errors about one fact. The
    #: notice is about the file, not about the rule that happened to find it.
    _unparseable_seen: set[tuple[str | None, int | None]] = field(default_factory=set)

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
        """Add a violation to the report, keeping one ``UNPARSEABLE`` per file."""
        if violation.rule_id == UNPARSEABLE_RULE_ID:
            seen = (violation.file_path, violation.line_number)
            if seen in self._unparseable_seen:
                return
            self._unparseable_seen.add(seen)
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
        check_restatements: bool = False,
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
            check_restatements: Report a COMMENT that says only what the object's
                name already says (``doc_005``). Off by default, like the rule:
                it is a heuristic and a correct comment that happens to restate
                the name is a false positive.
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
        self.check_restatements = check_restatements
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

        # Schema cache. Two strings, deliberately, and they are not
        # interchangeable (#274):
        #   `_schema_sql` is the build as `SchemaBuilder` produced it, COPY
        #     rows and all. It is what gets materialised into a database
        #     (`bodies.diagnose`) or scanned as text (`tenant_001`).
        #   `_parse_sql` is what pglast is asked to read: the same files with
        #     their COPY blocks blanked, assembled by `_assemble_parse_text`.
        # Handing the first to pglast reads nothing; handing the second to a
        # database drops the seed rows.
        self._schema_sql: str | None = None
        self._parse_sql: str = ""
        self._inventory: Inventory = Inventory()
        self._tables: dict[str, dict[str, Any]] | None = None
        self._schema_files: list[Path] = []
        self._file_objects: list[SchemaObject] = []
        self._file_schemas: list[SchemaObject] = []
        self._source_cache: list[tuple[str | None, str]] | None = None

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

        self._source_cache = None
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
        self._file_objects, self._file_schemas, rejected = self._inventory_per_file()
        self._parse_sql = self._assemble_parse_text({r.label for r in rejected})
        self._report_rejected_files(report, rejected)
        try:
            self._inventory = build_inventory(self._parse_sql)
            attribute_files(self._inventory, self._file_objects)
        except pglast.parser.ParseError as exc:
            # A file-backed run has already reported each rejected file by name
            # above; reaching here means the *concatenation* failed, or there
            # were no files at all — `lint(schema=...)`, which has none to name.
            self._add_unparseable(report, None, self._parse_sql, exc)

        report.tables_checked = len(self._inventory.tables)
        report.columns_checked = sum(len(t.columns) for t in self._inventory.tables)

        # One table rather than a chain of ifs: a rule is its switch and its
        # method, and adding one is a row.
        #
        # Deliberately keyed on switches and not on rule codes, which is the
        # question a reader arrives with now that the registry is the single
        # source of truth for what a rule is. One method serves several codes
        # (`_check_documentation` emits doc_001 through doc_004), two switches
        # share one method (qual_001 and qual_002), and `LintConfig` is the
        # library API — a caller sets `check_documentation=True`, not a set of
        # codes. Keying this on the registry would mean either running a method
        # once per code it emits, or putting a method name in the catalogue
        # `--list-rules` publishes. Per-code selection happens where it belongs,
        # on the findings, in `_keep_selected_rules`.
        #
        # What the two tables owe each other is agreement, and two guards hold
        # it: `test_every_rule_is_registered` (no rule emits without an entry)
        # and `test_every_switch_has_a_rule` (no switch runs without a rule).
        # The third column is the rule family the switch runs, and it is on the
        # row rather than in a table of its own so a new rule cannot be added
        # without answering "what does this lose when a file will not parse".
        # `None` means the answer is "nothing an unread file explains": the
        # `body` family degrades on its live tier, and `tenant_001` parses the
        # build itself and reports its own notice when that fails.
        ran: set[str] = set()
        for enabled, check, family in (
            (self.config.check_naming, self._check_naming_conventions, "naming"),
            (self.config.check_primary_keys, self._check_primary_keys, "pk"),
            (self.config.check_documentation, self._check_documentation, "doc"),
            (self.config.check_restatements, self._check_restatements, "doc"),
            (self.config.check_security, self._check_security, "security"),
            (self.config.check_duplicates, self._check_duplicates, "build"),
            (
                self.config.check_qualification or self.config.check_qualification_relations,
                self._check_qualification,
                "qual",
            ),
            (self.config.check_references, self._check_references, "build"),
            (
                self.config.check_bodies or self.config.check_body_warnings,
                self._check_bodies,
                None,
            ),
            (self.config.check_tenant_isolation, self._check_tenant_isolation, None),
        ):
            if enabled:
                check(report)
                if family is not None:
                    ran.add(family)
        self._report_blinded_rules(report, ran, rejected)

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

    def _inventory_per_file(
        self,
    ) -> tuple[list[SchemaObject], list[SchemaObject], list[Rejected]]:
        """``(objects, CREATE SCHEMA declarations, rejected files)``, each knowing its file.

        The first two are empty for a whole-string lint (``lint(schema=...)``),
        which has no files and therefore no locations to report.

        The third used to be discarded here, which is how a broken file could
        cost the whole build: the per-file pass already knew exactly which file
        pglast refused, and threw that away, leaving the whole-build parse to
        fail on it and take the other files' objects with it (#274).
        """
        # Reason: import cycle (duplicates imports this module's inventory at module level)
        from confiture.core.linting.duplicates import inventory_texts

        if not self._schema_files:
            return [], [], []
        return inventory_texts(self._sources())

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
        from confiture.core.linting.documentation import (
            documentation_findings,
            documentation_summary,
        )

        for violation in documentation_findings(self._inventory):
            report.add_violation(violation)
        report.documentation = documentation_summary(self._inventory)

    def _check_restatements(self, report: LintReport) -> None:
        """``doc_005``: a COMMENT that says only what the object's name says (#250)."""
        # Reason: import cycle (the module is partially initialised when this import runs at module level)
        from confiture.core.linting.documentation import restatement_findings

        for violation in restatement_findings(self._inventory):
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
        from confiture.core.linting.references import read_references

        # Reason: import cycle (unresolved imports LintViolation from this module at module level)
        from confiture.core.linting.unresolved import reference_findings, unresolved_references

        scans = [(label, read_references(text)) for label, text in self._sources()]
        located = [(label, reference) for label, scan in scans for reference in scan.references]
        self._report_unread_bodies(scans, report)
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

    @staticmethod
    def _report_unread_bodies(scans: list[tuple[str | None, Any]], report: LintReport) -> None:
        """Name the routines whose bodies no parser would return.

        `build_003` subtracts what a body names from what the build creates, so
        a body it never read contributes no names and the rule says nothing
        about it. Saying nothing and finding nothing are the same output and a
        different fact, which is what `degraded` exists to separate.
        """
        # Reason: import cycle (unresolved imports LintViolation from this module at module level)
        from confiture.core.linting.unresolved import RULE_ID

        unread = sorted({name for _label, scan in scans for name in scan.unread})
        if not unread:
            return
        body = "body" if len(unread) == 1 else "bodies"
        report.degraded.append(
            RuleStatus(
                code=RULE_ID,
                state="degraded",
                reason=(
                    f"could not read {len(unread)} routine {body}, so the objects "
                    f"they name are not checked: {', '.join(unread)}"
                ),
            )
        )

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

        The text is **blanked**: a ``COPY … FROM stdin`` block is psql client
        protocol and pglast rejects the text it sits in, so one seed file used
        to empty the inventory (#274). Blanking keeps every offset and every
        line number, so a finding still points at the line its author wrote —
        which deleting the block would not (:func:`sql_lexer.blank_copy_blocks`).

        Read once per lint and held: six rules want it, and a schema tree is
        thousands of files. ``lint()`` clears it, so a reused linter still sees
        what is on disk now.
        """
        if self._source_cache is None:
            self._source_cache = (
                [(None, blank_copy_blocks(self._schema_sql or ""))]
                if not self._schema_files
                else [
                    (
                        label_for(path, self.project_dir),
                        blank_copy_blocks(path.read_text(encoding="utf-8")),
                    )
                    for path in self._schema_files
                ]
            )
        return self._source_cache

    @staticmethod
    def _report_rejected_files(report: LintReport, rejected: list[Rejected]) -> None:
        """One ``UNPARSEABLE`` finding per file pglast refused, naming that file.

        Before #274 there was one notice for the whole build, carrying no file
        and a line into a generated artefact — which was all the whole-build
        parse could say, because it failed as a unit.
        """
        for rejection in rejected:
            SchemaLinter._add_unparseable(
                report, Path(rejection.label), rejection.text, rejection.error
            )

    @staticmethod
    def _report_blinded_rules(
        report: LintReport, ran: frozenset[str] | set[str], rejected: list[Rejected]
    ) -> None:
        """Say which rules read less of the schema than the build contains.

        A rejected file is missing from *both* object lists — the whole-build
        inventory never saw it, and `inventory_texts` skips it, so the per-file
        list has none of its objects either. So every rule whose subject is DDL
        examined a short schema, `build_001` and `qual_001` included; the first
        draft of this exempted them, and a duplicate defined in the broken file
        then went unreported with nothing saying so.

        This is the channel a `--baseline` does not touch (D6): a project can
        record the `UNPARSEABLE` finding as known, and the blindness still says
        so on every run.
        """
        if not rejected:
            return
        files = ", ".join(sorted(r.label for r in rejected))
        one = len(rejected) == 1
        were = "file was" if one else "files were"
        define = "it defines or references" if one else "they define or reference"
        report.degraded.extend(
            RuleStatus(
                code=rule.code,
                state="degraded",
                reason=(
                    f"{len(rejected)} {were} not read, so nothing {define} is checked ({files})"
                ),
            )
            for rule in LINT_RULES
            if rule.family in ran
        )

    @staticmethod
    def _add_unparseable(
        report: LintReport, path: Path | None, text: str, exc: BaseException
    ) -> None:
        """One constructor for the notice, reached from both of this module's sites."""
        # Reason: import cycle (unparseable imports LintViolation from this module)
        from confiture.core.linting.unparseable import unparseable_notice

        report.add_violation(unparseable_notice(path, text, exc))

    def _assemble_parse_text(self, rejected: set[str]) -> str:
        """The text pglast is asked to read — the blanked files, concatenated.

        A file in ``rejected`` contributes its own length in spaces and nothing
        else. That is what makes a broken file cost one file: the remaining
        files still parse as *one* text, so a ``COMMENT ON`` in one of them
        still resolves against a ``CREATE`` in another — which is the only
        reason a whole-build inventory exists beside the per-file one.

        Deliberately **not** ``self._schema_sql``. The three things
        ``SchemaBuilder.build`` adds — a header, a per-file separator, and the
        ``build.two_pass`` FK rewrite — reach no rule: the inventory reads
        ``CREATE`` statements, their columns and their primary keys, and
        two-pass moves only foreign keys. What assembling it here buys is worth
        more than byte-equality with an artefact nobody edits:

        * the whole-build inventory and the per-file inventory then walk the
          same statements in the same order *by construction*, which is what
          :func:`attribute_files` needs and cannot check — it zips positionally
          and stops at the first disagreement;
        * every file's span in this text is known, because this laid it out.

        ``_schema_sql`` keeps the real build, COPY rows and all, for the two
        consumers that want it: ``bodies.diagnose()`` materialises it into a
        throwaway database, and ``tenant_001`` scans it as text.
        """
        parts: list[str] = []
        for label, text in self._sources():
            parts.append(blank_preserving_lines(text) if label in rejected else text)
            if text and not text.endswith("\n"):
                parts.append("\n")
        return "".join(parts)

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
