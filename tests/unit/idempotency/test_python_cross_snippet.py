"""Cross-snippet pair recognition for ``.py`` migrations (Phase 6).

Before 0.14.0 the validator called :func:`detect_non_idempotent_patterns`
once per extracted snippet, so a ``DROP X IF EXISTS`` in one
``self.execute()`` and a matching ``CREATE X`` in the next looked like
an unpaired CREATE violation. From 0.14.0 the validator concatenates
all snippets per file and runs detection once, recognizing pairs across
``self.execute()`` boundaries.

This file also covers the line back-mapping helper directly so any
future refactor that touches the offset math has a focused test.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from confiture.core.idempotency.python_migration_extractor import (
    ExtractedSQL,
    ExtractionKind,
)
from confiture.core.idempotency.validator import (
    IdempotencyValidator,
    _combine_python_snippets,
    _map_combined_line_to_source,
)


def _migration_with(body: str) -> str:
    """Build a Confiture migration with ``body`` placed inside ``def up``.

    ``body`` must use 8-space indentation (so each line is at the right
    depth inside the method). The helper assembles the file
    line-by-line to avoid f-string interpolation collapsing the indent.
    """
    header = dedent(
        """\
        from confiture.models.migration import Migration


        class Demo(Migration):
            version = "20260101000000"
            name = "demo"

            def up(self) -> None:
        """
    )
    footer = dedent(
        """\

            def down(self) -> None:
                pass
        """
    )
    return header + body.rstrip("\n") + "\n" + footer


class TestCombineSnippetsHelper:
    """``_combine_python_snippets`` builds a parseable string + line index."""

    def test_single_snippet_terminates_with_semicolon(self):
        snip = ExtractedSQL(
            sql="CREATE TABLE foo (id int)",
            source_file=Path("/tmp/x.py"),
            source_line=10,
            kind=ExtractionKind.INLINE,
        )
        combined, origins = _combine_python_snippets([snip])
        assert combined.endswith(";")
        assert len(origins) == 1
        assert origins[0].source_line == 10

    def test_multiple_snippets_separated_by_newlines(self):
        snippets = [
            ExtractedSQL(
                sql="DROP VIEW IF EXISTS v_users;",
                source_file=Path("/tmp/x.py"),
                source_line=5,
                kind=ExtractionKind.INLINE,
            ),
            ExtractedSQL(
                sql="CREATE VIEW v_users AS SELECT 1;",
                source_file=Path("/tmp/x.py"),
                source_line=6,
                kind=ExtractionKind.INLINE,
            ),
        ]
        combined, origins = _combine_python_snippets(snippets)
        assert "DROP VIEW" in combined
        assert "CREATE VIEW" in combined
        # Each snippet is a single SQL line. ``"\n".join`` doesn't add
        # a blank line, so snippet 2 starts on combined line 2.
        assert origins[0].combined_start_line == 1
        assert origins[1].combined_start_line == 2


class TestMapCombinedLineToSource:
    """``_map_combined_line_to_source`` finds the snippet owning a line."""

    def test_returns_origin_for_line_in_range(self):
        snippets = [
            ExtractedSQL(
                sql="DROP VIEW IF EXISTS v;",
                source_file=Path("/x.py"),
                source_line=4,
                kind=ExtractionKind.INLINE,
            ),
            ExtractedSQL(
                sql="CREATE VIEW v AS\nSELECT 1;",
                source_file=Path("/x.py"),
                source_line=6,
                kind=ExtractionKind.INLINE,
            ),
        ]
        _, origins = _combine_python_snippets(snippets)
        # Snippet 1 occupies combined line 1; snippet 2 (2 lines) occupies 2-3.
        assert _map_combined_line_to_source(1, origins).source_line == 4
        assert _map_combined_line_to_source(2, origins).source_line == 6
        assert _map_combined_line_to_source(3, origins).source_line == 6

    def test_returns_none_for_line_outside_any_snippet(self):
        snippets = [
            ExtractedSQL(
                sql="DROP VIEW IF EXISTS v;",
                source_file=Path("/x.py"),
                source_line=4,
                kind=ExtractionKind.INLINE,
            )
        ]
        _, origins = _combine_python_snippets(snippets)
        assert _map_combined_line_to_source(99, origins) is None


class TestCrossSnippetPairRecognition:
    """End-to-end: DROP in one execute, CREATE in the next → no violation."""

    def test_drop_view_create_view_across_snippets_is_idempotent(self, tmp_path):
        body = (
            '        self.execute("DROP VIEW IF EXISTS v_users;")\n'
            '        self.execute("CREATE VIEW v_users AS SELECT 1;")'
        )
        (tmp_path / "20260101000000_demo.py").write_text(_migration_with(body), encoding="utf-8")
        validator = IdempotencyValidator()
        report = validator.validate_directory(tmp_path)
        view_violations = [
            v
            for v in report.violations
            if v.pattern.value in {"CREATE_VIEW", "CREATE_OR_REPLACE_VIEW_SHAPE_RISK"}
        ]
        assert view_violations == []

    def test_drop_then_unrelated_create_still_flagged(self, tmp_path):
        body = (
            '        self.execute("DROP VIEW IF EXISTS v_alpha;")\n'
            '        self.execute("CREATE VIEW v_beta AS SELECT 1;")'
        )
        (tmp_path / "20260101000000_demo.py").write_text(_migration_with(body), encoding="utf-8")
        validator = IdempotencyValidator()
        report = validator.validate_directory(tmp_path)
        view_violations = [v for v in report.violations if v.pattern.value == "CREATE_VIEW"]
        assert len(view_violations) == 1
        assert "v_beta" in view_violations[0].sql_snippet

    def test_drop_constraint_then_add_constraint_across_snippets(self, tmp_path):
        body = (
            '        self.execute("ALTER TABLE foo DROP CONSTRAINT IF EXISTS chk_x;")\n'
            '        self.execute("ALTER TABLE foo ADD CONSTRAINT chk_x CHECK (id > 0);")'
        )
        (tmp_path / "20260101000000_demo.py").write_text(_migration_with(body), encoding="utf-8")
        validator = IdempotencyValidator()
        report = validator.validate_directory(tmp_path)
        assert report.violations == []

    def test_violation_source_line_points_at_execute_call(self, tmp_path):
        body = (
            '        self.execute("SELECT 1;")\n'
            '        self.execute("CREATE TABLE foo (id int);")\n'
            '        self.execute("SELECT 2;")'
        )
        (tmp_path / "20260101000000_demo.py").write_text(_migration_with(body), encoding="utf-8")
        validator = IdempotencyValidator()
        report = validator.validate_directory(tmp_path)
        assert len(report.violations) == 1
        violation = report.violations[0]
        # The CREATE TABLE call is the second of three self.execute() calls;
        # the def up() body starts at line 9 in the dedented template,
        # so the calls land at lines 9, 10, 11.
        assert violation.source_line == 10
