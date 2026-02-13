"""CLI interface for consistency validation.

This module provides a command-line interface for running consistency validation
on seed data, with support for multiple output formats and configuration options.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .consistency_validator import ConsistencyValidator


@dataclass
class ConsistencyCLIConfig:
    """Configuration for consistency validation CLI.

    Attributes:
        output_format: Output format ("text" or "json")
        stop_on_first: Stop validation at first violation
        verbose: Include detailed diagnostic information
    """

    output_format: str = "text"
    stop_on_first: bool = False
    verbose: bool = False


@dataclass
class ConsistencyCLIResult:
    """Result of consistency validation via CLI.

    Attributes:
        success: True if validation passed (no violations)
        message: Human-readable result message
        violation_count: Total number of violations found
        exit_code: Exit code for CLI (0 = success, 1 = failure)
        violations: List of violations found
        validators_run: List of validators that ran
    """

    success: bool
    message: str
    violation_count: int
    exit_code: int
    violations: list[Any] = None
    validators_run: list[str] = None

    def __post_init__(self) -> None:
        """Initialize default values."""
        if self.violations is None:
            self.violations = []
        if self.validators_run is None:
            self.validators_run = []

    def format_output(self) -> str:
        """Format the result for CLI output.

        Returns:
            Formatted output string (text or JSON)
        """
        if hasattr(self, "_config") and self._config.output_format == "json":
            return self._format_json()
        else:
            return self._format_text()

    def _format_text(self) -> str:
        """Format output as human-readable text.

        Returns:
            Text-formatted output
        """
        lines = []

        if self.success:
            lines.append("✓ Seed data validation passed")
            lines.append(f"  Validators run: {', '.join(self.validators_run)}")
        else:
            lines.append("✗ Seed data validation failed")
            lines.append(f"  Violations found: {self.violation_count}")

            if self.violations:
                lines.append("\n  Violations:")
                for violation in self.violations:
                    table = getattr(violation, "table", "unknown")
                    message = getattr(violation, "message", str(violation))
                    lines.append(f"    - {table}: {message}")

        if self.message:
            lines.append(f"\n  {self.message}")

        return "\n".join(lines)

    def _format_json(self) -> str:
        """Format output as JSON.

        Returns:
            JSON-formatted output
        """
        output_dict = {
            "success": self.success,
            "message": self.message,
            "violation_count": self.violation_count,
            "validators_run": self.validators_run,
            "violations": [
                {
                    "table": getattr(v, "table", None),
                    "type": getattr(v, "violation_type", type(v).__name__),
                    "message": getattr(v, "message", str(v)),
                }
                for v in self.violations
            ],
        }
        return json.dumps(output_dict, indent=2)


class ConsistencyCLI:
    """CLI interface for consistency validation.

    Provides command-line access to seed data consistency validation with
    support for multiple output formats and configuration options.

    Example:
        >>> config = ConsistencyCLIConfig(output_format="text", verbose=True)
        >>> cli = ConsistencyCLI(config=config)
        >>> seed_data = {"users": [{"id": "1"}]}
        >>> schema = {"users": {"required": True}}
        >>> result = cli.validate(seed_data, schema)
        >>> print(result.format_output())
    """

    def __init__(self, config: ConsistencyCLIConfig | None = None) -> None:
        """Initialize the CLI interface.

        Args:
            config: Optional configuration object
        """
        self.config = config or ConsistencyCLIConfig()
        self.validator = ConsistencyValidator(stop_on_first_violation=self.config.stop_on_first)

    def validate(
        self,
        seed_data: dict[str, list[dict[str, Any]]],
        schema_context: dict[str, Any],
    ) -> ConsistencyCLIResult:
        """Validate seed data and return CLI result.

        Args:
            seed_data: Seed data dictionary
            schema_context: Schema context dictionary

        Returns:
            ConsistencyCLIResult with validation results
        """
        # Run validation
        report = self.validator.validate(seed_data, schema_context)

        # Create result
        result = ConsistencyCLIResult(
            success=not report.has_violations,
            message=self._build_message(report),
            violation_count=report.violation_count,
            exit_code=0 if not report.has_violations else 1,
            violations=report.violations,
            validators_run=report.validators_run,
        )

        # Store config for formatting
        result._config = self.config

        return result

    def load_seed_file(self, file_path: Path) -> dict[str, list[dict[str, Any]]]:  # noqa: ARG002
        """Load seed data from SQL file.

        Args:
            file_path: Path to SQL seed file

        Returns:
            Parsed seed data dictionary
        """
        # TODO: Parse SQL file and extract data
        # For now, return empty dict
        return {}

    def load_schema_file(self, file_path: Path) -> dict[str, Any]:  # noqa: ARG002
        """Load schema context from YAML file.

        Args:
            file_path: Path to schema YAML file

        Returns:
            Parsed schema context dictionary
        """
        # TODO: Parse YAML file and extract schema
        # For now, return empty dict
        return {}

    def _build_message(self, report: Any) -> str:
        """Build a summary message from validation report.

        Args:
            report: ConsistencyReport from validator

        Returns:
            Summary message string
        """
        if not report.has_violations:
            return "All consistency checks passed."

        violation_types = {}
        for violation in report.violations:
            vtype = getattr(violation, "violation_type", "unknown")
            violation_types[vtype] = violation_types.get(vtype, 0) + 1

        type_summary = ", ".join(
            f"{count} {vtype}" for vtype, count in sorted(violation_types.items())
        )
        return f"Found {report.violation_count} violations: {type_summary}"
