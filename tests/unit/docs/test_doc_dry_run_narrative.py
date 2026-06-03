"""Executable guard: the preflight "structural diff" fiction can't return.

DOCS-H1 anti-drift guard. `migrate preflight --against` does SAVEPOINT-replay
of pending migrations — it does NOT diff the result against `db/schema/`. The
docs must not describe a structural-diff feature preflight doesn't have. (A real
structural diff is `migrate diff <old.sql> <new.sql>`, which stays allowed.)

Also asserts the dry-run guide's Python sample imports resolve.
"""

from __future__ import annotations

from doc_snippets import REPO_ROOT, assert_doc_imports_resolve

DOCS_DIR = REPO_ROOT / "docs"

# Phrases that only ever describe the (nonexistent) preflight schema-diff.
PREFLIGHT_DIFF_FICTION = [
    "structurally diff",
    "diffs the resulting schema",
    "vs. db/schema/",
    "differs from db/schema",
    "structural diff against",
    "Drift items:",
]


def test_no_preflight_structural_diff_fiction_in_docs() -> None:
    violations: list[str] = []
    for path in sorted(DOCS_DIR.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        for phrase in PREFLIGHT_DIFF_FICTION:
            if phrase in text:
                line = text[: text.index(phrase)].count("\n") + 1
                violations.append(f"{path.relative_to(REPO_ROOT)}:{line}: {phrase!r}")
    assert not violations, "preflight structural-diff fiction present:\n" + "\n".join(violations)


def test_dry_run_guide_imports_resolve() -> None:
    assert assert_doc_imports_resolve("docs/guides/dry-run.md") > 0
