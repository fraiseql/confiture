"""Logging configuration system for Confiture.

Provides LoggingConfig for configuring structured logging with
support for log levels, multiple outputs, and metrics collection.
"""

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class OutputConfig:
    """Configuration for a single output target."""

    type: Literal["stdout", "file", "stderr"]
    path: str | None = None
    format: Literal["json", "text"] = "json"


@dataclass
class MetricsConfig:
    """Configuration for metrics collection."""

    enabled: bool = True
    retention_days: int = 30
    flush_interval_seconds: int = 60


@dataclass
class LoggingConfig:
    """Configuration for structured logging.

    Example:
        >>> config = LoggingConfig(
        ...     level="info",
        ...     outputs=[OutputConfig(type="stdout")],
        ... )
    """

    level: Literal["debug", "info", "warning", "error"] = "info"
    format: Literal["json", "text"] = "json"
    outputs: list[OutputConfig] = field(
        default_factory=lambda: [OutputConfig(type="stdout")]
    )
    metrics: MetricsConfig = field(default_factory=MetricsConfig)
    include_context: bool = True
    include_timestamp: bool = True

    @classmethod
    def default(cls) -> "LoggingConfig":
        """Create config with sensible defaults.

        Returns:
            LoggingConfig with defaults
        """
        return cls(
            level="info",
            format="json",
            outputs=[OutputConfig(type="stdout")],
            metrics=MetricsConfig(enabled=True),
            include_context=True,
            include_timestamp=True,
        )

    @classmethod
    def debug_mode(cls) -> "LoggingConfig":
        """Create config for debug mode.

        Returns:
            LoggingConfig with debug settings
        """
        return cls(
            level="debug",
            format="json",
            outputs=[OutputConfig(type="stdout")],
            metrics=MetricsConfig(enabled=True),
        )
