"""Schema builder - builds PostgreSQL schemas from DDL files

The SchemaBuilder concatenates SQL files from db/schema/ in deterministic order
to create a complete schema file. This implements "Medium 1: Build from Source DDL".

Performance: Uses Rust extension (_core) when available for 10-50x speedup.
"""

import hashlib
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from confiture.config.environment import Environment
from confiture.core.validators import CommentValidator
from confiture.exceptions import SchemaError

# Try to import Rust extension for 10-50x performance boost
_core: Any = None
HAS_RUST = False

if not TYPE_CHECKING:
    try:
        from confiture import _core  # type: ignore

        HAS_RUST = True
    except ImportError:
        pass


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
        """Initialize SchemaBuilder with recursive directory support

        Args:
            env: Environment name (e.g., "local", "production")
            project_dir: Project root directory. If None, uses current directory.
        """
        self.env_config = Environment.load(env, project_dir=project_dir)

        # Validate include_dirs
        if not self.env_config.include_dirs:
            raise SchemaError("No include_dirs specified in environment config")

        # Parse include_dirs (support string, dict, and DirectoryConfig formats)
        self.include_configs = []
        for include in self.env_config.include_dirs:
            if isinstance(include, str):
                self.include_configs.append(
                    {
                        "path": Path(include),
                        "recursive": True,  # Default recursive for backward compatibility
                        "include": ["**/*.sql"],
                        "exclude": [],
                        "auto_discover": True,
                        "order": 0,
                    }
                )
            elif isinstance(include, dict):
                recursive = include.get("recursive", True)
                default_include = ["**/*.sql"] if recursive else ["*.sql"]
                self.include_configs.append(
                    {
                        "path": Path(include["path"]),
                        "recursive": recursive,
                        "include": include.get("include", default_include),
                        "exclude": include.get("exclude", []),
                        "auto_discover": include.get("auto_discover", True),
                        "order": include.get("order", 0),
                    }
                )
            elif hasattr(include, "path"):  # DirectoryConfig object
                recursive = include.recursive
                # If using default include pattern and recursive=False, adjust to non-recursive pattern
                include_patterns = include.include
                if include_patterns == ["**/*.sql"] and not recursive:
                    include_patterns = ["*.sql"]
                self.include_configs.append(
                    {
                        "path": Path(include.path),
                        "recursive": recursive,
                        "include": include_patterns,
                        "exclude": include.exclude,
                        "auto_discover": include.auto_discover,
                        "order": include.order,
                    }
                )
            elif isinstance(include, dict):
                self.include_configs.append(
                    {
                        "path": Path(include["path"]),
                        "recursive": include.get("recursive", True),
                        "include": include.get("include", ["**/*.sql"]),
                        "exclude": include.get("exclude", []),
                        "auto_discover": include.get("auto_discover", True),
                        "order": include.get("order", 0),
                    }
                )
            elif hasattr(include, "path"):  # DirectoryConfig object
                self.include_configs.append(
                    {
                        "path": Path(include.path),
                        "recursive": include.recursive,
                        "include": include.include,
                        "exclude": include.exclude,
                        "auto_discover": include.auto_discover,
                        "order": include.order,
                    }
                )
            elif isinstance(include, dict):
                self.include_configs.append(
                    {
                        "path": Path(include["path"]),
                        "recursive": include.get("recursive", True),
                        "order": include.get("order", 0),
                    }
                )
            elif hasattr(include, "path"):  # DirectoryConfig object
                self.include_configs.append(
                    {
                        "path": Path(include.path),
                        "recursive": include.recursive,
                        "order": include.order,
                    }
                )

        # Sort by order
        self.include_configs.sort(key=lambda x: int(x["order"]))  # type: ignore

        # Extract paths for backward compatibility
        self.include_dirs: list[Path] = [cfg["path"] for cfg in self.include_configs]  # type: ignore

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
        for parts_at_level in zip(*all_parts, strict=False):
            if len(set(parts_at_level)) == 1:
                common_parts.append(parts_at_level[0])
            else:
                break

        if not common_parts:
            # No common parent, use current directory
            return Path(".")

        # Reconstruct path from common parts
        return Path(*common_parts)

    def _is_hex_prefix(self, filename: str) -> bool:
        """Check if filename starts with hexadecimal prefix.

        Hex prefixes must consist of valid hexadecimal characters where
        all letters are uppercase, followed by an underscore.

        Args:
            filename: Filename to check

        Returns:
            True if filename starts with valid hex prefix
        """
        parts = filename.split("_", 1)
        if len(parts) != 2:
            return False
        prefix = parts[0]

        # Check that all letters are uppercase
        if not all(c.isupper() or c.isdigit() for c in prefix):
            return False

        try:
            int(prefix, 16)
            return True
        except ValueError:
            return False

    def _hex_sort_key(self, path: Path) -> tuple[float | int, str]:
        """Generate sort key for hexadecimal-prefixed files.

        Args:
            path: File path to generate sort key for

        Returns:
            Tuple for sorting: (hex_value, rest_of_filename) or (inf, filename)
        """
        filename = path.stem
        if self._is_hex_prefix(filename):
            parts = filename.split("_", 1)
            hex_value = int(parts[0], 16)
            rest = parts[1] if len(parts) > 1 else ""
            return (hex_value, rest)
        return (float("inf"), filename)

    def find_sql_files(self) -> list[Path]:
        """Discover SQL files with pattern matching

        Files are returned in deterministic order based on configuration.
        Supports glob patterns for include/exclude and auto-discovery.

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

        for config in self.include_configs:
            include_dir: Path = config["path"]  # type: ignore
            recursive = config["recursive"]
            include_patterns = config["include"]
            exclude_patterns = config["exclude"]
            auto_discover = config["auto_discover"]

            if not include_dir.exists():
                if auto_discover:
                    # Skip non-existent directories in auto-discover mode
                    continue
                else:
                    raise SchemaError(f"Include directory does not exist: {include_dir}")

            # Find files matching include patterns
            for pattern in include_patterns:  # type: ignore
                if recursive:
                    sql_files = list(include_dir.rglob(pattern))
                else:
                    sql_files = list(include_dir.glob(pattern))

                # Filter out excluded patterns
                for file in sql_files:
                    rel_path = file.relative_to(include_dir)
                    is_excluded = any(
                        rel_path.match(exclude_pattern)
                        for exclude_pattern in exclude_patterns  # type: ignore
                    )

                    if not is_excluded:
                        all_sql_files.append(file)

        # Filter out excluded directories (legacy support)
        filtered_files = []
        exclude_paths = [Path(d) for d in self.env_config.exclude_dirs]

        for file in all_sql_files:
            # Check if file is in any excluded directory
            is_excluded = any(file.is_relative_to(exclude_dir) for exclude_dir in exclude_paths)
            if not is_excluded:
                filtered_files.append(file)

        if not filtered_files:
            include_dirs_str = ", ".join(str(d) for d in self.include_dirs)
            raise SchemaError(
                f"No SQL files found in include directories: {include_dirs_str}\n"
                f"Expected files in subdirectories like 00_common/, 10_tables/, etc."
            )

        # Sort files based on configuration
        if self.env_config.build.sort_mode == "hex":
            # Check if any file has hex prefix
            has_hex = any(self._is_hex_prefix(f.stem) for f in filtered_files)

            if has_hex:
                # Sort by hex value
                return sorted(filtered_files, key=self._hex_sort_key)
            else:
                # Default alphabetical sort
                return sorted(filtered_files)
        else:
            # Default alphabetical sort
            return sorted(filtered_files)

    def _validate_comments(self, files: list[Path]) -> None:
        """Validate SQL files for unclosed block comments

        This method is called before concatenation to catch errors early
        that would corrupt the schema.

        Args:
            files: List of SQL files to validate

        Raises:
            SchemaError: If validation fails and configured to fail
        """
        config = self.env_config.build.validate_comments

        if not config.enabled:
            return

        # Read all files and validate
        files_and_content = {}
        for file in files:
            try:
                files_and_content[file] = file.read_text(encoding="utf-8")
            except Exception as e:
                raise SchemaError(f"Error reading {file}: {e}") from e

        # Run validator
        validator = CommentValidator()
        violations = validator.validate_files(files_and_content)

        if not violations:
            return

        # Process violations based on configuration
        errors = [v for v in violations if v.violation_type == "unclosed"]
        spillovers = [v for v in violations if v.violation_type == "spillover"]

        should_fail = False
        error_messages = []

        if errors and config.fail_on_unclosed_blocks:
            should_fail = True
            for error in errors:
                error_messages.append(f"  {error.file_path}:{error.line_number} - {error.message}")

        if spillovers and config.fail_on_spillover:
            should_fail = True
            for spillover in spillovers:
                error_messages.append(
                    f"  {spillover.file_path}:{spillover.line_number} - {spillover.message}"
                )

        if should_fail:
            msg = "Comment validation failed:\n" + "\n".join(error_messages)
            raise SchemaError(msg)

    def _is_seed_file(self, file_path: Path) -> bool:
        """Check if file is a seed file based on path.

        Files are considered seeds if their path contains 'seed' or 'seeds'
        as a directory component.

        Args:
            file_path: Path to check

        Returns:
            True if file is in a seed/seeds directory
        """
        parts = [part.lower() for part in file_path.parts]
        return "seed" in parts or "seeds" in parts

    def categorize_sql_files(self) -> tuple[list[Path], list[Path]]:
        """Categorize SQL files into schema and seed files.

        Uses path heuristic to identify seeds: files are seeds if their path
        contains 'seed' or 'seeds' as a directory component.

        Returns:
            Tuple of (schema_files, seed_files)

        Example:
            >>> builder = SchemaBuilder(env="local")
            >>> schema_files, seed_files = builder.categorize_sql_files()
            >>> print(f"Schema: {len(schema_files)}, Seeds: {len(seed_files)}")
            Schema: 15, Seeds: 8
        """
        all_files = self.find_sql_files()
        schema_files = []
        seed_files = []

        for file in all_files:
            if self._is_seed_file(file):
                seed_files.append(file)
            else:
                schema_files.append(file)

        return schema_files, seed_files

    def _get_separator_for_file(self, file_path: Path) -> str:
        """Generate file separator for schema builder

        Creates a visual separator between concatenated SQL files.
        Style is configurable (block_comment, line_comment, mysql, custom).

        Args:
            file_path: Path to the file being separated

        Returns:
            Separator string with newlines

        Raises:
            SchemaError: If separator style is invalid
        """
        style = self.env_config.build.separators.style

        # Convert to relative path if absolute
        try:
            if file_path.is_absolute():
                rel_path = file_path.relative_to(self.base_dir)
            else:
                rel_path = file_path
        except (ValueError, AttributeError):
            rel_path = file_path

        # Block comment style (recommended, immune to spillover)
        if style == "block_comment":
            sep = "/* " + "=" * 42 + "\n"
            sep += f" * File: {rel_path}\n"
            sep += " * " + "=" * 42 + " */\n"
            return "\n" + sep + "\n"

        # Line comment style (backward compatible)
        elif style == "line_comment":
            sep = "-- " + "=" * 42 + "\n"
            sep += f"-- File: {rel_path}\n"
            sep += "-- " + "=" * 42 + "\n"
            return "\n" + sep + "\n"

        # MySQL style
        elif style == "mysql":
            sep = "# " + "=" * 42 + "\n"
            sep += f"# File: {rel_path}\n"
            sep += "# " + "=" * 42 + "\n"
            return "\n" + sep + "\n"

        # Custom style
        elif style == "custom":
            if not self.env_config.build.separators.custom_template:
                raise SchemaError("Custom separator style requires custom_template")
            template = self.env_config.build.separators.custom_template
            return "\n" + template.format(file_path=rel_path) + "\n"

        else:
            raise SchemaError(f"Invalid separator style: {style}")

    def build(self, output_path: Path | None = None, schema_only: bool = False) -> str:
        """Build schema by concatenating DDL files

        Generates a complete schema file by concatenating all SQL files in
        deterministic order, with headers and file separators.

        Performance: Uses Rust extension when available for 10-50x speedup.
        Falls back gracefully to Python implementation if Rust unavailable.

        Args:
            output_path: Optional path to write schema file. If None, only returns content.
            schema_only: If True, exclude seed files. Default False (include all files).

        Returns:
            Generated schema content as string

        Raises:
            SchemaError: If schema build fails

        Example:
            >>> builder = SchemaBuilder(env="local")
            >>> schema = builder.build(output_path=Path("schema.sql"))
            >>> print(f"Generated {len(schema)} bytes")

            >>> # Build schema without seeds
            >>> schema = builder.build(schema_only=True)
        """
        files = self.find_sql_files()

        # Filter to schema-only files if requested
        if schema_only:
            schema_files, _ = self.categorize_sql_files()
            files = schema_files

        # Pre-build validation: check for unclosed comments
        self._validate_comments(files)

        # Generate header
        header = self._generate_header(len(files))

        # Use Rust extension if available (10-50x faster)
        # Note: Rust extension uses line_comment separator style
        # If a different style is configured, fall back to Python
        use_rust = HAS_RUST and self.env_config.build.separators.style == "line_comment"

        if use_rust:
            try:
                # Build file content using Rust
                file_paths = [str(f) for f in files]
                content: str = _core.build_schema(file_paths)

                # Add headers and separators (Python side for flexibility)
                schema = self._add_headers_and_separators(header, files, content)
            except Exception:
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
                # Add file separator (uses configured style)
                parts.append(self._get_separator_for_file(file))

                # Add file content
                content = file.read_text(encoding="utf-8")
                parts.append(content)

                # Ensure newline at end
                if not content.endswith("\n"):
                    parts.append("\n")

            except Exception as e:
                raise SchemaError(f"Error reading {file}: {e}") from e

        return "".join(parts)

    def _add_headers_and_separators(self, header: str, _files: list[Path], content: str) -> str:
        """Add main header to Rust-built content

        The Rust layer now includes file separators, so this function
        only needs to prepend the main schema header.

        Args:
            header: Schema header
            _files: List of SQL files (unused, kept for API compatibility)
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
                hash_result: str = _core.hash_files(file_paths)
                return hash_result
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
