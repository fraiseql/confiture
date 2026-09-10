"""The error-code catalog as data: one mapping per code, no logic.

``confiture.error_codes`` renders these rows into ``ErrorCodeDefinition`` objects and
the registry; ``tests/unit/test_error_codes_data_table.py`` pins the rows against a
snapshot and keeps this module free of imports and code. Exit codes follow the
canonical convention in ``confiture.error_codes.CANONICAL_EXIT_CODES``.
"""

from __future__ import annotations

ERROR_CODE_DEFINITIONS: tuple[dict[str, str | int | None], ...] = (
    # ========== CONFIG (001-099): Configuration errors → exit code 5 ==========
    {
        "code": "CONFIG_001",
        "message_template": "Missing required field '{field}' in {file}",
        "severity": "error",
        "exit_code": 5,
        "resolution_hint": (
            "Add the field to your config file or set the corresponding environment variable"
        ),
    },
    {
        "code": "CONFIG_002",
        "message_template": "Invalid YAML syntax in {file}",
        "severity": "error",
        "exit_code": 5,
        "resolution_hint": "Check the YAML syntax in your configuration file",
    },
    {
        "code": "CONFIG_003",
        "message_template": "Invalid database URL format",
        "severity": "error",
        "exit_code": 5,
        "resolution_hint": "Use format: postgresql://user:password@host:port/database",
    },
    {
        "code": "CONFIG_004",
        "message_template": "Environment config not found: {env}",
        "severity": "error",
        "exit_code": 5,
        "resolution_hint": "Create configuration file for this environment or use an existing one",
    },
    {
        "code": "CONFIG_006",
        "message_template": "Database connection failed",
        "severity": "error",
        "exit_code": 3,
        "resolution_hint": "Check database URL, host, port, and credentials",
    },
    {
        "code": "CONFIG_007",
        "message_template": (
            "Conflicting explicit DSN sources: an explicit --config/--env and "
            "CONFITURE_DATABASE_URL are both set"
        ),
        "severity": "error",
        "exit_code": 5,
        "resolution_hint": (
            "Pass exactly one explicit source: drop --config/--env, unset "
            "CONFITURE_DATABASE_URL, or pass --no-config to make the env var "
            "authoritative."
        ),
    },
    {
        "code": "CONFIG_008",
        "message_template": "Invalid migration.tracking_table: {value}",
        "severity": "error",
        "exit_code": 5,
        "resolution_hint": (
            "Use letters, digits and underscores only, optionally "
            "schema-qualified (e.g. public.tb_confiture)"
        ),
    },
    {
        "code": "CONFIG_009",
        "message_template": "Anonymization secret not set ({env_var})",
        "severity": "error",
        "exit_code": 5,
        "resolution_hint": (
            "Export ANONYMIZATION_SECRET to a long random string kept out of "
            "version control before running an anonymizing sync or a keyed hash "
            "strategy"
        ),
    },
    # ========== MIGR (100-199): Migration execution errors → exit code 3 ==========
    {
        "code": "MIGR_100",
        "message_template": "Migration {version} not found",
        "severity": "error",
        "exit_code": 3,
        "resolution_hint": "Check the migration version and ensure the file exists",
    },
    {
        "code": "MIGR_101",
        "message_template": "Migration {version} already applied",
        "severity": "warning",
        "exit_code": 0,
        "resolution_hint": "This migration has already been applied to the database",
    },
    {
        "code": "MIGR_102",
        "message_template": "Migration file corrupted: {file}",
        "severity": "error",
        "exit_code": 3,
        "resolution_hint": "Regenerate or restore the migration file",
    },
    {
        "code": "MIGR_106",
        "message_template": "Duplicate migration version: {version}",
        "severity": "error",
        "exit_code": 3,
        "resolution_hint": (
            "Multiple migration files share the same version number. Rename files "
            "to use unique version prefixes. Run 'confiture migrate validate' to "
            "see all duplicates."
        ),
    },
    {
        "code": "MIGR_107",
        "message_template": (
            "Migration {version} ({name}) issued an explicit COMMIT or ROLLBACK "
            "in its body, breaking confiture's transaction envelope"
        ),
        "severity": "error",
        "exit_code": 3,
        "resolution_hint": (
            "Remove any explicit COMMIT or ROLLBACK from the migration body. "
            "Confiture manages the outer transaction; embedded transaction "
            "control leaves the database in an unrecoverable state if a "
            "subsequent statement fails. If you need autocommit semantics, set "
            "transactional = False on the migration."
        ),
    },
    {
        "code": "MIGR_108",
        "message_template": (
            "Migration {version} is non-transactional and cannot run with "
            "commit=False (inside a SAVEPOINT)"
        ),
        "severity": "error",
        "exit_code": 3,
        "resolution_hint": (
            "A non-transactional migration commits the current transaction and "
            "runs in autocommit, so it cannot be tested inside a SAVEPOINT. "
            "`session.up(dry_run_execute=True)` skips such migrations; apply them "
            "for real with `migrate up`."
        ),
    },
    # ========== SCHEMA (200-299): Schema DDL and build errors → exit code 4 ==========
    {
        "code": "DDL_001",
        "message_template": "Destructive DDL operation refused without --force: {operation}",
        "severity": "error",
        "exit_code": 4,
        "resolution_hint": "Re-run with --force if the destructive change is intended",
    },
    {
        "code": "SCHEMA_201",
        "message_template": "Schema directory not found: {directory}",
        "severity": "error",
        "exit_code": 4,
        "resolution_hint": "Create the schema directory or check the path",
    },
    {
        "code": "SCHEMA_202",
        "message_template": "Circular dependency detected",
        "severity": "error",
        "exit_code": 4,
        "resolution_hint": "Break the circular dependency between schema files",
    },
    {
        "code": "SCHEMA_205",
        "message_template": "psql meta-command in {file} at line {line}",
        "severity": "error",
        "exit_code": 4,
        "resolution_hint": (
            "Remove the backslash commands; only SQL statements and inline COPY … "
            "FROM stdin data blocks are applied"
        ),
    },
    {
        "code": "SCHEMA_206",
        "message_template": "{file}: pglast could not parse it — not checked for duplicates",
        "severity": "warning",
        "exit_code": 0,
        "resolution_hint": (
            "Fix the file's syntax or exclude it from the build; the duplicate scan "
            "skipped it, so an object it defines twice is not reported"
        ),
    },
    # ========== DIFFER (400-499): Schema diff detection errors → exit code 5 ==========
    {
        "code": "DIFFER_400",
        "message_template": "Cannot parse SQL DDL",
        "severity": "error",
        "exit_code": 5,
        "resolution_hint": "Fix the SQL syntax in your schema files",
    },
    {
        "code": "DIFFER_401",
        "message_template": "Destructive change forbidden by policy",
        "severity": "error",
        "exit_code": 5,
        "resolution_hint": "Re-run with --allow-destructive, or set migration.destructive to gated or allow",
    },
    # ========== ROLLBACK (600-699): Rollback errors → exit code 8 ==========
    {
        "code": "ROLLBACK_600",
        "message_template": "Cannot rollback: irreversible change",
        "severity": "critical",
        "exit_code": 8,
        "resolution_hint": "Manual intervention required; cannot automatically rollback",
    },
    # ========== PGGIT (900-999): pgGit integration errors → exit code 7 ==========
    {
        "code": "PGGIT_900",
        "message_template": "pgGit command failed",
        "severity": "error",
        "exit_code": 7,
        "resolution_hint": "Check pgGit is installed and configured",
    },
    # ========== PRECON (1000-1099): Precondition errors → exit code 5 ==========
    {
        "code": "PRECON_1000",
        "message_template": "Precondition not met: {condition}",
        "severity": "error",
        "exit_code": 5,
        "resolution_hint": "Ensure the precondition is satisfied before retrying",
    },
    {
        "code": "PRECON_1001",
        "message_template": "Database not initialized",
        "severity": "error",
        "exit_code": 2,
        "resolution_hint": "Run 'confiture init' to initialize the database",
    },
    # ========== LOCK (1300-1399): Database locking errors → exit code 6 ==========
    {
        "code": "LOCK_1300",
        "message_template": "Cannot acquire database lock",
        "severity": "error",
        "exit_code": 6,
        "resolution_hint": "Wait for other operations to complete",
    },
    # ========== ANON (1400-1499): Anonymization errors → exit code 5 ==========
    {
        "code": "ANON_1400",
        "message_template": "Invalid anonymization rule",
        "severity": "error",
        "exit_code": 5,
        "resolution_hint": "Check anonymization rule syntax",
    },
    # ========== MIGR extra: granular migration execution codes ==========
    {
        "code": "CONFIG_010",
        "message_template": "Database URL not set in environment '{env}'",
        "severity": "error",
        "exit_code": 5,
        "resolution_hint": (
            "Set database_url in db/environments/{env}.yaml or DATABASE_URL environment variable"
        ),
    },
    {
        "code": "CONFIG_011",
        "message_template": (
            "pglast {version} does not expose {members}; confiture cannot walk DDL with it"
        ),
        "severity": "error",
        "exit_code": 5,
        "resolution_hint": (
            "Install a pglast release confiture supports (pglast>=6.0, current major)"
        ),
    },
    {
        "code": "CONFIG_012",
        "message_template": "Lint baseline file is missing or malformed: {file}",
        "severity": "error",
        "exit_code": 5,
        "resolution_hint": (
            "Create or regenerate it with `confiture lint --baseline <file> --write-baseline`"
        ),
    },
    # ========== Default error codes for exception types ==========
    # These are the base codes used as defaults in exception __init__ methods.
    # More specific codes (e.g., MIGR_100, SCHEMA_201) are used at raise sites.
    {
        "code": "MIGR_001",
        "message_template": "Migration error",
        "severity": "error",
        "exit_code": 3,
        "resolution_hint": "Check migration files and database state",
    },
    {
        "code": "MIGR_004",
        "message_template": "Migration file already exists",
        "severity": "error",
        "exit_code": 3,
        "resolution_hint": "Use --force flag to overwrite existing file",
    },
    {
        "code": "SCHEMA_001",
        "message_template": "Schema error",
        "severity": "error",
        "exit_code": 4,
        "resolution_hint": "Check SQL DDL files for errors",
    },
    {
        "code": "SYNC_001",
        "message_template": "Sync error",
        "severity": "error",
        "exit_code": 5,
        "resolution_hint": "Check source and target database connections",
    },
    {
        "code": "DIFF_001",
        "message_template": "Schema diff error",
        "severity": "error",
        "exit_code": 5,
        "resolution_hint": "Check SQL DDL for parsing issues",
    },
    {
        "code": "VALID_001",
        "message_template": "Validation error",
        "severity": "error",
        "exit_code": 5,
        "resolution_hint": "Check validation rules and data integrity",
    },
    {
        "code": "VALID_002",
        "message_template": "Destructive migration refused: data is lost when it applies",
        "severity": "error",
        "exit_code": 5,
        "resolution_hint": "Review the migration, then run migrate up --allow-destructive",
    },
    {
        "code": "VERIFY_001",
        "message_template": "Verify file contains forbidden SQL",
        "severity": "error",
        "exit_code": 5,
        "resolution_hint": "Verify files must only contain SELECT queries",
    },
    {
        "code": "ROLLBACK_001",
        "message_template": "Rollback error",
        "severity": "critical",
        "exit_code": 8,
        "resolution_hint": "Check rollback SQL and database state",
    },
    {
        "code": "SQL_001",
        "message_template": "SQL execution error",
        "severity": "error",
        "exit_code": 1,
        "resolution_hint": "Check the SQL statement for errors",
    },
    {
        "code": "GIT_001",
        "message_template": "Git operation error",
        "severity": "error",
        "exit_code": 7,
        "resolution_hint": "Check git repository status",
    },
    {
        "code": "GIT_002",
        "message_template": "Not a git repository",
        "severity": "error",
        "exit_code": 7,
        "resolution_hint": "Initialize a git repository or use a valid repository path",
    },
    {
        "code": "GIT_003",
        "message_template": "Base ref unreachable in this checkout",
        "severity": "error",
        "exit_code": 7,
        "resolution_hint": (
            "In CI, set fetch-depth: 0 (actions/checkout) or run 'git fetch "
            "--unshallow origin <branch>'"
        ),
    },
    {
        "code": "GRANT_001",
        "message_template": "Grant accompaniment error",
        "severity": "error",
        "exit_code": 7,
        "resolution_hint": "Stage a migration file alongside grant changes",
    },
    {
        "code": "GEN_001",
        "message_template": "External generator error",
        "severity": "error",
        "exit_code": 3,
        "resolution_hint": "Check the external generator command and its output",
    },
    {
        "code": "REBUILD_001",
        "message_template": "Schema rebuild error",
        "severity": "error",
        "exit_code": 4,
        "resolution_hint": "Check schema DDL and database state",
    },
    {
        "code": "RESTORE_001",
        "message_template": "Restore error",
        "severity": "error",
        "exit_code": 5,
        "resolution_hint": "Check backup format and pg_restore availability",
    },
    {
        "code": "SEED_001",
        "message_template": "Seed execution error",
        "severity": "error",
        "exit_code": 5,
        "resolution_hint": "Check seed file syntax and database state",
    },
    {
        "code": "SEED_002",
        "message_template": "{count} seed file(s) failed",
        "severity": "warning",
        "exit_code": 0,
        "resolution_hint": (
            "The build continued because --continue-on-error (or seed.continue_on_error) "
            "is set; re-run without it to stop at the first failure"
        ),
    },
    {
        "code": "SEED_003",
        "message_template": "No seed files found for environment '{env}'",
        "severity": "info",
        "exit_code": 0,
        "resolution_hint": (
            "Add seed files under the environment's seed directory, or drop --sequential"
        ),
    },
)
