"""Schema builder - builds PostgreSQL schemas from DDL files

The SchemaBuilder concatenates SQL files from db/schema/ in deterministic order
to create a complete schema file. This implements "Medium 1: Build from Source DDL".

Performance: Uses Rust extension (_core) when available for 10-50x speedup.
"""

import hashlib
from datetime import datetime
from pathlib import Path

from confiture.config.environment import Environment
from confiture.exceptions import SchemaError

# Try to import Rust extension for 10-50x performance boost
try:
    from confiture import _core  # type: ignore

    HAS_RUST = True
except ImportError:
    HAS_RUST = False


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

        # Validate include_dirs
        if not self.env_config.include_dirs:
            raise SchemaError("No include_dirs specified in environment config")

        # Store include dirs for file discovery
        self.include_dirs = [Path(d) for d in self.env_config.include_dirs]

        # Base directory for relative path calculation
        # Find the common parent of all include directories
        self.base_dir = self._find_common_parent(self.include_dirs)

    def _find_common_parent(self, paths: list[Path]) -> Path:
        """Find common parent directory of all paths.

        Args:
            paths: List of paths to find common parent

        Returns:
            Common parent directory

        Example:
            >>> paths = [Path("db/schema/00_common"), Path("db/seeds/common")]
            >>> _find_common_parent(paths)
            Path("db")
        """
        if len(paths) == 1:
            return paths[0]

        # Convert to absolute paths for comparison
        abs_paths = [p.resolve() for p in paths]

        # Get all parent parts for each path (including the path itself)
        all_parts = [p.parts for p in abs_paths]

        # Find common prefix
        common_parts = []
        for parts_at_level in zip(*all_parts):
            if len(set(parts_at_level)) == 1:
                common_parts.append(parts_at_level[0])
            else:
                break

        if not common_parts:
            # No common parent, use current directory
            return Path(".")

        # Reconstruct path from common parts
        return Path(*common_parts)

    def find_sql_files(self) -> list[Path]:
        """Discover SQL files in all include directories

        Files are returned in deterministic alphabetical order. Use numbered
        directories (00_common/, 10_tables/, 20_views/) to control ordering.

        Returns:
            Sorted list of SQL file paths

        Raises:
            SchemaError: If include directories don't exist or no SQL files found

        Example:
            >>> builder = SchemaBuilder(env="local")
            >>> files = builder.find_sql_files()
            >>> print(files[0])
            /path/to/db/schema/00_common/extensions.sql
        """
        all_sql_files = []

        # Collect SQL files from all include directories
        for include_dir in self.include_dirs:
            if not include_dir.exists():
                raise SchemaError(f"Include directory does not exist: {include_dir}")

            # Find all SQL files recursively in this directory
            sql_files = list(include_dir.rglob("*.sql"))
            all_sql_files.extend(sql_files)

        # Filter out excluded directories
        filtered_files = []
        exclude_paths = [Path(d) for d in self.env_config.exclude_dirs]

        for file in all_sql_files:
            # Check if file is in any excluded directory
            is_excluded = any(
                file.is_relative_to(exclude_dir) for exclude_dir in exclude_paths
            )
            if not is_excluded:
                filtered_files.append(file)

        if not filtered_files:
            include_dirs_str = ", ".join(str(d) for d in self.include_dirs)
            raise SchemaError(
                f"No SQL files found in include directories: {include_dirs_str}\n"
                f"Expected files in subdirectories like 00_common/, 10_tables/, etc."
            )

        # Sort alphabetically for deterministic order
        return sorted(filtered_files)

    def build(self, output_path: Path | None = None) -> str:
        """Build schema by concatenating DDL files

        Generates a complete schema file by concatenating all SQL files in
        deterministic order, with headers and file separators.

        Performance: Uses Rust extension when available for 10-50x speedup.
        Falls back gracefully to Python implementation if Rust unavailable.

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

        # Use Rust extension if available (10-50x faster)
        if HAS_RUST:
            try:
                # Build file content using Rust
                file_paths = [str(f) for f in files]
                content = _core.build_schema(file_paths)

                # Add headers and separators (Python side for flexibility)
                schema = self._add_headers_and_separators(header, files, content)
            except Exception as e:
                # Fallback to Python if Rust fails
                schema = self._build_python(header, files)
        else:
            # Pure Python implementation (fallback)
            schema = self._build_python(header, files)

        # Write to file if requested
        if output_path:
            try:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(schema, encoding="utf-8")
            except Exception as e:
                raise SchemaError(f"Error writing schema to {output_path}: {e}") from e

        return schema

    def _build_python(self, header: str, files: list[Path]) -> str:
        """Pure Python implementation of schema building (fallback)

        Args:
            header: Schema header
            files: List of SQL files to concatenate

        Returns:
            Complete schema content
        """
        parts = [header]

        # Concatenate all files
        for file in files:
            try:
                # Relative path for header
                rel_path = file.relative_to(self.base_dir)

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

        return "".join(parts)

    def _add_headers_and_separators(
        self, header: str, files: list[Path], content: str
    ) -> str:
        """Add main header to Rust-built content

        The Rust layer now includes file separators, so this function
        only needs to prepend the main schema header.

        Args:
            header: Schema header
            files: List of SQL files (unused, kept for API compatibility)
            content: Concatenated content from Rust (includes file separators)

        Returns:
            Content with main header
        """
        # Rust layer now includes file separators, just prepend main header
        return header + content

    def compute_hash(self) -> str:
        """Compute deterministic SHA256 hash of schema

        The hash includes both file paths and content, ensuring that any change
        to the schema (content or structure) is detected.

        Performance: Uses Rust extension when available for 30-60x speedup.

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

        # Use Rust extension if available (30-60x faster)
        if HAS_RUST:
            try:
                file_paths = [str(f) for f in files]
                return _core.hash_files(file_paths)
            except Exception:
                # Fallback to Python if Rust fails
                pass

        # Pure Python implementation (fallback)
        hasher = hashlib.sha256()

        for file in files:
            # Include relative path in hash (detects file renames)
            rel_path = file.relative_to(self.base_dir)
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
