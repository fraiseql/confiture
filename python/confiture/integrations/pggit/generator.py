"""
Migration generator from pgGit commit history.

Analyzes pgGit branches and commits to generate Confiture migration files
that can be deployed to production (which does NOT have pgGit).

This is a key component of the pgGit integration: pgGit is used for
development coordination, then migrations are generated for production.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from confiture.integrations.pggit.client import PgGitClient, Commit, DiffEntry

if TYPE_CHECKING:
    from psycopg import Connection


@dataclass
class GeneratedMigration:
    """Represents a generated migration file.

    Attributes:
        version: Migration version string (e.g., "20250115143022_001")
        name: Migration name derived from branch/commit
        description: Human-readable description
        up_sql: SQL to apply migration
        down_sql: SQL to reverse migration
        source_commits: List of pgGit commit hashes this migration is derived from
        generated_at: When this migration was generated
        metadata: Additional metadata for tracking
    """

    version: str
    name: str
    description: str
    up_sql: str
    down_sql: str
    source_commits: list[str] = field(default_factory=list)
    generated_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def write_to_file(self, output_dir: Path) -> Path:
        """Write migration to Python file.

        Args:
            output_dir: Directory to write the migration file

        Returns:
            Path to the written file
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{self.version}_{self.name}.py"
        filepath = output_dir / filename

        content = self._render()
        filepath.write_text(content)

        return filepath

    def _render(self) -> str:
        """Render migration as Python file content."""
        class_name = self._to_class_name(self.name)
        commits_str = ", ".join(self.source_commits[:5])
        if len(self.source_commits) > 5:
            commits_str += f" (+{len(self.source_commits) - 5} more)"

        # Escape any triple quotes in SQL
        up_sql_escaped = self.up_sql.replace('"""', '\\"\\"\\"')
        down_sql_escaped = self.down_sql.replace('"""', '\\"\\"\\"')

        return f'''"""
{self.description}

Generated from pgGit commits: {commits_str}
Generated at: {self.generated_at.isoformat()}
"""

from confiture.models.migration import Migration


class {class_name}(Migration):
    """
    {self.description}

    Source: pgGit branch commits
    """

    version = "{self.version}"
    name = "{self.name}"

    def up(self) -> None:
        """Apply migration."""
        self.execute("""
{self._indent(up_sql_escaped, 8)}
        """)

    def down(self) -> None:
        """Reverse migration."""
        self.execute("""
{self._indent(down_sql_escaped, 8)}
        """)
'''

    def _to_class_name(self, name: str) -> str:
        """Convert name to PascalCase class name."""
        # Handle underscores and hyphens
        parts = name.replace("-", "_").split("_")
        return "".join(part.title() for part in parts if part)

    def _indent(self, text: str, spaces: int) -> str:
        """Indent text by given number of spaces."""
        if not text.strip():
            return "-- No SQL statements"
        indent = " " * spaces
        lines = text.split("\n")
        return "\n".join(indent + line if line.strip() else line for line in lines)


class MigrationGenerator:
    """
    Generates Confiture migrations from pgGit history.

    This class analyzes pgGit branches and commits, then produces
    migration files that can be applied via Confiture to any
    environment (including production, which has NO pgGit).

    The workflow is:
    1. Developer makes schema changes on pgGit-enabled dev database
    2. Changes are tracked in pgGit branches/commits
    3. MigrationGenerator creates migration files from those commits
    4. Migrations are deployed to production via `confiture migrate up`

    Example:
        >>> generator = MigrationGenerator(connection)
        >>> migrations = generator.generate_from_branch("feature/payments")
        >>> for migration in migrations:
        ...     filepath = migration.write_to_file(Path("db/migrations"))
        ...     print(f"Generated: {filepath}")

    Example with combined migration:
        >>> migration = generator.generate_combined(
        ...     "feature/payments",
        ...     output_dir=Path("db/migrations")
        ... )
        >>> print(f"Combined migration: {migration.version}_{migration.name}")
    """

    def __init__(self, connection: Connection):
        """
        Initialize generator.

        Args:
            connection: PostgreSQL connection with pgGit extension

        Raises:
            PgGitNotAvailableError: If pgGit not installed
        """
        self._connection = connection
        self._client = PgGitClient(connection)

    @property
    def client(self) -> PgGitClient:
        """Get the underlying pgGit client."""
        return self._client

    def generate_from_branch(
        self,
        branch_name: str,
        base_branch: str = "main",
        output_dir: Path | None = None,
    ) -> list[GeneratedMigration]:
        """
        Generate migrations from a feature branch.

        Analyzes the diff between branch_name and base_branch,
        and generates migration files for each change.

        Args:
            branch_name: Feature branch to generate from
            base_branch: Base branch to compare against (default: "main")
            output_dir: Directory to write migration files (optional)

        Returns:
            List of generated migrations

        Example:
            >>> migrations = generator.generate_from_branch("feature/payments")
            >>> print(f"Generated {len(migrations)} migrations")
        """
        # Get diff between branches
        diff = self._client.diff(base_branch, branch_name)

        if not diff:
            return []

        # Group changes by type for better organization
        migrations = []
        grouped_changes = self._group_changes_by_type(diff)

        for i, (obj_type, changes) in enumerate(grouped_changes.items()):
            migration = self._generate_migration_from_changes(
                changes,
                index=i,
                source_branch=branch_name,
                base_branch=base_branch,
            )
            migrations.append(migration)

            if output_dir:
                migration.write_to_file(output_dir)

        return migrations

    def generate_from_diff(
        self,
        diff: list[DiffEntry],
        name: str,
        output_dir: Path | None = None,
    ) -> GeneratedMigration:
        """
        Generate a migration from a diff.

        Args:
            diff: List of DiffEntry objects
            name: Name for the migration
            output_dir: Directory to write migration file (optional)

        Returns:
            Generated migration
        """
        up_statements = []
        down_statements = []

        for entry in diff:
            up_sql = self._generate_up_sql(entry)
            down_sql = self._generate_down_sql(entry)

            if up_sql:
                up_statements.append(up_sql)
            if down_sql:
                down_statements.insert(0, down_sql)  # Reverse order for down

        migration = GeneratedMigration(
            version=self._generate_version(),
            name=self._sanitize_name(name),
            description=f"Migration: {name}",
            up_sql=";\n\n".join(up_statements) + ";" if up_statements else "",
            down_sql=";\n\n".join(down_statements) + ";" if down_statements else "",
            source_commits=[],
            metadata={"changes_count": len(diff)},
        )

        if output_dir:
            migration.write_to_file(output_dir)

        return migration

    def generate_combined(
        self,
        branch_name: str,
        base_branch: str = "main",
        output_dir: Path | None = None,
    ) -> GeneratedMigration | None:
        """
        Generate a single combined migration from all branch changes.

        Useful when you want one migration file instead of multiple.

        Args:
            branch_name: Feature branch to generate from
            base_branch: Base branch to compare against
            output_dir: Directory to write migration file

        Returns:
            Single combined migration or None if no changes

        Example:
            >>> migration = generator.generate_combined("feature/payments")
            >>> if migration:
            ...     print(f"Generated: {migration.version}_{migration.name}")
        """
        diff = self._client.diff(base_branch, branch_name)

        if not diff:
            return None

        # Combine all changes
        up_statements = []
        down_statements = []

        for entry in diff:
            up_sql = self._generate_up_sql(entry)
            down_sql = self._generate_down_sql(entry)

            if up_sql:
                up_statements.append(up_sql)
            if down_sql:
                down_statements.insert(0, down_sql)  # Reverse order

        migration = GeneratedMigration(
            version=self._generate_version(),
            name=self._sanitize_branch_name(branch_name),
            description=f"Combined migration from branch {branch_name}",
            up_sql=";\n\n".join(up_statements) + ";" if up_statements else "",
            down_sql=";\n\n".join(down_statements) + ";" if down_statements else "",
            source_commits=[],  # Could be populated from log
            metadata={
                "source_branch": branch_name,
                "base_branch": base_branch,
                "changes_count": len(diff),
                "combined": True,
            },
        )

        if output_dir:
            migration.write_to_file(output_dir)

        return migration

    def preview(
        self,
        branch_name: str,
        base_branch: str = "main",
    ) -> list[dict[str, Any]]:
        """
        Preview what migrations would be generated.

        Args:
            branch_name: Feature branch
            base_branch: Base branch

        Returns:
            List of change dictionaries for preview
        """
        diff = self._client.diff(base_branch, branch_name)

        return [
            {
                "operation": entry.operation,
                "object_type": entry.object_type,
                "object_name": entry.object_name,
                "has_old_ddl": bool(entry.old_ddl),
                "has_new_ddl": bool(entry.new_ddl),
            }
            for entry in diff
        ]

    def _group_changes_by_type(
        self,
        diff: list[DiffEntry],
    ) -> dict[str, list[DiffEntry]]:
        """Group changes by object type."""
        grouped: dict[str, list[DiffEntry]] = {}
        for entry in diff:
            key = entry.object_type
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(entry)
        return grouped

    def _generate_migration_from_changes(
        self,
        changes: list[DiffEntry],
        index: int,
        source_branch: str,
        base_branch: str,
    ) -> GeneratedMigration:
        """Generate migration from a list of changes."""
        up_statements = []
        down_statements = []

        for change in changes:
            up_sql = self._generate_up_sql(change)
            down_sql = self._generate_down_sql(change)

            if up_sql:
                up_statements.append(up_sql)
            if down_sql:
                down_statements.insert(0, down_sql)

        # Determine name from changes
        obj_types = set(c.object_type for c in changes)
        name_parts = [source_branch.split("/")[-1]]
        if len(obj_types) == 1:
            name_parts.append(list(obj_types)[0].lower())

        return GeneratedMigration(
            version=self._generate_version(index),
            name=self._sanitize_name("_".join(name_parts)),
            description=f"Migration from {source_branch} ({len(changes)} changes)",
            up_sql=";\n\n".join(up_statements) + ";" if up_statements else "",
            down_sql=";\n\n".join(down_statements) + ";" if down_statements else "",
            source_commits=[],
            metadata={
                "source_branch": source_branch,
                "base_branch": base_branch,
                "object_types": list(obj_types),
                "changes_count": len(changes),
            },
        )

    def _generate_up_sql(self, entry: DiffEntry) -> str:
        """Generate UP SQL for a change."""
        if entry.new_ddl:
            return entry.new_ddl.strip()

        # Generate based on operation
        if entry.operation == "DROP":
            return f"DROP {entry.object_type} IF EXISTS {entry.object_name}"
        elif entry.operation in ("CREATE", "ALTER"):
            return f"-- {entry.operation} {entry.object_type} {entry.object_name} (DDL not captured)"

        return f"-- Unknown operation: {entry.operation} {entry.object_type} {entry.object_name}"

    def _generate_down_sql(self, entry: DiffEntry) -> str:
        """Generate DOWN (reverse) SQL for a change."""
        if entry.operation == "CREATE":
            # Reverse of CREATE is DROP
            return f"DROP {entry.object_type} IF EXISTS {entry.object_name}"
        elif entry.operation == "DROP":
            # Reverse of DROP is recreate (need old DDL)
            if entry.old_ddl:
                return entry.old_ddl.strip()
            return f"-- Cannot reverse DROP {entry.object_type} {entry.object_name} (no DDL captured)"
        elif entry.operation == "ALTER":
            # Reverse of ALTER needs old DDL
            if entry.old_ddl:
                return entry.old_ddl.strip()
            return f"-- Cannot reverse ALTER {entry.object_type} {entry.object_name} (no old DDL)"

        return f"-- Cannot reverse {entry.operation} {entry.object_type} {entry.object_name}"

    def _generate_version(self, index: int = 0) -> str:
        """Generate migration version string."""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        return f"{timestamp}_{index:03d}"

    def _sanitize_branch_name(self, name: str) -> str:
        """Convert branch name to migration-safe name."""
        # Remove prefix like feature/, hotfix/
        if "/" in name:
            name = name.split("/")[-1]
        return self._sanitize_name(name)

    def _sanitize_name(self, name: str) -> str:
        """Convert any name to migration-safe name."""
        # Replace non-alphanumeric with underscore
        safe = "".join(c if c.isalnum() else "_" for c in name)
        # Remove consecutive underscores
        while "__" in safe:
            safe = safe.replace("__", "_")
        # Remove leading/trailing underscores
        return safe.strip("_").lower()[:50]
