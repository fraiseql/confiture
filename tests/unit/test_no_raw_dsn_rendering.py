"""Guard: no output sink renders a DSN that has not been through ``redact_url`` (SEC-04).

A connection URL carries a password. The only spelling that may leave the
process — into a log line, a console message, an exception text, JSON on
stdout — is the one :func:`confiture.core.url_redaction.redact_url` produces.

This test walks every module under ``python/confiture`` and, for every output
sink (``print``, ``*.print``, ``logger.<level>``, ``typer.echo``,
``warnings.warn``, and the exception built by a ``raise``), collects the names
referenced by its arguments — through f-strings, ``%``-formatting and
``str.format`` — and fails when one of them is DSN-shaped and not inside a
``redact_url(...)`` call. Names are the guard's unit on purpose: a password
does not arrive in a variable called ``docs_url``.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_CONFITURE_SRC = Path(__file__).resolve().parents[2] / "python" / "confiture"
_REDACTION_MODULE = _CONFITURE_SRC / "core" / "url_redaction.py"

# The spellings a connection string travels under in this codebase.
_DSN_NAME = re.compile(
    r"(?i)(dsn|conninfo|connection_string|connstr"
    r"|(^|_)(database|db|connection|against|source|target|admin|template"
    r"|maintenance|temp_db|source_db|target_db|worker|test_db)_url$)"
)
_LOG_LEVELS = {"debug", "info", "warning", "warn", "error", "exception", "critical", "log"}


def _is_sink(call: ast.Call) -> bool:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id == "print"
    if isinstance(func, ast.Attribute):
        if func.attr == "print":
            return True  # console.print / error_console.print / rich Console
        if func.attr in ("echo", "secho") and isinstance(func.value, ast.Name):
            return func.value.id == "typer"
        if func.attr == "warn" and isinstance(func.value, ast.Name):
            return func.value.id == "warnings"
        if func.attr in _LOG_LEVELS and isinstance(func.value, ast.Name):
            return func.value.id in ("logger", "log", "logging", "_logger", "LOGGER")
    return False


def _is_redaction_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and (
        (isinstance(node.func, ast.Name) and node.func.id == "redact_url")
        or (isinstance(node.func, ast.Attribute) and node.func.attr == "redact_url")
    )


def _dsn_names(node: ast.AST) -> set[str]:
    """DSN-shaped names referenced under *node*, skipping ``redact_url(...)`` subtrees."""
    found: set[str] = set()
    stack: list[ast.AST] = [node]
    while stack:
        current = stack.pop()
        if _is_redaction_call(current):
            continue
        if isinstance(current, ast.Name) and _DSN_NAME.search(current.id):
            found.add(current.id)
        elif isinstance(current, ast.Attribute) and _DSN_NAME.search(current.attr):
            found.add(current.attr)
        stack.extend(ast.iter_child_nodes(current))
    return found


def _sink_payloads(tree: ast.AST):
    """Yield ``(lineno, node)`` for every expression an output sink renders."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_sink(node):
            for arg in [*node.args, *(kw.value for kw in node.keywords)]:
                yield node.lineno, arg
        elif isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            for arg in [*node.exc.args, *(kw.value for kw in node.exc.keywords)]:
                yield node.lineno, arg


def find_raw_dsn_renderings(root: Path) -> list[str]:
    findings: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if path == _REDACTION_MODULE:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = path.relative_to(root.parent.parent).as_posix()
        for lineno, payload in _sink_payloads(tree):
            names = _dsn_names(payload)
            if names:
                findings.append(f"{rel}:{lineno}: renders {', '.join(sorted(names))}")
    return findings


def test_no_sink_renders_a_raw_dsn() -> None:
    findings = find_raw_dsn_renderings(_CONFITURE_SRC)
    assert findings == [], (
        "connection URLs rendered without redact_url():\n  "
        + "\n  ".join(findings)
        + "\nWrap the value in confiture.core.url_redaction.redact_url(...)."
    )


# ---------------------------------------------------------------------------
# The detector itself
# ---------------------------------------------------------------------------


def _scan(source: str) -> list[str]:
    tree = ast.parse(source)
    return [n for _, payload in _sink_payloads(tree) for n in sorted(_dsn_names(payload))]


def test_detector_catches_fstring_in_print() -> None:
    assert _scan('print(f"connecting to {database_url}")') == ["database_url"]


def test_detector_catches_logger_percent_argument() -> None:
    assert _scan('logger.info("connecting to %s", dsn)') == ["dsn"]


def test_detector_catches_str_format_in_console_print() -> None:
    assert _scan('console.print("db: {}".format(self.connection_url))') == ["connection_url"]


def test_detector_catches_exception_message() -> None:
    assert _scan('raise ConfigurationError(f"bad url {against_url}")') == ["against_url"]


def test_detector_catches_attribute_access() -> None:
    assert _scan('print(f"{config.database_url}")') == ["database_url"]


def test_detector_allows_redacted_rendering() -> None:
    assert _scan('print(f"connecting to {redact_url(database_url)}")') == []
    assert _scan('logger.info("db %s", redact_url(self.source_dsn))') == []


def test_detector_ignores_non_dsn_urls() -> None:
    assert _scan('print(f"see {docs_url} and {safe_url} and {schema_url}")') == []


def test_detector_ignores_non_sinks() -> None:
    assert _scan("conn = psycopg.connect(database_url)") == []
