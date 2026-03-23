"""Analyze migration SQL for non-transactional statements.

Uses pglast (PostgreSQL's C parser) when available, falls back to regex.
Non-transactional statements cannot run inside BEGIN/COMMIT and require
special handling during deployment (e.g. no atomic rollback).
"""

from __future__ import annotations

import re
from typing import Any, ClassVar


class MigrationAnalyzer:
    """Analyzes migration SQL for non-transactional statements.

    Uses pglast (PostgreSQL's C parser) when available, falls back to regex.

    Example::

        analyzer = MigrationAnalyzer()
        issues = analyzer.analyze("CREATE INDEX CONCURRENTLY idx ON t(c);")
        # ["CREATE INDEX CONCURRENTLY: idx"]
    """

    _NON_TXN_NODE_TYPES: ClassVar[frozenset[str]] = frozenset(
        {
            "CreatedbStmt",
            "DropdbStmt",
            "VacuumStmt",
            "ClusterStmt",
        }
    )

    _NON_TXN_PATTERNS: ClassVar[list[tuple[re.Pattern[str], str]]] = [
        (
            re.compile(
                r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+CONCURRENTLY\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)",
                re.IGNORECASE,
            ),
            "CREATE INDEX CONCURRENTLY: {0}",
        ),
        (
            re.compile(
                r"DROP\s+INDEX\s+CONCURRENTLY",
                re.IGNORECASE,
            ),
            "DROP INDEX CONCURRENTLY",
        ),
        (
            re.compile(
                r"ALTER\s+TYPE\s+([\w.]+)\s+ADD\s+VALUE",
                re.IGNORECASE,
            ),
            "ALTER TYPE {0} ADD VALUE",
        ),
        (
            re.compile(
                r"REINDEX\s+.*CONCURRENTLY",
                re.IGNORECASE,
            ),
            "REINDEX CONCURRENTLY",
        ),
        (
            re.compile(
                r"((?:CREATE|DROP)\s+DATABASE)",
                re.IGNORECASE,
            ),
            "{0}",
        ),
        (
            re.compile(
                r"\bVACUUM\b",
                re.IGNORECASE,
            ),
            "VACUUM",
        ),
        (
            re.compile(
                r"\bCLUSTER\b(?!\s+BY)",
                re.IGNORECASE,
            ),
            "CLUSTER",
        ),
    ]

    def analyze(self, sql: str) -> list[str]:
        """Return list of non-transactional statement descriptions.

        Returns empty list if all statements are transactional.
        """
        try:
            import pglast  # noqa: PLC0415

            return self._analyze_pglast(sql, pglast)
        except ImportError:
            return self._analyze_regex(sql)

    def _analyze_pglast(self, sql: str, pglast: Any) -> list[str]:
        """AST-based detection using PostgreSQL's own parser."""
        results: list[str] = []
        tree = pglast.parse_sql(sql)

        for stmt_wrapper in tree:
            stmt = stmt_wrapper.stmt
            node_type = type(stmt).__name__

            # CREATE INDEX CONCURRENTLY / DROP INDEX CONCURRENTLY
            if node_type == "IndexStmt" and getattr(stmt, "concurrent", False):
                idx_name = getattr(stmt, "idxname", "<unnamed>")
                results.append(f"CREATE INDEX CONCURRENTLY: {idx_name}")

            elif node_type == "DropStmt" and getattr(stmt, "concurrent", False):
                results.append("DROP INDEX CONCURRENTLY")

            # ALTER TYPE ... ADD VALUE (non-transactional in PG < 16)
            elif node_type == "AlterEnumStmt":
                type_name = getattr(stmt, "typeName", None)
                if type_name:
                    parts = [n.sval for n in type_name if hasattr(n, "sval")]
                    results.append(f"ALTER TYPE {'.'.join(parts)} ADD VALUE")
                else:
                    results.append("ALTER TYPE ... ADD VALUE")

            # REINDEX ... CONCURRENTLY
            elif node_type == "ReindexStmt":
                options = getattr(stmt, "params", None) or []
                for opt in options:
                    if hasattr(opt, "defname") and opt.defname == "concurrently":
                        results.append("REINDEX CONCURRENTLY")
                        break

            # Database-level / maintenance statements
            elif node_type in self._NON_TXN_NODE_TYPES:
                results.append(node_type.replace("Stmt", "").upper())

        return results

    def _analyze_regex(self, sql: str) -> list[str]:
        """Regex-based fallback when pglast is unavailable.

        Note: This path cannot distinguish statements inside dollar-quoted
        function bodies from top-level statements. Use pglast for authoritative
        results (install with ``pip install "fraiseql-confiture[ast]"``).
        """
        results: list[str] = []
        for pattern, template in self._NON_TXN_PATTERNS:
            for match in pattern.finditer(sql):
                if "{0}" in template:
                    results.append(template.format(match.group(1)))
                else:
                    results.append(template)
        return results
