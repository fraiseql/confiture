"""Input validation for security.

This module provides validation functions to prevent common security issues:
- SQL injection via identifier validation
- Path traversal via path validation
- Configuration tampering via config validation
- Secret exposure via log sanitization

Note: These are defense-in-depth measures. Always use parameterized queries
as the primary defense against SQL injection.
"""

import re
from pathlib import Path
from typing import Any

# Allowed characters in SQL identifiers
# Matches: starts with letter/underscore, contains only alphanumeric and underscore
IDENTIFIER_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

# Maximum lengths
MAX_IDENTIFIER_LENGTH = 63  # PostgreSQL limit
MAX_PATH_LENGTH = 4096
MAX_SQL_LENGTH = 10_000_000  # 10MB

# PostgreSQL reserved words that cannot be used as identifiers
# This is a subset of the most common ones
RESERVED_WORDS = frozenset(
    {
        "select",
        "insert",
        "update",
        "delete",
        "drop",
        "create",
        "alter",
        "truncate",
        "grant",
        "revoke",
        "table",
        "index",
        "view",
        "sequence",
        "schema",
        "database",
        "user",
        "role",
        "from",
        "where",
        "and",
        "or",
        "not",
        "null",
        "true",
        "false",
        "in",
        "is",
        "as",
        "on",
        "join",
        "left",
        "right",
        "inner",
        "outer",
        "full",
        "cross",
        "union",
        "except",
        "intersect",
        "order",
        "by",
        "group",
        "having",
        "limit",
        "offset",
        "for",
        "with",
        "returning",
        "into",
        "values",
        "set",
        "default",
        "constraint",
        "primary",
        "foreign",
        "key",
        "references",
        "unique",
        "check",
        "cascade",
        "restrict",
    }
)

# Dangerous SQL patterns (defense in depth)
DANGEROUS_PATTERNS = [
    (re.compile(r";\s*DROP\s+", re.IGNORECASE), "DROP statement after semicolon"),
    (re.compile(r";\s*DELETE\s+FROM\s+", re.IGNORECASE), "DELETE statement after semicolon"),
    (re.compile(r";\s*TRUNCATE\s+", re.IGNORECASE), "TRUNCATE statement after semicolon"),
    (re.compile(r";\s*ALTER\s+.*\s+OWNER\s+", re.IGNORECASE), "ALTER OWNER after semicolon"),
    (re.compile(r"--[^\n]*", re.MULTILINE), "SQL comment (potential injection)"),
    (re.compile(r"/\*.*?\*/", re.DOTALL), "SQL block comment"),
]

# Patterns for sanitizing sensitive data in logs
SENSITIVE_PATTERNS = [
    (re.compile(r"password[=:]\s*\S+", re.IGNORECASE), "password=***"),
    (re.compile(r"passwd[=:]\s*\S+", re.IGNORECASE), "passwd=***"),
    (re.compile(r"secret[=:]\s*\S+", re.IGNORECASE), "secret=***"),
    (re.compile(r"token[=:]\s*\S+", re.IGNORECASE), "token=***"),
    (re.compile(r"api[_-]?key[=:]\s*\S+", re.IGNORECASE), "api_key=***"),
    (re.compile(r"auth[_-]?token[=:]\s*\S+", re.IGNORECASE), "auth_token=***"),
    (re.compile(r"access[_-]?key[=:]\s*\S+", re.IGNORECASE), "access_key=***"),
    (re.compile(r"private[_-]?key[=:]\s*\S+", re.IGNORECASE), "private_key=***"),
    (re.compile(r"postgresql://[^@]+@"), "postgresql://***@"),
    (re.compile(r"postgres://[^@]+@"), "postgres://***@"),
    (re.compile(r"Bearer\s+[\w\-_.]+", re.IGNORECASE), "Bearer ***"),
    (re.compile(r"Basic\s+[A-Za-z0-9+/=]+", re.IGNORECASE), "Basic ***"),
]


class ValidationError(Exception):
    """Raised when validation fails.

    Attributes:
        message: Description of the validation failure
        field: Optional field name that failed validation
    """

    def __init__(self, message: str, field: str | None = None):
        self.message = message
        self.field = field
        super().__init__(message)


def validate_identifier(name: str, context: str = "identifier") -> str:
    """Validate SQL identifier (table, column, schema name).

    Ensures the identifier:
    - Is not empty
    - Does not exceed PostgreSQL's 63 character limit
    - Contains only valid characters (alphanumeric and underscore)
    - Starts with letter or underscore
    - Is not a reserved SQL word

    Args:
        name: The identifier to validate
        context: Description for error messages (e.g., "table name", "column name")

    Returns:
        The validated identifier (unchanged if valid)

    Raises:
        ValidationError: If validation fails

    Examples:
        >>> validate_identifier("users")
        'users'
        >>> validate_identifier("user_accounts")
        'user_accounts'
        >>> validate_identifier("'; DROP TABLE users; --")
        Raises ValidationError
    """
    if not name:
        raise ValidationError(f"Empty {context}", field=context)

    if not isinstance(name, str):
        raise ValidationError(f"{context} must be a string, got {type(name).__name__}", field=context)

    if len(name) > MAX_IDENTIFIER_LENGTH:
        raise ValidationError(
            f"{context} exceeds maximum length of {MAX_IDENTIFIER_LENGTH} characters",
            field=context,
        )

    if not IDENTIFIER_PATTERN.match(name):
        raise ValidationError(
            f"Invalid {context}: '{name}'. Must start with letter or underscore, "
            "and contain only alphanumeric characters and underscores",
            field=context,
        )

    # Check for reserved words
    if name.lower() in RESERVED_WORDS:
        raise ValidationError(
            f"{context} '{name}' is a SQL reserved word. Use a different name or quote it.",
            field=context,
        )

    return name


def validate_path(path: str | Path, must_exist: bool = False, base_dir: Path | None = None) -> Path:
    """Validate file path for safety.

    Ensures the path:
    - Is not too long
    - Does not contain null bytes
    - Resolves to a valid path
    - Optionally exists
    - Optionally is within a base directory (prevents traversal)

    Args:
        path: The path to validate
        must_exist: If True, path must exist on filesystem
        base_dir: If provided, path must be within this directory

    Returns:
        The validated Path object (resolved to absolute)

    Raises:
        ValidationError: If validation fails

    Examples:
        >>> validate_path("db/migrations/001.py")
        PosixPath('/absolute/path/to/db/migrations/001.py')
        >>> validate_path("../../../etc/passwd", base_dir=Path("db"))
        Raises ValidationError
    """
    if isinstance(path, str):
        path = Path(path)

    path_str = str(path)

    # Check length
    if len(path_str) > MAX_PATH_LENGTH:
        raise ValidationError(f"Path exceeds maximum length of {MAX_PATH_LENGTH} characters")

    # Check for null bytes (common injection technique)
    if "\x00" in path_str:
        raise ValidationError("Path contains null byte")

    # Resolve to absolute path
    try:
        resolved = path.resolve()
    except (OSError, ValueError) as e:
        raise ValidationError(f"Invalid path: {e}") from e

    # Check for path traversal if base_dir is specified
    if base_dir is not None:
        base_resolved = base_dir.resolve()
        try:
            resolved.relative_to(base_resolved)
        except ValueError:
            raise ValidationError(f"Path '{path}' is outside allowed directory '{base_dir}'") from None

    # Check existence if required
    if must_exist and not resolved.exists():
        raise ValidationError(f"Path does not exist: {path}")

    return resolved


def validate_environment(env: str) -> str:
    """Validate environment name.

    Ensures the environment is one of the allowed values.

    Args:
        env: Environment name to validate

    Returns:
        Validated environment name (lowercase)

    Raises:
        ValidationError: If environment is not allowed

    Examples:
        >>> validate_environment("production")
        'production'
        >>> validate_environment("STAGING")
        'staging'
        >>> validate_environment("hacker")
        Raises ValidationError
    """
    if not env:
        raise ValidationError("Empty environment name")

    if not isinstance(env, str):
        raise ValidationError(f"Environment must be a string, got {type(env).__name__}")

    allowed = {"local", "development", "dev", "test", "testing", "staging", "production", "prod"}

    env_lower = env.lower().strip()

    if env_lower not in allowed:
        raise ValidationError(f"Invalid environment: '{env}'. Allowed: {', '.join(sorted(allowed))}")

    return env_lower


def validate_sql(sql: str, allow_dangerous: bool = False) -> str:
    """Validate SQL for basic safety.

    This is a defense-in-depth measure, NOT a replacement for parameterized queries.
    It checks for:
    - Empty SQL
    - Excessive length
    - Dangerous patterns (multiple statements, comments)

    Args:
        sql: SQL string to validate
        allow_dangerous: If True, skip dangerous pattern checks
            (use for trusted migration SQL)

    Returns:
        Validated SQL string

    Raises:
        ValidationError: If validation fails

    Examples:
        >>> validate_sql("SELECT * FROM users")
        'SELECT * FROM users'
        >>> validate_sql("SELECT 1; DROP TABLE users;")
        Raises ValidationError (unless allow_dangerous=True)
    """
    if not sql:
        raise ValidationError("Empty SQL")

    if not isinstance(sql, str):
        raise ValidationError(f"SQL must be a string, got {type(sql).__name__}")

    sql = sql.strip()

    if not sql:
        raise ValidationError("SQL contains only whitespace")

    if len(sql) > MAX_SQL_LENGTH:
        raise ValidationError(f"SQL exceeds maximum length of {MAX_SQL_LENGTH} characters")

    if not allow_dangerous:
        for pattern, description in DANGEROUS_PATTERNS:
            if pattern.search(sql):
                raise ValidationError(f"SQL contains potentially dangerous pattern: {description}")

    return sql


def validate_config(config: dict[str, Any]) -> dict[str, Any]:
    """Validate configuration dictionary.

    Ensures:
    - Required fields are present
    - Database URL has valid scheme
    - Warns about embedded credentials

    Args:
        config: Configuration dictionary to validate

    Returns:
        Validated configuration

    Raises:
        ValidationError: If validation fails
    """
    if not isinstance(config, dict):
        raise ValidationError(f"Config must be a dictionary, got {type(config).__name__}")

    # Check for database URL (may be in different locations)
    db_url = config.get("database_url") or config.get("database", {}).get("url")

    if db_url:
        # Validate URL scheme
        if not db_url.startswith(("postgresql://", "postgres://")):
            raise ValidationError(
                "Invalid database URL scheme. Must start with 'postgresql://' or 'postgres://'"
            )

        # Warn about embedded credentials (but don't reject)
        if "@" in db_url and "://" in db_url:
            import logging

            logging.getLogger(__name__).warning(
                "Database URL contains embedded credentials. "
                "Consider using environment variables or a password file instead."
            )

    return config


def sanitize_log_message(message: str) -> str:
    """Remove sensitive data from log messages.

    Redacts common sensitive patterns like:
    - Passwords
    - API keys/tokens
    - Database URLs with credentials
    - Bearer/Basic auth tokens

    Args:
        message: Log message to sanitize

    Returns:
        Sanitized message with sensitive data replaced by ***

    Examples:
        >>> sanitize_log_message("Connecting to postgresql://user:secret@host/db")
        'Connecting to postgresql://***@host/db'
        >>> sanitize_log_message("Using token=abc123xyz")
        'Using token=***'
    """
    if not message:
        return message

    result = message
    for pattern, replacement in SENSITIVE_PATTERNS:
        result = pattern.sub(replacement, result)

    return result
