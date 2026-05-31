"""Structured error envelope + JSON-aware CLI error boundary (issue #145).

In ``--format json`` mode, every failure path emits a stable, machine-readable
envelope on stdout instead of free-form Rich text. The ``error`` value is the
unified inner issue object shared across #144 / #145 / #148 (see
.phases/.../shared-issue-schema.md):

    {"ok": false, "error": {severity, code, message, actionable,
                            details, migration, file, line}}

The process still exits with the #146 exit code (``ConfiturError.exit_code``).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn

import typer

from confiture.exceptions import ConfiturError

if TYPE_CHECKING:
    from rich.console import Console

# Envelope `code` used when a non-ConfiturError escapes translation. It is not a
# registry code (those are domain failures); it signals "unexpected internal
# error" and pairs with the generic exit code 1.
INTERNAL_ERROR_CODE = "INTERNAL_ERROR"


# Stale-lock advisory threshold (seconds). Held longer than this, the message
# suggests the holder may be stuck.
_STALE_LOCK_SECONDS = 300


def lock_error_to_confiture(exc: Exception) -> ConfiturError:
    """Translate a LockAcquisitionError into a LOCK_1300 ConfiturError (#147).

    Folds the holder identity into ``context["holder"]`` (so it lands under the
    envelope's ``details.holder``) and adds a stale-lock hint when the lock has
    been held a long time.
    """
    holder = getattr(exc, "holder", None)
    context: dict[str, Any] = {}
    if holder is not None:
        context["holder"] = holder.to_dict()

    hint = "Wait for the current migration to finish, then retry."
    held = getattr(holder, "held_for_seconds", None) if holder is not None else None
    if held is not None and held > _STALE_LOCK_SECONDS:
        hint += (
            f" Held for >{_STALE_LOCK_SECONDS // 60} min — this may be a stale lock; "
            "investigate the holder process before forcing."
        )
    return ConfiturError(
        str(exc) or "Migration lock is held by another process.",
        error_code="LOCK_1300",
        context=context,
        resolution_hint=hint,
    )


def coerce_to_confiture_error(exc: Exception) -> ConfiturError:
    """Wrap a non-ConfiturError so JSON consumers never see a raw traceback.

    A genuine ``ConfiturError`` is returned unchanged. A ``LockAcquisitionError``
    becomes a ``LOCK_1300`` error with holder identity (#147). Anything else
    becomes a generic ``ConfiturError`` (no registry code → exit 1) carrying the
    original message, so ``emit_error_json`` still produces a valid envelope.
    """
    if isinstance(exc, ConfiturError):
        return exc
    from confiture.core.locking import LockAcquisitionError

    if isinstance(exc, LockAcquisitionError):
        return lock_error_to_confiture(exc)
    message = str(exc) or exc.__class__.__name__
    return ConfiturError(message)


def _jsonify(value: Any) -> Any:
    """Recursively coerce Paths (and containers of Paths) to JSON-safe values."""
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {k: _jsonify(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonify(v) for v in value]
    return value


def emit_error_json(error: ConfiturError) -> dict[str, Any]:
    """Serialize a ConfiturError to the #145 error envelope.

    ``details`` is everything in ``error.context`` except the keys promoted to
    first-class fields (``file``, ``line``, ``migration_version``). Named-attribute
    extras (``conflicting_files``, ``filepath``) that some subclasses store outside
    ``context`` are folded into ``details`` so it is never silently empty.
    """
    base = error.to_dict()
    context = dict(base.get("context") or {})

    # Fold named-attribute extras into details (these subclasses keep data on
    # attrs, not in context). setdefault: an explicit context key wins.
    conflicting = getattr(error, "conflicting_files", None)
    if conflicting:
        context.setdefault("conflicting_files", conflicting)
    filepath = getattr(error, "filepath", None)
    if filepath is not None:
        context.setdefault("filepath", filepath)

    migration = context.pop("migration_version", None) or getattr(error, "version", None)
    file = context.pop("file", None)
    line = context.pop("line", None)

    severity = base["severity"]
    if severity == "critical":  # fold CRITICAL into the public "error" tier
        severity = "error"

    return {
        "ok": False,
        "error": {
            "code": base["error_code"] or INTERNAL_ERROR_CODE,
            "message": base["message"],
            "severity": severity,
            "details": _jsonify(context),
            "migration": _jsonify(migration),
            "file": _jsonify(file),
            "line": line,
            "actionable": base["resolution_hint"],
        },
    }


def fail(
    error: Exception,
    *,
    json_mode: bool,
    output_file: Path | None = None,
    console: Console | None = None,
    error_console: Console | None = None,
) -> NoReturn:
    """Single error boundary: emit the failure, then exit with the #146 code.

    In ``json_mode`` the envelope goes to stdout (OD-4) so a single ``jq`` pipe
    reads it; otherwise the human-readable Rich rendering goes to stderr. The
    human path is byte-for-byte the pre-#145 behavior.

    Raises:
        typer.Exit: always, with ``ConfiturError.exit_code``.
    """
    from confiture.cli.helpers import _output_json
    from confiture.cli.helpers import console as default_console
    from confiture.cli.helpers import error_console as default_error_console
    from confiture.core.error_handler import print_error_to_console

    err = coerce_to_confiture_error(error)

    if json_mode:
        _output_json(emit_error_json(err), output_file, console or default_console)
    else:
        print_error_to_console(err, error_console or default_error_console)

    raise typer.Exit(err.exit_code)
