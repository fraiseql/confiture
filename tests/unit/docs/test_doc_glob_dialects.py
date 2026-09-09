"""The manual's exclusion examples are executable, and it names both glob dialects.

Two of the three patterns in ``configuration.md``'s ``include_dirs`` block are
the ones issue #256 measured; a prose description of what they exclude is worth
nothing unless something runs them.
"""

from __future__ import annotations

import re
from pathlib import Path

from confiture.core.builder import SchemaBuilder

REPO = Path(__file__).resolve().parents[3]
CONFIG_DOC = REPO / "docs" / "reference" / "configuration.md"

# The exclusion examples the reference manual prints, and what its prose says
# each removes from the build.
DOC_EXAMPLES = {
    "**/*.bak": ["x.bak", "a/y.bak"],
    "**/temp/**": ["temp/t.sql", "a/temp/t.sql"],
    "**/development/**": ["development/d.sql", "seeds/development/d.sql"],
}


def _doc_text() -> str:
    return CONFIG_DOC.read_text(encoding="utf-8")


def test_the_documented_exclusions_are_the_ones_that_are_executed() -> None:
    """Each pattern below really appears in the manual, so the test cannot drift from it."""
    text = _doc_text()
    for pattern in DOC_EXAMPLES:
        assert f'"{pattern}"' in text, f"{pattern} is no longer an example in configuration.md"


def test_the_documented_exclusions_exclude_what_the_manual_says(tmp_path: Path) -> None:
    schema_dir = tmp_path / "db" / "schema"
    excluded = sorted({name for names in DOC_EXAMPLES.values() for name in names})
    for relative in [*excluded, "keep.sql"]:
        path = schema_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("SELECT 1;\n")

    env_dir = tmp_path / "db" / "environments"
    env_dir.mkdir(parents=True)
    (env_dir / "test.yaml").write_text(
        "database_url: postgresql://localhost/test\n"
        "include_dirs:\n"
        f"  - path: {schema_dir}\n"
        '    include:\n      - "**/*.sql"\n      - "**/*.bak"\n'
        "    exclude:\n" + "".join(f'      - "{p}"\n' for p in DOC_EXAMPLES)
    )

    builder = SchemaBuilder(env="test", project_dir=tmp_path)
    selected = sorted(str(p.relative_to(schema_dir)) for p in builder.find_sql_files())

    assert selected == ["keep.sql"]


def test_the_manual_says_which_dialect_applies_to_which_block() -> None:
    """One config file carries gitignore path globs and fnmatch filename globs."""
    text = _doc_text()
    assert re.search(r"gitignore", text, re.IGNORECASE), "the include_dirs dialect is not named"
    assert "fnmatch" in text, "the seed-profile dialect is not named"
    assert "seed.profiles" in text, "nothing tells a reader which block reads which dialect"
