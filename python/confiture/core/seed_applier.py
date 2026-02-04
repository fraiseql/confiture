"""Orchestrator for sequential seed file execution.

Phase 9: Sequential Seed File Execution

Provides high-level orchestration for applying seed files either
sequentially (each in own savepoint) or concatenated (default behavior).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ApplyResult:
    """Result of seed application.

    Tracks successful and failed files during sequential execution.
    """

    total: int = 0
    succeeded: int = 0
    failed: int = 0
    failed_files: list[str] = field(default_factory=list)


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
    ) -> None:
        """Initialize SeedApplier.

        Args:
            seeds_dir: Path to seeds directory
            env: Environment name (optional, for context)
        """
        self.seeds_dir = Path(seeds_dir)
        self.env = env or "local"

    def find_seed_files(self) -> list[Path]:
        """Discover and return sorted seed files.

        Returns SQL files in sorted order from seeds directory.
        Non-SQL files are ignored.

        Returns:
            List of Path objects for SQL files in sorted order
        """
        if not self.seeds_dir.exists():
            return []

        # Find all .sql files
        sql_files = sorted(self.seeds_dir.glob("*.sql"))
        return sql_files
