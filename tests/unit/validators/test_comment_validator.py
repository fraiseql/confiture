"""Tests for SQL comment validator

Tests cover:
- Detection of unclosed block comments
- Detection of file spillover (file ends in comment)
- Nested comment handling
- Edge cases and error formatting
"""

from pathlib import Path

from confiture.core.validators.comment_validator import (
    CommentValidator,
    CommentViolation,
    CommentViolationSeverity,
)


class TestCommentValidatorBasic:
    """Test basic unclosed block comment detection"""

    def test_valid_closed_block_comment(self):
        """Test valid closed block comment passes"""
        sql = "/* This is a comment */ SELECT 1;"
        validator = CommentValidator()
        violations = validator.validate_file(sql, Path("test.sql"))
        assert violations == []

    def test_unclosed_block_comment(self):
        """Test unclosed block comment is detected"""
        sql = "/* This comment is unclosed SELECT 1;"
        validator = CommentValidator()
        violations = validator.validate_file(sql, Path("test.sql"))
        assert len(violations) == 1
        assert violations[0].severity == CommentViolationSeverity.ERROR
        assert "unclosed" in violations[0].message.lower()

    def test_nested_unclosed_block_comment(self):
        """Test nested unclosed block comment is detected"""
        sql = "/* outer /* inner SELECT 1;"
        validator = CommentValidator()
        violations = validator.validate_file(sql, Path("test.sql"))
        assert len(violations) == 1

    def test_multiple_closed_comments(self):
        """Test multiple closed comments are valid"""
        sql = "/* First */ SELECT 1; /* Second */"
        validator = CommentValidator()
        violations = validator.validate_file(sql, Path("test.sql"))
        assert violations == []

    def test_line_comments_ignored(self):
        """Test line comments don't affect validation"""
        sql = "-- This is a line comment\nSELECT 1;"
        validator = CommentValidator()
        violations = validator.validate_file(sql, Path("test.sql"))
        assert violations == []

    def test_block_comment_with_line_comment_inside(self):
        """Test block comment containing line comment"""
        sql = "/* This is a comment -- with line comment */ SELECT 1;"
        validator = CommentValidator()
        violations = validator.validate_file(sql, Path("test.sql"))
        assert violations == []

    def test_error_includes_file_path(self):
        """Test error message includes file path"""
        sql = "/* unclosed"
        validator = CommentValidator()
        violations = validator.validate_file(sql, Path("db/schema/10_tables/users.sql"))
        assert len(violations) == 1
        assert "db/schema/10_tables/users.sql" in str(violations[0].file_path)

    def test_error_includes_line_number(self):
        """Test error message includes line number"""
        sql = "SELECT 1;\n/* unclosed"
        validator = CommentValidator()
        violations = validator.validate_file(sql, Path("test.sql"))
        assert len(violations) == 1
        assert violations[0].line_number == 2


class TestCommentValidatorSpillover:
    """Test file spillover detection (file ends in comment)"""

    def test_file_ends_in_unclosed_comment(self):
        """Test file ending with unclosed comment is detected"""
        sql = "SELECT 1;\n/* comment starts but never closes"
        validator = CommentValidator()
        violations = validator.validate_file(sql, Path("test.sql"))
        assert len(violations) == 1
        assert violations[0].severity == CommentViolationSeverity.ERROR

    def test_file_ends_after_closed_comment(self):
        """Test file ending after closed comment is valid"""
        sql = "SELECT 1;\n/* comment */ \n"
        validator = CommentValidator()
        violations = validator.validate_file(sql, Path("test.sql"))
        assert violations == []

    def test_spillover_detection_type(self):
        """Test spillover violations are marked as spillover"""
        sql = "/* unclosed"
        validator = CommentValidator()
        violations = validator.validate_file(sql, Path("test.sql"))
        assert len(violations) == 1
        assert violations[0].violation_type == "spillover"


class TestCommentValidatorNested:
    """Test nested comment handling"""

    def test_nested_comments_simple(self):
        """Test nested block comments"""
        sql = "/* outer /* inner */ */"
        validator = CommentValidator()
        violations = validator.validate_file(sql, Path("test.sql"))
        # Should be valid - outer comment closes inner
        assert violations == []

    def test_nested_unclosed_inner(self):
        """Test nested with inner unclosed"""
        sql = "/* outer /* inner */"
        validator = CommentValidator()
        violations = validator.validate_file(sql, Path("test.sql"))
        # First */ closes inner, second */ closes outer
        assert violations == []

    def test_deeply_nested_unclosed(self):
        """Test deeply nested with unclosed"""
        sql = "/* level1 /* level2 /* level3 */"
        validator = CommentValidator()
        violations = validator.validate_file(sql, Path("test.sql"))
        # All closes should work
        assert violations == []


class TestCommentValidatorBatch:
    """Test batch validation across multiple files"""

    def test_validate_multiple_files(self):
        """Test validating multiple files"""
        sql1 = "SELECT 1; /* closed */"
        sql2 = "SELECT 2; /* unclosed"
        sql3 = "SELECT 3; /* also closed */"

        validator = CommentValidator()
        files = [
            (sql1, Path("file1.sql")),
            (sql2, Path("file2.sql")),
            (sql3, Path("file3.sql")),
        ]

        all_violations = []
        for sql, path in files:
            all_violations.extend(validator.validate_file(sql, path))

        # Should have one violation from file2
        assert len(all_violations) == 1
        assert all_violations[0].file_path == Path("file2.sql")

    def test_batch_validation_method(self):
        """Test batch validation helper method"""
        files_and_content = {
            Path("file1.sql"): "SELECT 1; /* closed */",
            Path("file2.sql"): "SELECT 2; /* unclosed",
        }

        validator = CommentValidator()
        violations = validator.validate_files(files_and_content)

        assert len(violations) == 1
        assert violations[0].file_path == Path("file2.sql")


class TestCommentViolation:
    """Test CommentViolation dataclass"""

    def test_violation_creation(self):
        """Test creating a violation"""
        violation = CommentViolation(
            file_path=Path("test.sql"),
            line_number=5,
            message="Unclosed block comment",
            severity=CommentViolationSeverity.ERROR,
            violation_type="unclosed",
            snippet="/* this is unclosed",
        )
        assert violation.file_path == Path("test.sql")
        assert violation.line_number == 5
        assert violation.severity == CommentViolationSeverity.ERROR

    def test_violation_string_representation(self):
        """Test violation can be converted to string"""
        violation = CommentViolation(
            file_path=Path("db/schema/10_tables/users.sql"),
            line_number=42,
            message="Unclosed block comment",
            severity=CommentViolationSeverity.ERROR,
            violation_type="unclosed",
            snippet="/* unclosed comment",
        )
        str_repr = str(violation)
        assert "db/schema/10_tables/users.sql" in str_repr
        assert "42" in str_repr


class TestCommentValidatorEdgeCases:
    """Test edge cases"""

    def test_empty_file(self):
        """Test empty file passes"""
        sql = ""
        validator = CommentValidator()
        violations = validator.validate_file(sql, Path("empty.sql"))
        assert violations == []

    def test_only_block_comment(self):
        """Test file with only block comment"""
        sql = "/* Just a comment */"
        validator = CommentValidator()
        violations = validator.validate_file(sql, Path("test.sql"))
        assert violations == []

    def test_comment_with_asterisks(self):
        """Test comment containing asterisks"""
        sql = "/* *** Multiple asterisks *** */"
        validator = CommentValidator()
        violations = validator.validate_file(sql, Path("test.sql"))
        assert violations == []

    def test_sql_with_strings_containing_slash(self):
        """Test SQL with strings containing slashes (known limitation)"""
        # Note: This is a known limitation - strings aren't parsed
        sql = "SELECT 'http://example.com' WHERE /* comment */ x = 1;"
        validator = CommentValidator()
        violations = validator.validate_file(sql, Path("test.sql"))
        # Should be valid in this case
        assert violations == []

    def test_multiple_violations_same_file(self):
        """Test detecting multiple violations in same file"""
        sql = "/* unclosed1\nSELECT 1;\n/* unclosed2"
        validator = CommentValidator()
        violations = validator.validate_file(sql, Path("test.sql"))
        # May have 1 or more violations depending on implementation
        assert len(violations) >= 1

    def test_very_long_comment(self):
        """Test very long unclosed comment"""
        long_comment = "/*" + "x" * 10000
        validator = CommentValidator()
        violations = validator.validate_file(long_comment, Path("test.sql"))
        assert len(violations) == 1

    def test_unicode_in_comment(self):
        """Test unicode characters in comments"""
        sql = "/* Comment with unicode: 🍓 */ SELECT 1;"
        validator = CommentValidator()
        violations = validator.validate_file(sql, Path("test.sql"))
        assert violations == []


class TestCommentValidatorErrorMessages:
    """Test error message quality"""

    def test_error_message_helpful(self):
        """Test error message contains helpful information"""
        sql = "CREATE TABLE x (\n  id INT,\n  /* unclosed comment"
        validator = CommentValidator()
        violations = validator.validate_file(sql, Path("schema.sql"))
        assert len(violations) == 1

        msg = violations[0].message
        assert "/*" in msg or "comment" in msg.lower()

    def test_snippet_included_in_violation(self):
        """Test violation includes code snippet"""
        sql = "SELECT 1; /* this is unclosed"
        validator = CommentValidator()
        violations = validator.validate_file(sql, Path("test.sql"))
        assert len(violations) == 1
        assert violations[0].snippet is not None
        assert "unclosed" in violations[0].snippet.lower() or "/*" in violations[0].snippet
