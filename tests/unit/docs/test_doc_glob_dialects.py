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


def _materialise(project: Path, block: str, env: str, files: list[str]) -> Path:
    """A project laid out as a doc block describes, with *files* under its tree."""
    for relative in files:
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("SELECT 1;\n")
    env_dir = project / "db" / "environments"
    env_dir.mkdir(parents=True, exist_ok=True)
    (env_dir / f"{env}.yaml").write_text(f"database_url: postgresql://localhost/test\n{block}")
    return project


def _doc_block(name: str) -> str:
    from doc_snippets import fenced_after_anchor

    return fenced_after_anchor(_doc_text(), name)


PRODUCTION_TREE = [
    "db/schema/10_tables/10_users.sql",
    "db/seeds/common/10_lookup.sql",
    "db/seeds/common/development/90_dev_only.sql",
    "db/seeds/development/99_fixtures.sql",
]


def test_the_production_example_does_not_ship_development_seeds(tmp_path: Path) -> None:
    """The manual's own production config, executed.

    ``**/development/**`` needed three path components under ``PurePath.match``,
    and ``db/seeds/common/development/`` is two below the entry that excludes
    it — so a production build shipped the development seeds the block exists
    to keep out.
    """
    project = _materialise(
        tmp_path, _doc_block("include-dirs-production"), "production", PRODUCTION_TREE
    )

    selected = [
        str(p.relative_to(project))
        for p in SchemaBuilder(env="production", project_dir=project).find_sql_files()
    ]

    assert selected == [
        "db/schema/10_tables/10_users.sql",
        "db/seeds/common/10_lookup.sql",
    ]


def test_the_local_example_builds_the_schema_then_both_seed_blocks(tmp_path: Path) -> None:
    """The `order` values in the same example decide the sequence, as its prose says."""
    project = _materialise(tmp_path, _doc_block("include-dirs-local"), "local", PRODUCTION_TREE)

    selected = [
        str(p.relative_to(project))
        for p in SchemaBuilder(env="local", project_dir=project).find_sql_files()
    ]

    assert selected == [
        "db/schema/10_tables/10_users.sql",
        "db/seeds/common/10_lookup.sql",
        "db/seeds/common/development/90_dev_only.sql",
        "db/seeds/development/99_fixtures.sql",
    ]
