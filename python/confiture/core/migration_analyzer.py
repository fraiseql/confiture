"""Analyze migration SQL for non-transactional statements.

Read with PostgreSQL's own parser (``sql_lexer.parse_file``). Non-transactional statements cannot run inside BEGIN/COMMIT and require
special handling during deployment (e.g. no atomic rollback).
"""

from typing import ClassVar

from confiture.core.sql_lexer import parse_file


class MigrationAnalyzer:
    """Analyzes migration SQL for non-transactional statements.

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

    def analyze(self, sql: str) -> list[str]:
        """Return list of non-transactional statement descriptions.

        Returns empty list if all statements are transactional.
        """
        return self._analyze_pglast(sql)

    def _analyze_pglast(self, sql: str) -> list[str]:
        """AST-based detection using PostgreSQL's own parser."""
        results: list[str] = []
        tree = parse_file(sql).statements

        for stmt_wrapper in tree:
            stmt = stmt_wrapper.stmt
            node_type = type(stmt).__name__

            # CREATE INDEX CONCURRENTLY / DROP INDEX CONCURRENTLY
            if node_type == "IndexStmt" and getattr(stmt, "concurrent", False):
                idx_name = getattr(stmt, "idxname", "<unnamed>")
                results.append(f"CREATE INDEX CONCURRENTLY: {idx_name}")

            elif node_type == "DropStmt" and getattr(stmt, "concurrent", False):
                results.append("DROP INDEX CONCURRENTLY")

            # ALTER TYPE ... ADD VALUE — could not run inside a transaction block
            # before PostgreSQL 12. From 12 it can, provided the new value is not
            # *used* until the transaction commits, so it is still reported: the
            # restriction moved, it did not disappear.
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
