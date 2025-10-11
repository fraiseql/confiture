"""Schema builder - builds PostgreSQL schemas from DDL files

The SchemaBuilder concatenates SQL files from db/schema/ in deterministic order
to create a complete schema file. This implements "Medium 1: Build from Source DDL".
"""

import hashlib
from datetime import datetime
from pathlib import Path

from confiture.config.environment import Environment
from confiture.exceptions import SchemaError


class SchemaBuilder:
    """Build PostgreSQL schema from DDL source files

    The SchemaBuilder discovers SQL files in the schema directory, concatenates
    them in deterministic order, and generates a complete schema file.

    Attributes:
        env_config: Environment configuration
        schema_dir: Base directory for schema files

    Example:
        >>> builder = SchemaBuilder(env="local")
        >>> schema = builder.build()
        >>> print(len(schema))
        15234
    """

    def __init__(self, env: str, project_dir: Path | None = None):
        """Initialize SchemaBuilder

        Args:
            env: Environment name (e.g., "local", "production")
            project_dir: Project root directory. If None, uses current directory.
        """
        self.env_config = Environment.load(env, project_dir=project_dir)

        # Schema directory is the first include_dir
        if not self.env_config.include_dirs:
            raise SchemaError("No include_dirs specified in environment config")

        self.schema_dir = Path(self.env_config.include_dirs[0])

    def find_sql_files(self) -> list[Path]:
        """Discover SQL files in schema directory

        Files are returned in deterministic alphabetical order. Use numbered
        directories (00_common/, 10_tables/, 20_views/) to control ordering.

        Returns:
            Sorted list of SQL file paths

        Raises:
            SchemaError: If schema directory doesn't exist or is empty

        Example:
            >>> builder = SchemaBuilder(env="local")
            >>> files = builder.find_sql_files()
            >>> print(files[0])
            /path/to/db/schema/00_common/extensions.sql
        """
        if not self.schema_dir.exists():
            raise SchemaError(f"Schema directory does not exist: {self.schema_dir}")

        # Find all SQL files recursively
        sql_files = list(self.schema_dir.rglob("*.sql"))

        # Filter out excluded directories
        filtered_files = []
        exclude_paths = [Path(d) for d in self.env_config.exclude_dirs]

        for file in sql_files:
            # Check if file is in any excluded directory
            is_excluded = any(
                file.is_relative_to(exclude_dir) for exclude_dir in exclude_paths
            )
            if not is_excluded:
                filtered_files.append(file)

        if not filtered_files:
            raise SchemaError(
                f"No SQL files found in {self.schema_dir}\n"
                f"Expected files in subdirectories like 00_common/, 10_tables/, etc."
            )

        # Sort alphabetically for deterministic order
        return sorted(filtered_files)

    def build(self, output_path: Path | None = None) -> str:
        """Build schema by concatenating DDL files

        Generates a complete schema file by concatenating all SQL files in
        deterministic order, with headers and file separators.

        Args:
            output_path: Optional path to write schema file. If None, only returns content.

        Returns:
            Generated schema content as string

        Raises:
            SchemaError: If schema build fails

        Example:
            >>> builder = SchemaBuilder(env="local")
            >>> schema = builder.build(output_path=Path("schema.sql"))
            >>> print(f"Generated {len(schema)} bytes")
        """
        files = self.find_sql_files()

        # Generate header
        header = self._generate_header(len(files))
        parts = [header]

        # Concatenate all files
        for file in files:
            try:
                # Relative path for header
                rel_path = file.relative_to(self.schema_dir)

                # Add file separator
                parts.append("\n-- ============================================\n")
                parts.append(f"-- File: {rel_path}\n")
                parts.append("-- ============================================\n\n")

                # Add file content
                content = file.read_text(encoding="utf-8")
                parts.append(content)

                # Ensure newline at end
                if not content.endswith("\n"):
                    parts.append("\n")

            except Exception as e:
                raise SchemaError(f"Error reading {file}: {e}") from e

        # Join all parts
        schema = "".join(parts)

        # Write to file if requested
        if output_path:
            try:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(schema, encoding="utf-8")
            except Exception as e:
                raise SchemaError(f"Error writing schema to {output_path}: {e}") from e

        return schema

    def compute_hash(self) -> str:
        """Compute deterministic SHA256 hash of schema

        The hash includes both file paths and content, ensuring that any change
        to the schema (content or structure) is detected.

        Returns:
            SHA256 hexadecimal digest

        Example:
            >>> builder = SchemaBuilder(env="local")
            >>> hash1 = builder.compute_hash()
            >>> # Modify a file...
            >>> hash2 = builder.compute_hash()
            >>> assert hash1 != hash2  # Change detected
        """
        files = self.find_sql_files()
        hasher = hashlib.sha256()

        for file in files:
            # Include relative path in hash (detects file renames)
            rel_path = file.relative_to(self.schema_dir)
            hasher.update(str(rel_path).encode("utf-8"))
            hasher.update(b"\x00")  # Separator

            # Include file content
            try:
                content = file.read_bytes()
                hasher.update(content)
                hasher.update(b"\x00")  # Separator
            except Exception as e:
                raise SchemaError(f"Error reading {file} for hash: {e}") from e

        return hasher.hexdigest()

    def _generate_header(self, file_count: int) -> str:
        """Generate schema file header

        Args:
            file_count: Number of SQL files included

        Returns:
            Header string
        """
        timestamp = datetime.now().isoformat()
        schema_hash = self.compute_hash()

        return f"""-- ============================================
-- PostgreSQL Schema for Confiture
-- ============================================
--
-- Environment: {self.env_config.name}
-- Generated: {timestamp}
-- Schema Hash: {schema_hash}
-- Files Included: {file_count}
--
-- This file was generated by Confiture (confiture build)
-- DO NOT EDIT MANUALLY - Edit source files in db/schema/
--
-- ============================================

"""
