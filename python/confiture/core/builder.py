"""Schema builder - builds PostgreSQL schemas from DDL files

The SchemaBuilder concatenates SQL files from db/schema/ in deterministic order
to create a complete schema file. This implements "Medium 1: Build from Source DDL".

Performance: Uses Rust extension (_core) when available for 10-50x speedup.
"""

import hashlib
import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from confiture.config.environment import Environment
from confiture.core import path_globs, tree_prefix
from confiture.core.fk_extractor import extract_and_strip_fks, generate_alter_statements
from confiture.core.progress import ProgressManager

# The seed-path rule lives in core.seed.paths; re-exported for callers that
# imported it from here.
from confiture.core.seed.paths import _SEED_DIR_RE, is_seed_path  # noqa: F401
from confiture.core.validation.comment_validator import CommentValidator
from confiture.exceptions import SchemaError
from confiture.models.results import SplitBuildResult

logger = logging.getLogger(__name__)

# The native hasher (confiture._core.hash_files): the same digest as the Python
# path, computed with a native SHA-256 and the GIL released. Absent on an sdist
# or editable install without a Rust toolchain; the Python path is then used and
# says so once per process at INFO.
_core: Any = None
HAS_RUST = False
_FALLBACK_NOTED: list[str] = []  # the first reason logged; empty until the fallback is used


def _note_fallback(reason: str) -> None:
    """Log, once per process, that the Python hash path is in use and why."""
    if _FALLBACK_NOTED:
        return
    _FALLBACK_NOTED.append(reason)
    logger.info("native extension %s: hashing schema files in Python", reason)


if not TYPE_CHECKING:
    try:
        from confiture import _core

        HAS_RUST = True
    except ImportError:
        pass


def _include_config(include: Any) -> dict[str, Any] | None:
    """One ``include_dirs`` entry — a string, a dict or a ``DirectoryConfig`` — as a config dict.

    A string means recursive ``**/*.sql``; a non-recursive entry with the
    default pattern reads ``*.sql``. An entry of another type is ignored.
    """
    if isinstance(include, str):
        return {
            "path": Path(include),
            "recursive": True,  # Default recursive for backward compatibility
            "include": ["**/*.sql"],
            "exclude": [],
            "auto_discover": True,
            "order": 0,
        }
    if isinstance(include, dict):
        recursive = include.get("recursive", True)
        default_include = ["**/*.sql"] if recursive else ["*.sql"]
        return {
            "path": Path(include["path"]),
            "recursive": recursive,
            "include": include.get("include", default_include),
            "exclude": include.get("exclude", []),
            "auto_discover": include.get("auto_discover", True),
            "order": include.get("order", 0),
        }
    if hasattr(include, "path"):  # DirectoryConfig object
        include_patterns = include.include
        if include_patterns == ["**/*.sql"] and not include.recursive:
            include_patterns = ["*.sql"]
        return {
            "path": Path(include.path),
            "recursive": include.recursive,
            "include": include_patterns,
            "exclude": include.exclude,
            "auto_discover": include.auto_discover,
            "order": include.order,
        }
    return None


@dataclass(frozen=True)
class SelectedFile:
    """A file the build reads, and how it came to be in the build.

    Attributes:
        path: The file itself.
        entry: The ``include_dirs`` entry whose directory it was found under.
        order: That entry's ``order`` value.
        pattern: The entry's include pattern that matched it — the first, when
            more than one would.
    """

    path: Path
    entry: Path
    order: int
    pattern: str


@dataclass(frozen=True)
class PatternDiagnostic:
    """A configured pattern that does not select what its author would expect.

    Attributes:
        code: The error-code registry entry that names the situation.
        entry: The ``include_dirs`` entry the pattern is written under.
        pattern: The pattern as written.
        message: What it selects, and what a reader would expect it to select.
    """

    code: str
    entry: Path
    pattern: str
    message: str


@dataclass(frozen=True)
class SelectionReport:
    """What a build would read, before anything is read.

    Attributes:
        env: The environment the selection was made for.
        files: The selected files, in build order, each with its provenance.
        patterns: One note per pattern that does not select what it appears to.
    """

    env: str
    files: list[SelectedFile]
    patterns: list[PatternDiagnostic]


def _first_occurrences(selected: list[SelectedFile]) -> list[SelectedFile]:
    """*selected* with each resolved path kept once, at its first appearance.

    Two include patterns can select the same file — ``["**/*.sql", "*.sql"]``
    over a flat directory selects every file twice. The build reads it once.
    """
    seen: set[Path] = set()
    unique: list[SelectedFile] = []
    for file in selected:
        resolved = file.path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(file)
    return unique


def _walk_files(directory: Path, *, recursive: bool) -> Iterator[Path]:
    """Every file under *directory*, once, in a deterministic order.

    Directory symlinks are not descended into, matching what ``rglob`` does on
    the Python versions confiture supports. ``recursive`` bounds the walk; the
    patterns then filter what it found, so neither decides half of the other's
    job.
    """
    for entry in sorted(directory.iterdir()):
        if entry.is_dir():
            if recursive and not entry.is_symlink():
                yield from _walk_files(entry, recursive=recursive)
            continue
        yield entry


def _first_matching(rel_path: Path, include_patterns: list[str]) -> str | None:
    """The first include pattern that selects *rel_path*, or None if none does."""
    for pattern in include_patterns:
        if path_globs.matches(rel_path, pattern):
            return pattern
    return None


def _sorted_block(block: list[SelectedFile], *, numbered: bool) -> list[SelectedFile]:
    """One ``order`` block, in the sequence the configured sort mode gives it."""
    if numbered:
        by_path = {record.path: record for record in block}
        return [by_path[path] for path in tree_prefix.order(list(by_path))]
    return sorted(block, key=lambda record: record.path)


def _order_blocks(selected: list[SelectedFile]) -> list[list[SelectedFile]]:
    """*selected* grouped by ``order`` value, the groups low to high."""
    blocks: dict[int, list[SelectedFile]] = {}
    for record in selected:
        blocks.setdefault(record.order, []).append(record)
    return [blocks[order] for order in sorted(blocks)]


def _resolved_dir_paths(items: Any) -> list[Path]:
    """Absolute paths of a directory list (strings, ``{path: …}`` dicts or ``DirectoryConfig``)."""
    paths: list[Path] = []
    for item in items:
        if isinstance(item, str):
            paths.append(Path(item).resolve())
        elif isinstance(item, dict):
            paths.append(Path(item["path"]).resolve())
        elif hasattr(item, "path"):
            paths.append(Path(item.path).resolve())
    return paths


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

    def __init__(self, env: str | Environment, project_dir: Path | None = None):
        """Initialize SchemaBuilder with recursive directory support

        Args:
            env: Environment name (e.g., "local", "production") or a
                pre-loaded Environment instance.
            project_dir: Project root directory. If None, uses current directory.
                Ignored when *env* is already an Environment.
        """
        if isinstance(env, Environment):
            self.env_config = env
        else:
            self.env_config = Environment.load(env, project_dir=project_dir)
        self.env_name: str = env if isinstance(env, str) else self.env_config.name

        # Validate include_dirs
        if not self.env_config.include_dirs:
            raise SchemaError(
                "No include_dirs specified in environment config",
                resolution_hint="Add an 'include_dirs' list to your environment YAML config (e.g., include_dirs: ['db/schema'])",
            )

        # Parse include_dirs (support string, dict, and DirectoryConfig formats)
        self.include_configs: list[dict[str, Any]] = [
            config
            for config in (_include_config(include) for include in self.env_config.include_dirs)
            if config is not None
        ]

        # Entries in build sequence: by ``order``, and — because the sort is
        # stable — in config order among equals. Two things read this: the
        # blocks the files are concatenated in, and, when two entries select
        # the same file, which of them owns it (the first one reached).
        self.include_configs.sort(key=lambda x: int(x["order"]))

        # Extract paths for backward compatibility
        self.include_dirs: list[Path] = [cfg["path"] for cfg in self.include_configs]

        # Base directory for relative path calculation
        # Find the common parent of all include directories
        self.base_dir = self._find_common_parent(self.include_dirs)

        # Resolve superuser_dirs / superuser_post_dirs to absolute paths for file classification
        self._superuser_paths: list[Path] = _resolved_dir_paths(self.env_config.superuser_dirs)
        self._superuser_post_paths: list[Path] = _resolved_dir_paths(
            self.env_config.superuser_post_dirs
        )

    def find_common_parent(self, paths: list[Path]) -> Path:
        """Public spelling of :meth:`_find_common_parent`."""
        return self._find_common_parent(paths)

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
            return Path()

        # Reconstruct path from common parts
        return Path(*common_parts)

    def _is_hex_prefix(self, filename: str) -> bool:
        """Whether *filename* carries a numeric prefix.

        Delegates to :mod:`confiture.core.tree_prefix`, the one answer the
        builder, the tree rules and ``generate alloc`` share: the run of hex
        digits before the first underscore, in either case, carrying at least
        one decimal digit so that ``add_column.sql`` stays a word (LINT-07).

        Args:
            filename: Filename or stem to check

        Returns:
            True if the name starts with a numeric prefix
        """
        return tree_prefix.is_numbered(filename)

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
        return [record.path for record in self._select()]

    def _select(self) -> list[SelectedFile]:
        """The files the build reads, in build order, each carrying its provenance.

        Overlapping entries — one for ``db/schema`` and one for
        ``db/schema/10_tables`` — are legal and select the same files twice. A
        file is built once, and it belongs to the entry with the lower
        ``order``; among entries sharing an ``order``, to the one listed first.
        That is what ``self.include_configs`` is sorted for: this loop reaches
        the owning entry before any other that would select the same file, so
        keeping the first occurrence keeps the right one.

        Returns:
            One record per file, deduplicated on the resolved path and sorted
            the way the build concatenates them.

        Raises:
            SchemaError: If an include directory is missing and not auto-discovered,
                or if nothing was selected.
        """
        selected: list[SelectedFile] = []
        for config in self.include_configs:
            selected.extend(self._select_entry(config))

        selected = self._without_excluded_dirs(_first_occurrences(selected))
        self._require_non_empty(selected)
        return self._in_build_order(selected)

    def selection_report(self) -> SelectionReport:
        """What ``build`` would read, and why — without reading any of it.

        Returns:
            The selected files in build order, each naming the ``include_dirs``
            entry, the ``order`` and the pattern that put it there, together
            with a note for every pattern that does not select what it appears
            to.

        Raises:
            SchemaError: For the same reasons :meth:`find_sql_files` does.
        """
        return SelectionReport(env=self.env_name, files=self._select(), patterns=[])

    def _select_entry(self, config: dict[str, Any]) -> list[SelectedFile]:
        """The files one ``include_dirs`` entry selects, in the order its patterns are written."""
        include_dir: Path = config["path"]
        if not include_dir.exists():
            if config["auto_discover"]:
                return []
            raise SchemaError(
                f"Include directory does not exist: {include_dir}",
                resolution_hint=f"Create the directory at {include_dir} or update include_dirs in your config",
            )

        order = int(config["order"])
        include_patterns = config["include"]
        exclude_patterns = config["exclude"]
        found: list[SelectedFile] = []
        for path in _walk_files(include_dir, recursive=config["recursive"]):
            rel_path = path.relative_to(include_dir)
            if path_globs.matches_any(rel_path, exclude_patterns):
                continue
            pattern = _first_matching(rel_path, include_patterns)
            if pattern is not None:
                found.append(
                    SelectedFile(path=path, entry=include_dir, order=order, pattern=pattern)
                )
        return found

    def _without_excluded_dirs(self, selected: list[SelectedFile]) -> list[SelectedFile]:
        """*selected* minus everything under ``exclude_dirs`` (the pattern-less legacy key)."""
        exclude_paths = [Path(directory) for directory in self.env_config.exclude_dirs]
        return [
            record
            for record in selected
            if not any(record.path.is_relative_to(excluded) for excluded in exclude_paths)
        ]

    def _require_non_empty(self, selected: list[SelectedFile]) -> None:
        """Refuse a build with nothing in it.

        Raises:
            SchemaError: If *selected* is empty.
        """
        if selected:
            return
        include_dirs_str = ", ".join(str(d) for d in self.include_dirs)
        raise SchemaError(
            f"No SQL files found in include directories: {include_dirs_str}",
            resolution_hint="Add .sql files to subdirectories like 00_common/, 10_tables/ or check your include/exclude patterns",
        )

    def _in_build_order(self, selected: list[SelectedFile]) -> list[SelectedFile]:
        """*selected* in the order the build concatenates it.

        ``order`` partitions the build: entries are grouped by their ``order``
        value and the groups are concatenated low to high. Within a group the
        configured sort decides — alphabetical, or numeric-prefix order under
        ``sort_mode: hex``. Every entry defaults to ``order: 0``, so a project
        that never sets the key has exactly one group, and that group's sort is
        the whole sort.

        The order entries are *listed* in sequences nothing: ``order`` is the
        only sequencing key, so ``- db/seeds`` written above ``- db/schema``
        still builds ``db/schema`` first when its ``order`` is lower. It breaks
        exactly one tie — entries sharing an ``order`` value keep their config
        order, which is what decides which entry owns a file two entries both
        select.

        Whether numeric prefixes are read at all is decided once, over every
        selected file: a two-block tree where only one block carries them sorts
        both blocks the same way, as it did before blocks existed.
        """
        # Numeric order, reading the prefix on every path component — see
        # core.tree_prefix for why the filename's own prefix is not enough.
        numbered = self.env_config.build.sort_mode == "hex" and any(
            self._is_hex_prefix(record.path.stem) for record in selected
        )
        ordered: list[SelectedFile] = []
        for block in _order_blocks(selected):
            ordered.extend(_sorted_block(block, numbered=numbered))
        return ordered

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
            except (OSError, UnicodeDecodeError) as e:
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
            error_messages.extend(
                f"  {error.file_path}:{error.line_number} - {error.message}" for error in errors
            )

        if spillovers and config.fail_on_spillover:
            should_fail = True
            error_messages.extend(
                f"  {spillover.file_path}:{spillover.line_number} - {spillover.message}"
                for spillover in spillovers
            )

        if should_fail:
            msg = "Comment validation failed:\n" + "\n".join(error_messages)
            raise SchemaError(msg)

    def _is_seed_file(self, file_path: Path) -> bool:
        """Check if file is a seed file based on path.

        A file is a seed when any path component contains ``seed`` or ``seeds``
        as a whole token — delimited by the component's start/end or a ``_`` /
        ``-`` separator (see :data:`_SEED_DIR_RE`). This recognises
        ordering-prefixed layouts such as ``30_seed_backend`` / ``seed_common``
        / ``10-seeds`` that an exact ``== "seed"`` match would miss, while still
        rejecting look-alikes like ``seedling`` and ``proceeds``.

        The env config's ``include_dirs`` deliberately does *not* drive this:
        ``SeedConfig`` has no seed-directory concept, so seeds are identified by
        this path heuristic rather than configuration (do not "fix" it back to a
        config lookup — there is no such option to honour).

        Matching is anchored at the include-root level (``self.base_dir`` and
        below) — the absolute filesystem prefix *above* the project is ignored,
        so a project living under e.g. ``/home/me/my_seed_app/`` does not have
        all of its files misclassified as seeds. The include root's own name is
        still considered, so a project whose root *is* ``seeds`` works.

        Args:
            file_path: Path to check

        Returns:
            True if a path component at/below the include root is a seed directory
        """
        return is_seed_path(file_path, anchor=self.base_dir.parent)

    def is_seed_file(self, file_path: Path) -> bool:
        """Public spelling of :meth:`_is_seed_file`."""
        return self._is_seed_file(file_path)

    def categorize_sql_files(self) -> tuple[list[Path], list[Path]]:
        """Categorize SQL files into schema and seed files.

        Uses a path heuristic to identify seeds: a file is a seed when a path
        component carries ``seed``/``seeds`` as a whole token (start/end or
        ``_``/``-`` delimited) — see :meth:`_is_seed_file`.

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
                raise SchemaError(
                    "Custom separator style requires custom_template",
                    resolution_hint="Set build.separators.custom_template in your config when using style: custom",
                )
            template = self.env_config.build.separators.custom_template
            return "\n" + template.format(file_path=rel_path) + "\n"

        else:
            raise SchemaError(
                f"Invalid separator style: {style}",
                resolution_hint="Use one of: block_comment, line_comment, mysql, custom",
            )

    def build(
        self,
        output_path: Path | None = None,
        schema_only: bool = False,
        progress: ProgressManager | None = None,
    ) -> str:
        """Build schema by concatenating DDL files

        Generates a complete schema file by concatenating all SQL files in
        deterministic order, with headers and file separators.

        Args:
            output_path: Optional path to write schema file. If None, only returns content.
            schema_only: If True, exclude seed files. Default False (include all files).
            progress: Optional ProgressManager for displaying build progress

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

            >>> # With progress tracking
            >>> with ProgressManager() as pm:
            ...     schema = builder.build(progress=pm)
        """
        discover_task = None
        if progress:
            discover_task = progress.add_task("Discovering SQL files...", total=None)

        files = self.find_sql_files()

        if progress and discover_task is not None:
            progress.update(discover_task, len(files))

        # Filter to schema-only files if requested
        if schema_only:
            schema_files, _ = self.categorize_sql_files()
            files = schema_files

        validate_task = None
        if progress:
            validate_task = progress.add_task("Validating comments...", total=len(files))

        # Pre-build validation: check for unclosed comments
        self._validate_comments(files)

        if progress and validate_task is not None:
            progress.finish_task(validate_task)

        # Generate header
        header = self._generate_header(len(files))

        process_task = None
        if progress:
            process_task = progress.add_task("Processing files...", total=len(files))

        schema = self._build_python(header, files, progress=progress)

        # Two-pass FK processing: strip FK constraints from CREATE TABLE,
        # then emit ALTER TABLE ADD CONSTRAINT at the end (issue #94)
        if self.env_config.build.two_pass:
            stripped_sql, fk_infos = extract_and_strip_fks(schema)
            if fk_infos:
                alter_block = generate_alter_statements(fk_infos)
                schema = stripped_sql + "\n" + alter_block + "\n"
            else:
                schema = stripped_sql

        if progress and process_task is not None:
            progress.finish_task(process_task)

        write_task = None
        if progress:
            write_task = progress.add_task("Writing output...", total=1)

        # Write to file if requested
        if output_path:
            try:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(schema, encoding="utf-8")
            except OSError as e:
                raise SchemaError(
                    f"Error writing schema to {output_path}: {e}",
                    resolution_hint="Check that the output directory exists and you have write permissions",
                ) from e

        if progress and write_task is not None:
            progress.update(write_task, 1)

        return schema

    def _build_python(
        self,
        header: str,
        files: list[Path],
        progress: ProgressManager | None = None,
    ) -> str:
        """Pure Python implementation of schema building (fallback)

        Args:
            header: Schema header
            files: List of SQL files to concatenate
            progress: Optional ProgressManager for tracking progress

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

                # Update progress
                if progress:
                    progress.update(None, advance=1)

            except (OSError, UnicodeDecodeError) as e:
                raise SchemaError(f"Error reading {file}: {e}") from e

        return "".join(parts)

    def _is_superuser_file(self, file_path: Path) -> bool:
        """Check if a file belongs to a superuser directory.

        A file is a superuser file if its resolved path is under any of the
        directories listed in ``superuser_dirs``.

        Args:
            file_path: Absolute path to check.

        Returns:
            True if the file is under a superuser directory.
        """
        return any(file_path.is_relative_to(su_dir) for su_dir in self._superuser_paths)

    def _is_superuser_post_file(self, file_path: Path) -> bool:
        """Check if a file belongs to a superuser post directory.

        A file is a superuser-post file if its resolved path is under any of
        the directories listed in ``superuser_post_dirs``.

        Args:
            file_path: Absolute path to check.

        Returns:
            True if the file is under a superuser post directory.
        """
        return any(file_path.is_relative_to(su_dir) for su_dir in self._superuser_post_paths)

    def build_split(
        self,
        output_dir: str | Path,
        schema_only: bool = False,
    ) -> SplitBuildResult:
        """Build schema split into three SQL files for phased deployment.

        Files are routed to three phases based on directory classification:

        1. **superuser_pre** — from ``superuser_dirs`` (roles, extensions, schemas)
        2. **app** — everything not in superuser_pre or superuser_post dirs
        3. **superuser_post** — from ``superuser_post_dirs`` (grants on objects, role settings)

        Sort order is preserved within each phase.  If a directory appears in
        both ``superuser_post_dirs`` and ``superuser_dirs``, post takes priority.

        Args:
            output_dir: Directory to write the three output files into.
            schema_only: If True, exclude seed files.

        Returns:
            SplitBuildResult with paths and metadata for all three files.

        Raises:
            SchemaError: If schema build fails.
        """

        output_dir = Path(output_dir)

        start = time.monotonic()

        files = self.find_sql_files()

        if schema_only:
            schema_files, _ = self.categorize_sql_files()
            files = schema_files

        self._validate_comments(files)

        # Partition files — priority: superuser_post > superuser_pre > app
        superuser_pre_files: list[Path] = []
        superuser_post_files: list[Path] = []
        app_files: list[Path] = []
        for f in files:
            if self._is_superuser_post_file(f):
                superuser_post_files.append(f)
            elif self._is_superuser_file(f):
                superuser_pre_files.append(f)
            else:
                app_files.append(f)

        env_name = self.env_config.name
        superuser_pre_path = output_dir / f"schema_{env_name}_superuser_pre.sql"
        app_path = output_dir / f"schema_{env_name}_app.sql"
        superuser_post_path = output_dir / f"schema_{env_name}_superuser_post.sql"

        output_dir.mkdir(parents=True, exist_ok=True)

        # Build superuser pre SQL
        if superuser_pre_files:
            header = self._generate_header(len(superuser_pre_files))
            superuser_pre_sql = self._build_python(header, superuser_pre_files)
        else:
            superuser_pre_sql = ""
        superuser_pre_path.write_text(superuser_pre_sql, encoding="utf-8")

        # Build app SQL
        header = self._generate_header(len(app_files))
        app_sql = self._build_python(header, app_files)

        if self.env_config.build.two_pass:
            stripped_sql, fk_infos = extract_and_strip_fks(app_sql)
            if fk_infos:
                alter_block = generate_alter_statements(fk_infos)
                app_sql = stripped_sql + "\n" + alter_block + "\n"
            else:
                app_sql = stripped_sql

        app_path.write_text(app_sql, encoding="utf-8")

        # Build superuser post SQL
        if superuser_post_files:
            header = self._generate_header(len(superuser_post_files))
            superuser_post_sql = self._build_python(header, superuser_post_files)
        else:
            superuser_post_sql = ""
        superuser_post_path.write_text(superuser_post_sql, encoding="utf-8")

        elapsed_ms = int((time.monotonic() - start) * 1000)

        return SplitBuildResult(
            success=True,
            superuser_pre_path=str(superuser_pre_path),
            app_path=str(app_path),
            superuser_post_path=str(superuser_post_path),
            superuser_pre_files=len(superuser_pre_files),
            app_files=len(app_files),
            superuser_post_files=len(superuser_post_files),
            superuser_pre_size_bytes=len(superuser_pre_sql.encode("utf-8")),
            app_size_bytes=len(app_sql.encode("utf-8")),
            superuser_post_size_bytes=len(superuser_post_sql.encode("utf-8")),
            hash=self.compute_hash(),
            execution_time_ms=elapsed_ms,
        )

    def compute_hash(self) -> str:
        """Compute deterministic SHA256 hash of schema

        The hash includes both file paths and content, ensuring that any change
        to the schema (content or structure) is detected.

        The hash reflects **what** SQL is generated (``include_dirs`` file
        contents and paths) — not **how** it is deployed.  In particular,
        ``superuser_dirs`` (which only controls file partitioning in
        ``build_split()``) is deliberately excluded so that adding or
        changing it does not invalidate caches or trigger unnecessary
        rebuilds (see issue #103).

        The native extension computes the same digest when it is installed;
        otherwise the Python path does, and says so once per process at INFO.

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

        if HAS_RUST:
            try:
                digest: str = _core.hash_files([str(f) for f in files], str(self.base_dir))
            except OSError as e:
                # The same failure the Python path reports: a file that cannot be read.
                raise SchemaError(f"Error reading schema files for hash: {e}") from e
            except Exception as e:  # Reason: a fault of any kind in the native extension falls back to the Python hash
                _note_fallback(f"failed ({type(e).__name__}: {e})")
            else:
                return digest
        else:
            _note_fallback("not installed")

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
            except OSError as e:
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
