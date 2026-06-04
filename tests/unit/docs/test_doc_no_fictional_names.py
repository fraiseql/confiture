"""Executable guard: no fictional names in docs or the project CLAUDE.md.

DOCS-M5 / DOCS-M4 anti-drift guard. These names describe a tool that doesn't
exist and must never reappear in user-facing docs:

* ``confiture_migrations`` / ``confiture_version`` — the tracking table is
  ``tb_confiture`` (see docs/reference/tracking-table.md);
* ``apply_all(`` — fictional Migrator method;
* ``uv run mypy`` — the project type-checks with ``ty``;
* ``confiture.core.security`` — the dormant validation/secure-logging module was
  deleted in 0.22.0 (it was never imported by any live path); the docs once
  presented it as an *active* control, which was false assurance. The unrelated
  ``confiture.core.anonymization.security`` (KMS) path is not matched.

Word boundaries keep legitimate identifiers (``tb_confiture_version_key``,
``idx_tb_confiture_version``) from tripping the table-name patterns.
"""

from __future__ import annotations

import re

from doc_snippets import REPO_ROOT

DOCS_DIR = REPO_ROOT / "docs"
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"

FORBIDDEN = {
    "confiture_migrations (the tracking table is tb_confiture)": re.compile(
        r"(?<!\w)confiture_migrations"
    ),
    "confiture_version (fictional table; use tb_confiture)": re.compile(
        r"(?<!\w)confiture_version(?!\w)"
    ),
    "apply_all( (fictional Migrator method)": re.compile(r"apply_all\("),
    "uv run mypy (the project uses ty)": re.compile(r"uv run mypy"),
    "confiture.core.security (dormant module deleted in 0.22.0)": re.compile(
        r"confiture\.core\.security"
    ),
}


def _scanned_files() -> list:
    files = sorted(DOCS_DIR.rglob("*.md"))
    files.append(CLAUDE_MD)
    return files


def test_no_fictional_names_in_docs_or_claude_md() -> None:
    violations: list[str] = []
    for path in _scanned_files():
        text = path.read_text(encoding="utf-8")
        for label, pattern in FORBIDDEN.items():
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                violations.append(f"{path.relative_to(REPO_ROOT)}:{line}: {label}")

    assert not violations, "fictional names found:\n" + "\n".join(violations)
