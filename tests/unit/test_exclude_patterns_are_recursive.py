"""``include`` and ``exclude`` mean the same thing, and ``**`` spans directories.

Until 1.5.0 the two lists went through different machinery: ``include`` through
``rglob``/``glob``, ``exclude`` through ``PurePath.match``. So one silently
ignored the ``recursive`` flag and the other silently ignored the directory
structure, and the reference manual's own exclusion examples excluded a
different set of files from the one they name.
"""

from __future__ import annotations

from pathlib import Path

from confiture.core.builder import SchemaBuilder


def _project(tmp_path: Path, *, include: list[str], exclude: list[str], files: list[str]) -> Path:
    schema_dir = tmp_path / "db" / "schema"
    for relative in files:
        path = schema_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("SELECT 1;\n")

    env_dir = tmp_path / "db" / "environments"
    env_dir.mkdir(parents=True)

    def _block(key: str, patterns: list[str]) -> str:
        if not patterns:
            return ""
        return f"    {key}:\n" + "".join(f'      - "{pattern}"\n' for pattern in patterns)

    (env_dir / "test.yaml").write_text(
        "database_url: postgresql://localhost/test\n"
        "include_dirs:\n"
        f"  - path: {schema_dir}\n" + _block("include", include) + _block("exclude", exclude)
    )
    return tmp_path


def _selected(project: Path) -> list[str]:
    schema_dir = project / "db" / "schema"
    builder = SchemaBuilder(env="test", project_dir=project)
    return sorted(str(p.relative_to(schema_dir)) for p in builder.find_sql_files())


def test_the_manuals_exclusion_examples_exclude_what_they_say(tmp_path: Path) -> None:
    """The three patterns from the reference manual, over the issue's own tree.

    A ``.bak`` at the root, a ``temp/`` at the root and a file two levels under
    ``vendor/`` were all in the build; each is what a reader of
    ``**/*.bak``, ``**/temp/**`` and ``vendor/**`` believes is out of it.
    """
    project = _project(
        tmp_path,
        include=["**/*.sql", "**/*.bak"],
        exclude=["**/*.bak", "**/temp/**", "vendor/**"],
        files=[
            "keep.sql",
            "x.bak",
            "a/y.bak",
            "temp/t1.sql",
            "a/temp/t2.sql",
            "vendor/v1.sql",
            "vendor/sub/v2.sql",
        ],
    )

    assert _selected(project) == ["keep.sql"]


def test_include_patterns_are_anchored(tmp_path: Path) -> None:
    """A pattern with a ``/`` names a place, not a suffix of a path."""
    project = _project(
        tmp_path,
        include=["10_tables/*.sql"],
        exclude=[],
        files=["10_tables/x.sql", "a/10_tables/y.sql"],
    )

    assert _selected(project) == ["10_tables/x.sql"]


def test_a_slash_free_pattern_still_matches_at_any_depth(tmp_path: Path) -> None:
    """The rule that keeps this from being a mass regression, at the build's level."""
    project = _project(
        tmp_path,
        include=["*.sql"],
        exclude=["*.bak"],
        files=["x.sql", "a/b/y.sql", "a/z.bak"],
    )

    assert _selected(project) == ["a/b/y.sql", "x.sql"]
