"""Orchestrator for sequential seed file execution.

Provides high-level orchestration for applying seed files either
sequentially (each in own savepoint) or concatenated (default behavior).
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import psycopg
from rich.console import Console

from confiture.core.progress import ProgressManager
from confiture.core.psql_applier import apply_sql_via_psql
from confiture.core.seed.executor import SeedExecutor
from confiture.core.seed.insert_to_copy_converter import InsertToCopyConverter
from confiture.exceptions import ConfiturError, SchemaError, base_message

if TYPE_CHECKING:
    from confiture.config.environment import SeedProfile


def apply_profile_filter(files: list[Path], profile: SeedProfile) -> list[Path]:
    """Filter *files* by a profile's include-then-exclude filename globs.

    Order is preserved. Empty ``include`` means "start from all files".
    """

    def _matches_any(name: str, patterns: list[str]) -> bool:
        return any(fnmatch.fnmatch(name, pat) for pat in patterns)

    result: list[Path] = []
    for path in files:
        name = path.name
        if profile.include and not _matches_any(name, profile.include):
            continue
        if profile.exclude and _matches_any(name, profile.exclude):
            continue
        result.append(path)
    return result


def apply_seed_files(connection_url: str, seed_files: list[Path]) -> int:
    """Apply ordered seed files into the database at *connection_url* via ``psql``.

    Used to load seeds into **ephemeral** / template databases (artifact builds,
    test-db provisioning) where no long-lived :class:`SeedApplier` is in play.
    Each file is applied independently with
    :func:`confiture.core.psql_applier.apply_sql_via_psql`, so ``COPY … FROM
    stdin`` data loads correctly (psycopg's ``execute()`` cannot consume inline
    COPY rows).

    Requires ``psql`` on PATH. Application is **fail-fast and per-file**: there is
    no per-file savepoint and no whole-batch rollback — on a bad seed file this
    raises immediately, leaving earlier files committed. This is safe for the
    ephemeral callers, which drop and rebuild the database on any failure so
    partial commits never escape. The interactive :class:`SeedApplier` /
    ``confiture seed apply`` path is unaffected.

    Args:
        connection_url: Connection URL of the target database.
        seed_files: Ordered seed files to apply.

    Returns:
        The number of seed files applied.

    Raises:
        SchemaError: If ``psql`` is unavailable or a seed file fails to apply
            (the message names the offending file).
    """
    for seed_file in seed_files:
        try:
            apply_sql_via_psql(connection_url, sql_file=seed_file)
        except SchemaError as exc:
            # base_message: the inner hint is carried forward on its own
            # field below, so quoting str(exc) would render it twice (#211).
            raise SchemaError(
                f"Failed to apply seed file {seed_file.name}: {base_message(exc)}",
                resolution_hint=exc.resolution_hint,
            ) from exc
    return len(seed_files)


@dataclass
class ApplyResult:
    """Result of seed application.

    Tracks successful and failed files during sequential execution.
    """

    total: int = 0
    succeeded: int = 0
    failed: int = 0
    failed_files: list[str] = field(default_factory=list)
    seed_profile: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization.

        Returns:
            Dictionary with all fields suitable for JSON output.
        """
        return {
            "total": self.total,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "failed_files": self.failed_files,
            "success": self.failed == 0,
            "seed_profile": self.seed_profile,
        }


class SeedApplier:
    """Orchestrates seed file discovery and execution.

    Handles:
    - Finding seed files in sorted order
    - Mode selection (concatenate vs sequential)
    - Progress reporting
    - Error collection and reporting
    """

    def __init__(
        self,
        seeds_dir: Path,
        env: str | None = None,
        connection=None,
        console: Console | None = None,
        copy_format: bool = False,
        copy_threshold: int = 1000,
    ) -> None:
        """Initialize SeedApplier.

        Args:
            seeds_dir: Path to seeds directory
            env: Environment name (optional, for context)
            connection: Database connection (optional, for sequential execution)
            console: Rich console for output (optional)
        """
        self.seeds_dir = Path(seeds_dir)
        self.env = env or "local"
        self.connection = connection
        self.console = console or Console()
        # ``seed apply --copy-format --copy-threshold N``: INSERT files with at
        # least N rows are converted to COPY before execution.
        self.copy_format = copy_format
        self.copy_threshold = copy_threshold

    def find_seed_files(self, profile: SeedProfile | None = None) -> list[Path]:
        """Discover and return sorted seed files, optionally filtered by *profile*.

        Returns SQL files in sorted order from the (top-level, non-recursive)
        seeds directory. Non-SQL files are ignored. When *profile* is None the
        result is byte-identical to the historical apply-all behaviour.

        Args:
            profile: Optional seed profile selecting an include/exclude subset by
                filename glob.

        Returns:
            List of Path objects for SQL files in sorted order.
        """
        if not self.seeds_dir.exists():
            return []

        # Find all .sql files (top-level only — globs match filenames)
        sql_files = sorted(self.seeds_dir.glob("*.sql"))
        if profile is None:
            return sql_files
        return apply_profile_filter(sql_files, profile)

    def apply_sequential(
        self,
        continue_on_error: bool = False,
        progress: ProgressManager | None = None,
        profile: SeedProfile | None = None,
        transaction_mode: str = "savepoint",
    ) -> ApplyResult:
        """Apply seed files sequentially, one savepoint or one transaction per file.

        Each file executed in its own savepoint for isolation.
        Avoids PostgreSQL parser limits from concatenation.

        Args:
            continue_on_error: Continue applying files if one fails
            progress: Optional ProgressManager for displaying progress
            profile: Optional seed profile selecting a subset of files
            transaction_mode: ``"savepoint"`` runs every file inside the caller's
                transaction with a savepoint each (a failure rolls back that file
                only); ``"transaction"`` commits after each file, so the files
                before a failure stay applied (``seed.transaction_mode`` in the
                environment YAML)

        Returns:
            ApplyResult with tracking info

        Raises:
            ValueError: If connection not set
        """
        if not self.connection:
            raise ValueError("Database connection required for sequential execution")

        discover_task = None
        if progress:
            discover_task = progress.add_task("Discovering seed files...", total=None)

        # Discover seed files
        files = self.find_seed_files(profile=profile)
        result = ApplyResult(total=len(files))

        if progress and discover_task is not None:
            progress.update(discover_task, len(files))

        if not files:
            self.console.print("[yellow]⚠ No seed files found[/yellow]")
            return result

        apply_task = None
        if progress:
            apply_task = progress.add_task("Applying seed files...", total=len(files))

        executor = SeedExecutor(connection=self.connection)

        # Apply each file
        for i, seed_file in enumerate(files, 1):
            try:
                self._apply_seed_file(executor, seed_file, f"sp_seed_{i:03d}", transaction_mode)
                result.succeeded += 1
            except (OSError, UnicodeDecodeError, psycopg.Error, ConfiturError) as e:
                if transaction_mode == "transaction":
                    self.connection.rollback()
                result.failed += 1
                result.failed_files.append(seed_file.name)
                self.console.print(f"[red]✗ {e}[/red]")
                if not continue_on_error:
                    if progress and apply_task is not None:
                        progress.update(apply_task, advance=1)
                    raise
            if progress and apply_task is not None:
                progress.update(apply_task, advance=1)

        if progress and apply_task is not None:
            progress.finish_task(apply_task)

        self._print_seed_summary(result)
        return result

    def _apply_seed_file(
        self, executor: SeedExecutor, seed_file: Path, savepoint_name: str, transaction_mode: str
    ) -> None:
        """Run one seed file (as COPY when large enough); commit in transaction mode."""
        assert self.connection is not None
        self.console.print(f"[cyan]→ {seed_file.name}[/cyan]", end=" ")
        sql_content = seed_file.read_text(encoding="utf-8")
        if self.copy_format and count_insert_rows(sql_content) >= self.copy_threshold:
            sql_content = InsertToCopyConverter().convert(sql_content)
            self.console.print("[dim](COPY)[/dim]", end=" ")
        executor.execute_sql(sql_content, savepoint_name, source=seed_file)
        if transaction_mode == "transaction":
            self.connection.commit()
        self.console.print("[green]✓[/green]")

    def _print_seed_summary(self, result: ApplyResult) -> None:
        self.console.print("\n" + "=" * 50)
        self.console.print(f"Applied {result.succeeded}/{result.total} seed files")
        if result.failed > 0:
            self.console.print(f"[yellow]⚠ {result.failed} files failed[/yellow]")
            for failed_file in result.failed_files:
                self.console.print(f"  - {failed_file}")


_ROW_SEPARATOR = re.compile(r"\)\s*,\s*\(")
_INSERT = re.compile(r"\bINSERT\s+INTO\b", re.IGNORECASE)


def count_insert_rows(sql: str) -> int:
    """Rows an INSERT script would write: one per statement plus one per ``), (``.

    Lexical on purpose — it decides whether the COPY conversion is worth it,
    nothing more.
    """
    return len(_INSERT.findall(sql)) + len(_ROW_SEPARATOR.findall(sql))
