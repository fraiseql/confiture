"""Enhanced error context system for user-friendly error messages.

Provides detailed error explanations with solutions and helpful guidance.
"""

from dataclasses import dataclass


@dataclass
class ErrorContext:
    """Structured error information with solutions.

    Attributes:
        error_code: Unique identifier (e.g., "DB_CONNECTION_FAILED")
        message: Brief error message for users
        cause: What caused the error
        solutions: Step-by-step how to fix it
        examples: Real command examples
        docs_url: Link to documentation
        severity: "error" | "warning"
    """

    error_code: str
    message: str
    cause: str
    solutions: list[str]
    examples: list[str]
    docs_url: str
    severity: str = "error"


# Common error contexts
ERROR_CONTEXTS = {
    "DB_CONNECTION_FAILED": ErrorContext(
        error_code="DB_CONNECTION_FAILED",
        message="Database connection failed",
        cause="Cannot reach PostgreSQL database at the specified URL",
        solutions=[
            "Verify PostgreSQL is running: pg_isready localhost",
            "Check your DATABASE_URL or --database-url parameter",
            "Verify username/password: psql -U postgres",
            "Check network connectivity: ping localhost",
            "For remote databases: check firewall rules",
        ],
        examples=[
            "confiture build --database-url postgresql://localhost/mydb",
            "export DATABASE_URL=postgresql://user:pass@localhost/mydb",
        ],
        docs_url="https://github.com/fraiseql/confiture/blob/main/docs/troubleshooting.md#connection-issues",
    ),
    "DB_PERMISSION_DENIED": ErrorContext(
        error_code="DB_PERMISSION_DENIED",
        message="Database permission denied",
        cause="User lacks required permissions for the operation",
        solutions=[
            "Connect as a privileged user: psql -U postgres",
            "Grant permissions: ALTER USER myuser CREATEDB;",
            "For migrations: ensure user can write to confiture_migrations table",
            "Check database ownership: \\l in psql",
        ],
        examples=[
            "psql -U postgres -c 'ALTER USER myuser CREATEDB;'",
        ],
        docs_url="https://github.com/fraiseql/confiture/blob/main/docs/troubleshooting.md#connection-issues",
    ),
    "SEEDS_DIR_NOT_FOUND": ErrorContext(
        error_code="SEEDS_DIR_NOT_FOUND",
        message="Seeds directory not found",
        cause="The specified seed directory doesn't exist or is not readable",
        solutions=[
            "Create the directory: mkdir -p db/seeds/common",
            "Check directory name spelling and path",
            "Use --seeds-dir to specify a different path",
            "Verify permissions: ls -la db/seeds",
        ],
        examples=[
            "confiture seed apply --seeds-dir db/seeds/common",
            "confiture init  # Create standard project structure",
        ],
        docs_url="https://github.com/fraiseql/confiture/blob/main/docs/error-reference.md#seeds_dir_not_found",
    ),
    "MIGRATIONS_DIR_NOT_FOUND": ErrorContext(
        error_code="MIGRATIONS_DIR_NOT_FOUND",
        message="Migrations directory not found",
        cause="The migrations directory doesn't exist",
        solutions=[
            "Create migrations directory: mkdir -p db/migrations",
            "Use confiture init to create standard structure",
            "Check path spelling: db/migrations vs db/migration",
            "Verify permissions: ls -la db/",
        ],
        examples=[
            "mkdir -p db/migrations",
            "confiture init",
        ],
        docs_url="https://github.com/fraiseql/confiture/blob/main/docs/error-reference.md#migrations_dir_not_found",
    ),
    "SCHEMA_DIR_NOT_FOUND": ErrorContext(
        error_code="SCHEMA_DIR_NOT_FOUND",
        message="Schema directory not found",
        cause="The schema directory doesn't exist",
        solutions=[
            "Create schema directory: mkdir -p db/schema",
            "Use confiture init to create project structure",
            "Add SQL files to db/schema/",
            "Verify directory permissions",
        ],
        examples=[
            "mkdir -p db/schema/10_tables",
            "confiture init",
        ],
        docs_url="https://github.com/fraiseql/confiture/blob/main/docs/error-reference.md#schema_dir_not_found",
    ),
    "MIGRATION_CONFLICT": ErrorContext(
        error_code="MIGRATION_CONFLICT",
        message="Migration conflict detected",
        cause="Multiple migrations with same version or conflicting changes",
        solutions=[
            "Check for duplicate version numbers: ls -1 db/migrations/ | grep -E '^[0-9]{3}_'",
            "Rename conflicting migration to next version",
            "Use confiture migrate status to see all versions",
            "Review git history to understand conflict origin",
        ],
        examples=[
            "confiture migrate status",
            "mv db/migrations/002_feature.sql db/migrations/004_feature.sql",
        ],
        docs_url="https://github.com/fraiseql/confiture/blob/main/docs/error-reference.md#migration_conflict",
    ),
    "SEED_VALIDATION_FAILED": ErrorContext(
        error_code="SEED_VALIDATION_FAILED",
        message="Seed validation failed",
        cause="Seed files contain issues (DDL, double semicolons, etc)",
        solutions=[
            "Review error messages above for specific issues",
            "Remove DDL statements (CREATE/ALTER/DROP) from seeds",
            "Fix double semicolons (;;)",
            "Add missing ON CONFLICT clauses for UPSERTs",
            "Use confiture seed validate --fix to auto-correct",
        ],
        examples=[
            "confiture seed validate --format json --output report.json",
            "confiture seed validate --fix --dry-run",
        ],
        docs_url="https://github.com/fraiseql/confiture/blob/main/docs/error-reference.md#seed_validation_failed",
    ),
    "SQL_SYNTAX_ERROR": ErrorContext(
        error_code="SQL_SYNTAX_ERROR",
        message="SQL syntax error in migration or schema",
        cause="One or more SQL statements contain syntax errors",
        solutions=[
            "Review the SQL file at the specified location",
            "Check for common issues: missing semicolons, unclosed parentheses",
            "Validate SQL syntax using: psql -f file.sql --check",
            "Use a SQL editor with syntax highlighting to identify errors",
            "Test SQL statements in psql before adding to migrations",
        ],
        examples=[
            "psql -U postgres -d mydb -f migration.sql",
            "psql --echo-errors -f migration.sql",
        ],
        docs_url="https://github.com/fraiseql/confiture/blob/main/docs/error-reference.md#sql_syntax_error",
    ),
    "TABLE_ALREADY_EXISTS": ErrorContext(
        error_code="TABLE_ALREADY_EXISTS",
        message="Table already exists in database",
        cause="Migration or schema tries to create a table that already exists",
        solutions=[
            "Use CREATE TABLE IF NOT EXISTS instead of CREATE TABLE",
            "Check if migration has already been applied: confiture migrate status",
            "If migration was partial, use confiture migrate rollback",
            "Review migration order to avoid duplicate creates",
        ],
        examples=[
            "confiture migrate status",
            "CREATE TABLE IF NOT EXISTS users (...)",
            "confiture migrate rollback --version 001",
        ],
        docs_url="https://github.com/fraiseql/confiture/blob/main/docs/error-reference.md#table_already_exists",
    ),
    "FOREIGN_KEY_CONSTRAINT": ErrorContext(
        error_code="FOREIGN_KEY_CONSTRAINT",
        message="Foreign key constraint violation",
        cause="Data violates foreign key constraints (missing referenced row)",
        solutions=[
            "Verify referenced table and column exist",
            "Check data in seed files matches references",
            "Load parent table data before child table",
            "Use DEFERRABLE INITIALLY DEFERRED for circular references",
            "Disable constraints temporarily if needed: ALTER TABLE ... DISABLE TRIGGER ALL",
        ],
        examples=[
            "confiture seed validate --format json",
            "ALTER TABLE orders DISABLE TRIGGER ALL;",
            "ALTER TABLE orders ENABLE TRIGGER ALL;",
        ],
        docs_url="https://github.com/fraiseql/confiture/blob/main/docs/error-reference.md#foreign_key_constraint",
    ),
    "INSUFFICIENT_DISK_SPACE": ErrorContext(
        error_code="INSUFFICIENT_DISK_SPACE",
        message="Insufficient disk space for operation",
        cause="Database or filesystem is out of space",
        solutions=[
            "Check available disk space: df -h",
            "Check PostgreSQL data directory: du -sh /var/lib/postgresql/",
            "Clean up old backups or unused data",
            "Free up disk space before retrying operation",
            "For large operations, consider splitting into smaller batches",
        ],
        examples=[
            "df -h /var/lib/postgresql/",
            "du -sh /var/lib/postgresql/*/base/*",
        ],
        docs_url="https://github.com/fraiseql/confiture/blob/main/docs/error-reference.md#insufficient_disk_space",
    ),
    "LOCK_TIMEOUT": ErrorContext(
        error_code="LOCK_TIMEOUT",
        message="Lock acquisition timeout",
        cause="Another operation is holding locks on tables (migration conflict)",
        solutions=[
            "Check active database connections: SELECT * FROM pg_stat_activity;",
            "Increase lock timeout: SET lock_timeout = '10s';",
            "Terminate blocking connections: SELECT pg_terminate_backend(pid);",
            "Retry migration after other operations complete",
            "Use --skip-lock-check flag if appropriate for your use case",
        ],
        examples=[
            "confiture migrate up --timeout 30s",
            "psql -c \"SELECT * FROM pg_stat_activity WHERE state = 'active';\"",
        ],
        docs_url="https://github.com/fraiseql/confiture/blob/main/docs/error-reference.md#lock_timeout",
    ),
}


def get_error_context(error_code: str) -> ErrorContext | None:
    """Get enhanced error context by code.

    Args:
        error_code: Error code (e.g., "DB_CONNECTION_FAILED")

    Returns:
        ErrorContext with solutions, or None if not found
    """
    return ERROR_CONTEXTS.get(error_code)


def format_error_with_context(error_code: str, custom_message: str | None = None) -> str:
    """Format error message with solutions.

    Args:
        error_code: Error code key
        custom_message: Override the default message

    Returns:
        Formatted error message with solutions
    """
    context = get_error_context(error_code)
    if not context:
        return custom_message or error_code

    lines = [
        f"❌ {custom_message or context.message}",
        "",
        "📋 CAUSE:",
        f"  {context.cause}",
        "",
        "✅ HOW TO FIX:",
    ]

    for i, solution in enumerate(context.solutions, 1):
        lines.append(f"  {i}. {solution}")

    if context.examples:
        lines.extend(["", "💡 EXAMPLES:"])
        for example in context.examples:
            lines.append(f"  $ {example}")

    lines.extend(
        [
            "",
            "📚 LEARN MORE:",
            f"  {context.docs_url}",
        ]
    )

    return "\n".join(lines)
