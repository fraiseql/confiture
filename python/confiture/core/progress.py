"""Progress tracking for long-running operations.

Provides a unified interface for displaying progress bars using Rich.
Automatically detects CI/CD environments and disables progress display.
"""

import os
import sys

from rich.progress import (
    BarColumn,
    Progress,
    Task,
    TextColumn,
    TimeRemainingColumn,
)


def _is_ci_environment() -> bool:
    """Detect if running in CI/CD environment.

    Returns:
        True if running in CI/CD (no TTY), False otherwise
    """
    # Check for CI environment variables
    ci_vars = {
        "CI",
        "GITHUB_ACTIONS",
        "GITLAB_CI",
        "CIRCLECI",
        "BUILD_ID",
        "BUILD_NUMBER",
        "RUN_ID",
        "TRAVIS",
        "JENKINS_URL",
    }
    if any(var in os.environ for var in ci_vars):
        return True

    # Check if stdout is a TTY (interactive terminal)
    return not sys.stdout.isatty()


class ProgressManager:
    """Unified progress bar management for long operations.

    Automatically detects CI/CD environments and disables progress display.
    Provides a simple interface for tracking multi-step operations.

    Example:
        >>> progress = ProgressManager()
        >>> task = progress.start_task("Processing files...", total=100)
        >>> for item in items:
        ...     process(item)
        ...     progress.update(task, 1)
        >>> progress.stop()
    """

    def __init__(self, show_progress: bool | None = None, live: bool = True):
        """Initialize ProgressManager.

        Args:
            show_progress: Explicitly enable/disable progress (None = auto-detect)
            live: Use live progress display (vs static columns)
        """
        # Auto-detect if show_progress not specified
        if show_progress is None:
            show_progress = not _is_ci_environment()

        self.enabled = show_progress
        self.live = live
        self.progress: Progress | None = None
        self.tasks: dict[str, int] = {}  # task_name -> task_id

        # Create progress display if enabled
        if self.enabled:
            self.progress = Progress(
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TimeRemainingColumn(),
                transient=True,  # Clear completed tasks
            )

    def start(self) -> "ProgressManager":
        """Start the progress display.

        Returns:
            Self for context manager usage
        """
        if self.progress:
            self.progress.start()
        return self

    def stop(self) -> None:
        """Stop the progress display."""
        if self.progress:
            self.progress.stop()

    def __enter__(self) -> "ProgressManager":
        """Context manager entry."""
        return self.start()

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.stop()

    def add_task(
        self,
        description: str,
        total: float | None = None,
        start: bool = True,
    ) -> Task | None:
        """Add a new progress task.

        Args:
            description: Task description shown to user
            total: Total items to process (None for indeterminate)
            start: Whether to start immediately

        Returns:
            Task ID if progress enabled, None otherwise

        Example:
            >>> task = progress.add_task("Processing...", total=100)
            >>> progress.update(task, 1)
        """
        if not self.progress:
            return None

        return self.progress.add_task(description, total=total, start=start)

    def update(
        self,
        task: Task | None,
        advance: float = 1,
        description: str | None = None,
        total: float | None = None,
        refresh: bool = False,
    ) -> None:
        """Update a task's progress.

        Args:
            task: Task to update (from add_task)
            advance: Number of items completed
            description: New description if provided
            total: New total if provided
            refresh: Force immediate refresh

        Example:
            >>> progress.update(task, 1)
        """
        if not self.progress or task is None:
            return

        if description is not None:
            self.progress.update(task, description=description)
        if total is not None:
            self.progress.update(task, total=total)
        if advance > 0:
            self.progress.update(task, advance=advance, refresh=refresh)

    def update_description(self, task: Task | None, description: str) -> None:
        """Update a task's description.

        Args:
            task: Task to update
            description: New description text
        """
        if not self.progress or task is None:
            return
        self.progress.update(task, description=description)

    def finish_task(self, task: Task | None, description: str | None = None) -> None:
        """Mark a task as completed.

        Args:
            task: Task to mark complete
            description: Optional final description
        """
        if not self.progress or task is None:
            return

        if description:
            self.progress.update(task, description=description)
        # Progress is auto-updated when reaches total


# Convenience function for simple operations
def progress_bar(
    description: str,
    total: int,
    show_progress: bool | None = None,
) -> ProgressManager:
    """Create a simple progress bar for iteration.

    Args:
        description: Description of the operation
        total: Total items to process
        show_progress: Explicitly enable/disable (None = auto-detect)

    Returns:
        ProgressManager configured for simple use

    Example:
        >>> with progress_bar("Processing items", total=100) as progress:
        ...     for i in range(100):
        ...         process(i)
        ...         progress.update(task, 1)
    """
    manager = ProgressManager(show_progress=show_progress)
    manager.progress_task = manager.add_task(description, total=total)
    return manager
