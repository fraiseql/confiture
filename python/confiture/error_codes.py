"""Error code registry and definitions for structured error handling.

This module provides a central registry of error codes that enables deterministic
error handling in agent workflows while maintaining backward compatibility.

Error codes follow the format: CATEGORY_NNN where:
- CATEGORY is a 3-6 letter category name (CONFIG, MIGR, SCHEMA, etc.)
- NNN is a 3-digit number within the category (001-999)

Categories and their exit codes (the #146 stabilized convention; see
docs/reference/exit-codes.md and CANONICAL_EXIT_CODES below for the contract):
- CONFIG (001-099): Configuration errors → exit code 5
    (carve-out: CONFIG_006 "connection failed" → 3)
- MIGR (100-199): Migration execution errors → exit code 3
    (carve-out: MIGR_101 "already applied" success-with-signal → 0)
- SCHEMA (200-299): Schema DDL and build errors → exit code 4
- SYNC (300-399): Production data sync errors → exit code 5
- DIFFER (400-499): Schema diff detection errors → exit code 5
- VALID (500-599): Validation errors → exit code 5
- ROLLBACK (600-699): Rollback errors → exit code 8
- SQL (700-799): SQL execution errors → exit code 1
- GIT (800-899): Git operation errors → exit code 7
- PGGIT (900-999): pgGit integration errors → exit code 7
- PRECON (1000-1099): Precondition errors → exit code 5
    (carve-out: PRECON_1001 "tracking table absent" → 2)
- LOCK (1300-1399): Database locking errors → exit code 6
- ANON (1400-1499): Anonymization errors → exit code 5
"""

import json
from dataclasses import dataclass

from confiture.error_code_table import ERROR_CODE_DEFINITIONS
from confiture.models.error import ErrorSeverity


@dataclass(frozen=True)
class ErrorCodeDefinition:
    """Definition of a single error code.

    Attributes:
        code: Error code (e.g., "CONFIG_001")
        message_template: Message template with optional format placeholders
        severity: Severity level (INFO, WARNING, ERROR, CRITICAL)
        exit_code: Process exit code for this error (0-10)
        resolution_hint: Optional suggestion on how to resolve the error
    """

    code: str
    message_template: str
    severity: ErrorSeverity
    exit_code: int
    resolution_hint: str | None = None


class ErrorCodeRegistry:
    """Central registry for error code definitions.

    Provides O(1) lookup of error codes and maintains mapping between
    exception types and their default error codes.

    Example:
        >>> registry = ErrorCodeRegistry()
        >>> definition = ErrorCodeDefinition(
        ...     code="CONFIG_001",
        ...     message_template="Missing field '{field}'",
        ...     severity=ErrorSeverity.ERROR,
        ...     exit_code=2,
        ... )
        >>> registry.register(definition)
        >>> registered = registry.get("CONFIG_001")
        >>> registered.code
        'CONFIG_001'
    """

    def __init__(self) -> None:
        """Initialize empty registry."""
        self._codes: dict[str, ErrorCodeDefinition] = {}
        self._exception_defaults: dict[type, str] = {}

    def register(self, definition: ErrorCodeDefinition) -> None:
        """Register an error code definition.

        Args:
            definition: Error code definition to register

        Raises:
            ValueError: If code is already registered
        """
        if definition.code in self._codes:
            msg = f"Error code {definition.code} already registered"
            raise ValueError(msg)

        self._codes[definition.code] = definition

    def get(self, code: str) -> ErrorCodeDefinition:
        """Get an error code definition by code.

        Lookup is O(1) using internal dict.

        Args:
            code: Error code (e.g., "CONFIG_001")

        Returns:
            Error code definition

        Raises:
            ValueError: If code is not registered
        """
        if code not in self._codes:
            msg = f"Error code not found: {code}"
            raise ValueError(msg)

        return self._codes[code]

    def set_exception_default(self, exc_type: type, code: str) -> None:
        """Set the default error code for an exception type.

        Args:
            exc_type: Exception class
            code: Default error code for this exception type
        """
        self._exception_defaults[exc_type] = code

    def get_for_exception(self, exc_type: type) -> str | None:
        """Get the default error code for an exception type.

        Args:
            exc_type: Exception class

        Returns:
            Default error code for this exception type, or None if not set
        """
        return self._exception_defaults.get(exc_type)

    def all_codes(self) -> list[ErrorCodeDefinition]:
        """Get all registered error code definitions.

        Returns:
            List of all error code definitions
        """
        return list(self._codes.values())

    def size(self) -> int:
        """Get the number of registered error codes.

        Returns:
            Total number of error codes in registry
        """
        return len(self._codes)


def _create_global_registry() -> ErrorCodeRegistry:
    """Render the data table into the global error-code registry."""
    registry = ErrorCodeRegistry()
    for row in ERROR_CODE_DEFINITIONS:
        hint = row["resolution_hint"]
        registry.register(
            ErrorCodeDefinition(
                code=str(row["code"]),
                message_template=str(row["message_template"]),
                severity=ErrorSeverity(str(row["severity"])),
                exit_code=int(row["exit_code"]),
                resolution_hint=None if hint is None else str(hint),
            )
        )
    return registry


# Global registry instance
ERROR_CODE_REGISTRY = _create_global_registry()


# ============================================================================
# Canonical exit-code contract (issue #146)
# ============================================================================
#
# CANONICAL_EXIT_CODES is the single, HAND-AUTHORED source of truth for the
# integer process exit code every symbolic error code maps to. It is written
# directly from docs/reference/exit-codes.md — it is NOT derived from the
# registry. The convention test (tests/unit/test_exit_code_convention.py)
# asserts ERROR_CODE_REGISTRY == this dict; deriving one from the other would
# make that test a tautology. The redundancy IS the enforcement mechanism.
#
# Family defaults (the renumbered convention #146 freezes as a contract):
#   2 = tracking table absent (PRECON_1001 only)   3 = DB connection failed
#   4 = schema/DDL/build       5 = config invalid + validation/sync/lint/...
#   6 = lock contention        7 = git / pggit / grant
#   8 = irreversible rollback  1 = generic SQL        0 = success-with-signal
#
# Per-code carve-outs that deliberately differ from their family default are
# annotated inline; do not "align" them to the family number during audits.
CANONICAL_EXIT_CODES: dict[str, int] = {
    # CONFIG family → 5 (config invalid), with CONFIG_006 carved out to 3.
    "CONFIG_001": 5,
    "CONFIG_002": 5,
    "CONFIG_003": 5,
    "CONFIG_004": 5,
    "CONFIG_006": 3,  # carve-out: DB connection failed (family is otherwise 5)
    "CONFIG_007": 5,  # conflicting explicit DSN sources (#152)
    "CONFIG_008": 5,  # tracking_table is not a plain identifier
    "CONFIG_009": 5,  # ANONYMIZATION_SECRET unset (D8: the secret is mandatory)
    "CONFIG_010": 5,
    "CONFIG_011": 5,  # installed pglast lacks enum members confiture walks (D13)
    "CONFIG_012": 5,  # lint baseline file missing or malformed (#219)
    "CONFIG_013": 5,  # a glob that matched files matches none since 1.5.0 (#256)
    "CONFIG_014": 0,  # carve-out: a glob's match set moved — reported, never fatal (#256)
    # MIGR family → 3, with one success-with-signal carve-out at 0.
    "MIGR_001": 3,
    "MIGR_004": 3,
    "MIGR_100": 3,
    "MIGR_101": 0,  # carve-out: already applied — success-with-signal
    "MIGR_102": 3,
    "MIGR_106": 3,
    "MIGR_107": 3,
    "MIGR_108": 3,
    # SCHEMA family → 4.
    "DDL_001": 4,  # destructive DDL refused without --force (schema family)
    "SCHEMA_001": 4,
    "SCHEMA_201": 4,
    "SCHEMA_202": 4,
    "SCHEMA_205": 4,  # psql meta-command refused before psql runs
    # SYNC family → 5.
    "SYNC_001": 5,
    # DIFFER family → 5.
    "DIFFER_400": 5,
    "DIFFER_401": 5,
    "DIFF_001": 5,
    # VALID family → 5.
    "VALID_001": 5,
    "VALID_002": 5,
    "VERIFY_001": 5,
    # ROLLBACK family → 8 (irreversible / inconsistent state).
    "ROLLBACK_001": 8,
    "ROLLBACK_600": 8,
    # SQL family → 1 (generic execution failure).
    "SQL_001": 1,
    # GIT / PGGIT / GRANT → 7.
    "GIT_001": 7,
    "GIT_002": 7,
    "GIT_003": 7,
    "GRANT_001": 7,
    "PGGIT_900": 7,
    # GEN → 3 (migration generation belongs with the MIGR family number).
    "GEN_001": 3,
    # PRECON family → 5, with PRECON_1001 carved out to 2 (no tracking table).
    "PRECON_1000": 5,
    "PRECON_1001": 2,  # carve-out: tracking table absent (family is otherwise 5)
    # LOCK → 6 (contention).
    "LOCK_1300": 6,
    # ANON family → 5.
    "ANON_1400": 5,
    # REBUILD → 4 (schema family number).
    "REBUILD_001": 4,
    # RESTORE / SEED → 5.
    "RESTORE_001": 5,
    "SEED_001": 5,
}


# Human-readable meaning of each integer exit code in the canonical convention.
# This is the operator-facing summary; the per-code mapping lives in
# CANONICAL_EXIT_CODES above. Codes 0–8 are in use; 9 is reserved.
EXIT_CODE_MEANINGS: dict[int, str] = {
    0: "Success (including success-with-signal: already applied, nothing pending, advisories)",
    1: "Generic failure (SQL/hook execution, status: pending)",
    2: "Tracking table absent — confiture not initialized on this database yet",
    3: "Database connection failed — host/auth/network unreachable",
    4: "Schema / DDL / build error",
    5: "Configuration invalid, or validation / sync / lint / precondition failure",
    6: "Lock contention — another writer holds the lock",
    7: "Git / pgGit / grant-accompaniment error",
    8: "Irreversible rollback, or inconsistent state after rollback",
}

# The canonical *semantic class* per exit integer — the machine-readable taxonomy
# the fraisier migration adapters (Rust ``fraisier-core`` and Python ``fraisier``)
# project onto their own error types. It is a stability contract alongside
# ``EXIT_CODE_MEANINGS``: exactly one class per documented exit code, and the class
# names are frozen (a rename is a breaking change requiring a major bump and a
# CHANGELOG note). Consumers keep an identical table verified against
# ``render_exit_codes_json`` / ``confiture --exit-codes-json`` so a drift fails CI
# on both sides. See docs/reference/exit-codes.md and fraisier-adapter-contract.md.
EXIT_CODE_SEMANTIC_CLASS: dict[int, str] = {
    0: "ok",
    1: "internal_error",
    2: "precondition_failed",
    3: "db_unreachable",
    4: "schema_error",
    5: "invalid_config",
    6: "lock_contention",
    7: "git_error",
    8: "irreversible_rollback",
}

# The symbolic error code (exit 2) for a reachable-but-uninitialised database — no
# migration ledger. It is the one code a consumer keys on to recognise "no ledger"
# when only the structured ``--format json`` envelope (not the exit integer) is in
# hand, and to distinguish it from any unrelated failure.
NO_LEDGER_ERROR_CODE = "PRECON_1001"


def render_exit_codes_json() -> str:
    """Render the exit-code contract as machine-readable JSON for wrapper authors.

    The fraisier migration adapters consume this (Rust vendors it and diffs it
    against ``confiture --exit-codes-json``; Python reads it when the installed
    confiture is new enough) to keep their exit-code classifiers in lockstep with
    this frozen contract. Generated from the same hand-authored tables the Markdown
    reference is (``CANONICAL_EXIT_CODES`` + ``EXIT_CODE_MEANINGS`` +
    ``EXIT_CODE_SEMANTIC_CLASS``), so the two can never drift.

    Returns:
        A stable (sorted-key, 2-space-indented) JSON document with the shape::

            {
              "no_ledger_error_code": "PRECON_1001",
              "classes": [<the 9 semantic class names, in exit order>],
              "exit_codes": {
                "<n>": {"class": ..., "meaning": ..., "symbolic_codes": [...]},
                ...
              }
            }
    """
    used_codes = sorted(set(CANONICAL_EXIT_CODES.values()))
    exit_codes = {
        str(code): {
            "class": EXIT_CODE_SEMANTIC_CLASS[code],
            "meaning": EXIT_CODE_MEANINGS.get(code, "(reserved)"),
            "symbolic_codes": sorted(c for c, ec in CANONICAL_EXIT_CODES.items() if ec == code),
        }
        for code in used_codes
    }
    payload = {
        "no_ledger_error_code": NO_LEDGER_ERROR_CODE,
        "classes": [EXIT_CODE_SEMANTIC_CLASS[code] for code in used_codes],
        "exit_codes": exit_codes,
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def render_exit_codes_doc() -> str:
    """Render the canonical exit-code reference as Markdown.

    The output is generated from the HAND-AUTHORED ``CANONICAL_EXIT_CODES`` and
    ``EXIT_CODE_MEANINGS`` — never from the registry — so the human-facing doc
    can never drift from the frozen contract. ``docs/reference/exit-codes.md``
    embeds this between generated-section markers; a coverage test asserts every
    in-use code has a row.

    Returns:
        Markdown containing the summary table and the per-code breakdown.
    """
    used_codes = sorted(set(CANONICAL_EXIT_CODES.values()))

    lines: list[str] = []
    lines.append("| Exit | Meaning |")
    lines.append("|------|---------|")
    lines.extend(
        f"| {code} | {EXIT_CODE_MEANINGS.get(code, '(reserved)')} |" for code in used_codes
    )

    lines.append("")
    lines.append("### Symbolic codes per exit code")
    lines.append("")
    for code in used_codes:
        symbols = sorted(c for c, ec in CANONICAL_EXIT_CODES.items() if ec == code)
        lines.append(f"- **{code}** — {EXIT_CODE_MEANINGS.get(code, '(reserved)')}")
        lines.append(f"  - {', '.join(symbols)}")

    return "\n".join(lines)


def render_error_codebook() -> str:
    """Render the full symbolic error-code codebook as Markdown (issue #145).

    Generated from ``ERROR_CODE_REGISTRY`` so the published codebook can never
    drift from the codes the CLI actually emits in ``--format json``. One table
    row per code: symbolic code, exit code, severity, message template, and the
    resolution hint surfaced as the envelope's ``actionable`` field.
    """

    def _sort_key(d: ErrorCodeDefinition) -> tuple[str, int]:
        family, _, number = d.code.partition("_")
        return (family, int(number) if number.isdigit() else 0)

    lines: list[str] = []
    lines.append("| Code | Exit | Severity | Message | Actionable |")
    lines.append("|------|:----:|----------|---------|------------|")
    for d in sorted(ERROR_CODE_REGISTRY.all_codes(), key=_sort_key):
        message = d.message_template.replace("|", "\\|").replace("\n", " ")
        hint = (d.resolution_hint or "—").replace("|", "\\|").replace("\n", " ")
        lines.append(f"| `{d.code}` | {d.exit_code} | {d.severity.value} | {message} | {hint} |")
    return "\n".join(lines)
