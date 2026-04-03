"""AST-based import checker for untrusted strategy modules."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

# Modules that must never be imported by custom strategies
BLOCKED_MODULES: frozenset[str] = frozenset(
    {
        # System access
        "os",
        "sys",
        "subprocess",
        "shutil",
        "ctypes",
        "signal",
        "multiprocessing",
        "threading",
        # Import system manipulation
        "importlib",
        "pkgutil",
        # Network / IO
        "socket",
        "http",
        "urllib",
        "requests",
        "httpx",
        "paramiko",
        "ftplib",
        "smtplib",
        # Cloud SDKs
        "boto3",
        "botocore",
        "google",
        "azure",
        # Code execution
        "eval",
        "exec",
        "compile",
        "code",
        "codeop",
    }
)


@dataclass(frozen=True)
class ImportViolation:
    """A blocked import found in a strategy module."""

    module: str
    line: int
    col: int


def check_file(path: Path) -> list[ImportViolation]:
    """Scan a Python file for blocked imports. Returns violations."""
    source = path.read_text(encoding="utf-8")
    return check_source(source)


def check_source(source: str) -> list[ImportViolation]:
    """Scan Python source code for blocked imports."""
    tree = ast.parse(source)
    violations: list[ImportViolation] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in BLOCKED_MODULES:
                    violations.append(
                        ImportViolation(
                            module=alias.name,
                            line=node.lineno,
                            col=node.col_offset,
                        )
                    )
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.split(".")[0] in BLOCKED_MODULES
        ):
            violations.append(
                ImportViolation(
                    module=node.module,
                    line=node.lineno,
                    col=node.col_offset,
                )
            )

    return violations
