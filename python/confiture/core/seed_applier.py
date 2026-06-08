"""Orchestrator for sequential seed file execution.

Provides high-level orchestration for applying seed files either
sequentially (each in own savepoint) or concatenated (default behavior).
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import psycopg
from rich.console import Console

from confiture.core.progress import ProgressManager
from confiture.core.seed_executor import SeedExecutor

if TYPE_CHECKING:
    from confiture.config.environment import SeedProfile


def _apply_profile_filter(files: list[Path], profile: SeedProfile) -> list[Path]:
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
    """Apply ordered seed files into the database at *connection_url*.

    Each file runs inside its own savepoint for failure isolation. Used to load
    seeds into ephemeral / template databases (artifact builds, test-db
    provisioning) where no long-lived :class:`SeedApplier` is in play.

    Args:
        connection_url: Connection URL of the target database.
        seed_files: Ordered seed files to apply.

    Returns:
        The number of seed files applied.
    """
    with psycopg.connect(connection_url, autocommit=False) as conn:
        executor = SeedExecutor(connection=conn)
        for i, seed_file in enumerate(seed_files, 1):
            executor.execute_file(seed_file, savepoint_name=f"sp_seed_{i:03d}")
        conn.commit()
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
        return _apply_profile_filter(sql_files, profile)

    def apply_sequential(
        self,
        continue_on_error: bool = False,
        progress: ProgressManager | None = None,
        profile: SeedProfile | None = None,
    ) -> ApplyResult:
        """Apply seed files sequentially with savepoints.

        Each file executed in its own savepoint for isolation.
        Avoids PostgreSQL parser limits from concatenation.

        Args:
            continue_on_error: Continue applying files if one fails
            progress: Optional ProgressManager for displaying progress
            profile: Optional seed profile selecting a subset of files

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
            savepoint_name = f"sp_seed_{i:03d}"

            try:
                self.console.print(f"[cyan]→ {seed_file.name}[/cyan]", end=" ")
                executor.execute_file(seed_file, savepoint_name=savepoint_name)
                result.succeeded += 1
                self.console.print("[green]✓[/green]")

                # Update progress
                if progress and apply_task is not None:
                    progress.update(apply_task, advance=1)

            except Exception as e:
                result.failed += 1
                result.failed_files.append(seed_file.name)
                self.console.print(f"[red]✗ {e}[/red]")

                # Still update progress on failure
                if progress and apply_task is not None:
                    progress.update(apply_task, advance=1)

                if not continue_on_error:
                    raise

        if progress and apply_task is not None:
            progress.finish_task(apply_task)

        # Summary
        self.console.print("\n" + "=" * 50)
        self.console.print(f"Applied {result.succeeded}/{result.total} seed files")
        if result.failed > 0:
            self.console.print(f"[yellow]⚠ {result.failed} files failed[/yellow]")
            for failed_file in result.failed_files:
                self.console.print(f"  - {failed_file}")

        return result
