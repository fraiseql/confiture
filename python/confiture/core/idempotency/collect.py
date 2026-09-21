"""The idempotency report for a set of migration files: SQL read directly, Python through the static evaluator."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from confiture.core.idempotency.models import IdempotencyReport
from confiture.core.idempotency.python_migration_extractor import (
    ExtractionWarning,
    extract_sql_from_python_migration,
    extract_sql_from_python_source,
)
from confiture.core.sql_path import find_project_root


def _repo_root_for(path: Path) -> Path:
    """Resolve the project root that owns ``path``, for extractor boundaries.

    Delegates to the extractor's own anchor search so a staged ``.py``
    migration analyzed from a temp file gets the same ``execute_file``
    boundary it would have had on disk.
    """

    return find_project_root(path)


def collect_report(
    sql_files: list[Path],
    py_files: list[Path],
    validator: Any,
    project_root: Path | None = None,
    staged_content: dict[Path, str] | None = None,
) -> Any:
    """Run the idempotency validator against .sql files and Python migrations.

    Returns a merged :class:`IdempotencyReport`. Python-origin violations
    carry the ``source_line`` of the originating ``self.execute()`` call;
    extractor warnings ride on the report's ``warnings`` list.

    ``project_root`` is forwarded to the extractor for ``execute_file``
    path-boundary checking; passing ``None`` lets the extractor auto-detect
    the root (the nearest ancestor with ``pyproject.toml``, ``.git``, or
    ``db/``).

    ``staged_content`` maps a path to its **staging-index** blob. When a path
    is present there, that content is analyzed instead of the working tree —
    the two differ when a file is staged and then edited further, and a
    pre-commit gate must judge what is about to be committed (#181). The
    blob is analyzed *as the file at that path*: ``Path(__file__)`` and
    migration-relative reads resolve where the migration lives, not in a
    temp directory (0.46.0).
    """

    combined = IdempotencyReport()
    staged_content = staged_content or {}

    for sql_path in sorted(sql_files):
        if sql_path in staged_content:
            file_report = validator.validate_sql(staged_content[sql_path], file_path=str(sql_path))
        elif sql_path.is_file():
            file_report = validator.validate_file(sql_path)
        else:
            continue
        for scanned in file_report.scanned_files:
            combined.add_file_scanned(scanned)
        for violation in file_report.violations:
            combined.add_violation(violation)
        combined.warnings.extend(file_report.warnings)

    for py_path in sorted(py_files):
        if py_path in staged_content:
            extraction = extract_sql_from_python_source(
                staged_content[py_path],
                path=py_path,
                project_root=project_root or _repo_root_for(py_path),
            )
        else:
            extraction = extract_sql_from_python_migration(py_path, project_root=project_root)
        combined.add_file_scanned(str(py_path))
        combined.warnings.extend(extraction.warnings)
        for snippet in extraction.snippets:
            snippet_report = validator.validate_sql(snippet.sql, file_path=str(py_path))
            for violation in snippet_report.violations:
                violation.source_line = snippet.source_line
                combined.add_violation(violation)
            for warning in snippet_report.warnings:
                combined.warnings.append(
                    ExtractionWarning(
                        kind=warning.kind,
                        source_file=py_path,
                        source_line=snippet.source_line,
                        message=warning.message,
                        reason_code=warning.reason_code,
                        remedy=warning.remedy,
                    )
                )

    combined.scanned_files.sort()
    return combined
