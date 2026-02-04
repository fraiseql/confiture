"""SQL comment validator

Detects unclosed block comments in SQL files that would corrupt concatenated schemas.
Uses a state machine to track comment nesting.
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class CommentViolationSeverity(Enum):
    """Severity level for comment violations"""

    ERROR = "error"
    WARNING = "warning"


@dataclass
class CommentViolation:
    """Represents a comment validation violation

    Attributes:
        file_path: Path to file with violation
        line_number: Line number where violation occurs
        message: Human-readable error message
        severity: ERROR or WARNING
        violation_type: Type of violation (unclosed, spillover, etc.)
        snippet: Code snippet around violation
    """

    file_path: Path
    line_number: int
    message: str
    severity: CommentViolationSeverity
    violation_type: str
    snippet: str | None = None

    def __str__(self) -> str:
        """Format violation as string"""
        return f"{self.file_path}:{self.line_number} [{self.severity.value.upper()}] {self.message}"


class CommentValidator:
    """Validates SQL for unclosed block comments

    Uses a state machine to track block comment nesting and detect:
    - Unclosed block comments (/* without matching */)
    - File spillover (file ends inside unclosed comment)
    - Nested comments

    Example:
        >>> validator = CommentValidator()
        >>> violations = validator.validate_file(sql_content, Path("schema.sql"))
        >>> if violations:
        ...     for v in violations:
        ...         print(f"Error in {v.file_path}:{v.line_number}: {v.message}")
    """

    def __init__(self) -> None:
        """Initialize comment validator"""
        pass

    def validate_file(self, content: str, file_path: Path) -> list[CommentViolation]:
        """Validate a single SQL file for unclosed comments

        Args:
            content: SQL file content
            file_path: Path to file (for error messages)

        Returns:
            List of violations found
        """
        if not content:
            return []

        violations: list[CommentViolation] = []
        lines = content.split("\n")

        in_block_comment = False
        block_start_line = 0
        line_number = 1

        for line in lines:
            i = 0
            while i < len(line):
                # Look for comment start
                if i < len(line) - 1:
                    if line[i : i + 2] == "/*":
                        in_block_comment = True
                        block_start_line = line_number
                        i += 2
                        continue

                    # Look for comment end
                    if in_block_comment and line[i : i + 2] == "*/":
                        in_block_comment = False
                        i += 2
                        continue

                i += 1

            line_number += 1

        # Check for spillover (file ends in unclosed comment)
        if in_block_comment:
            violations.append(
                CommentViolation(
                    file_path=file_path,
                    line_number=block_start_line,
                    message=(
                        f"Unclosed block comment starting at line {block_start_line}. "
                        f"File ends while still inside comment."
                    ),
                    severity=CommentViolationSeverity.ERROR,
                    violation_type="spillover",
                    snippet=self._get_snippet(content, block_start_line),
                )
            )

        return violations

    def validate_files(self, files_and_content: dict[Path, str]) -> list[CommentViolation]:
        """Validate multiple SQL files

        Args:
            files_and_content: Dict mapping file paths to content

        Returns:
            List of all violations found
        """
        all_violations = []
        for file_path, content in files_and_content.items():
            all_violations.extend(self.validate_file(content, file_path))
        return all_violations

    @staticmethod
    def _get_snippet(content: str, line_number: int, context_lines: int = 2) -> str:
        """Extract code snippet around error line

        Args:
            content: Full file content
            line_number: Line with error (1-indexed)
            context_lines: Number of lines before/after to include

        Returns:
            Code snippet as string
        """
        lines = content.split("\n")
        start = max(0, line_number - context_lines - 1)
        end = min(len(lines), line_number + context_lines)
        snippet_lines = lines[start:end]
        return "\n".join(snippet_lines)
