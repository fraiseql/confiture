"""Tests for multi-statement INSERT conversion (Issue #44).

Covers the case where a seed file contains multiple individual INSERT statements
that should all be converted, not just the first one.
"""

from __future__ import annotations

from confiture.core.seed.insert_to_copy_converter import InsertToCopyConverter


class TestMultiStatementConversion:
    """Issue #44: all INSERT statements must be converted, not just the first."""

    def test_three_individual_inserts_all_converted(self) -> None:
        """Three individual INSERTs should yield rows_converted=3."""
        converter = InsertToCopyConverter()
        sql = (
            "INSERT INTO public.tb_item (id, name) VALUES ('aaa-001', 'First item');\n"
            "INSERT INTO public.tb_item (id, name) VALUES ('aaa-002', 'Second item');\n"
            "INSERT INTO public.tb_item (id, name) VALUES ('aaa-003', 'Third item');\n"
        )

        result = converter.try_convert(sql, file_path="items.sql")

        assert result.success is True
        assert result.rows_converted == 3

    def test_same_table_same_columns_merged_into_one_copy_block(self) -> None:
        """Same table + same columns → single COPY block."""
        converter = InsertToCopyConverter()
        sql = (
            "INSERT INTO users (id, name) VALUES (1, 'Alice');\n"
            "INSERT INTO users (id, name) VALUES (2, 'Bob');\n"
            "INSERT INTO users (id, name) VALUES (3, 'Carol');\n"
        )

        result = converter.try_convert(sql)

        assert result.success is True
        assert result.rows_converted == 3
        assert result.copy_format is not None
        # Should produce exactly one COPY block
        assert result.copy_format.count("COPY users") == 1
        assert "Alice" in result.copy_format
        assert "Bob" in result.copy_format
        assert "Carol" in result.copy_format

    def test_different_tables_get_separate_copy_blocks(self) -> None:
        """Different tables → separate COPY blocks."""
        converter = InsertToCopyConverter()
        sql = (
            "INSERT INTO users (id, name) VALUES (1, 'Alice');\n"
            "INSERT INTO orders (id, user_id) VALUES (10, 1);\n"
        )

        result = converter.try_convert(sql)

        assert result.success is True
        assert result.rows_converted == 2
        assert result.copy_format is not None
        assert result.copy_format.count("COPY") == 2

    def test_same_table_different_columns_get_separate_copy_blocks(self) -> None:
        """Same table but different column lists → separate COPY blocks."""
        converter = InsertToCopyConverter()
        sql = (
            "INSERT INTO users (id, name) VALUES (1, 'Alice');\n"
            "INSERT INTO users (id, name, email) VALUES (2, 'Bob', 'bob@example.com');\n"
        )

        result = converter.try_convert(sql)

        assert result.success is True
        assert result.rows_converted == 2
        assert result.copy_format is not None
        assert result.copy_format.count("COPY users") == 2

    def test_single_statement_behaviour_unchanged(self) -> None:
        """Single-statement path must be backward-compatible."""
        converter = InsertToCopyConverter()
        sql = "INSERT INTO users (id, name) VALUES (1, 'Alice');"

        result = converter.try_convert(sql, file_path="single.sql")

        assert result.success is True
        assert result.rows_converted == 1
        assert result.copy_format is not None

    def test_single_multi_row_insert_behaviour_unchanged(self) -> None:
        """Multi-row VALUES list within a single INSERT must still work."""
        converter = InsertToCopyConverter()
        sql = "INSERT INTO users (id, name) VALUES (1, 'Alice'), (2, 'Bob'), (3, 'Carol');"

        result = converter.try_convert(sql)

        assert result.success is True
        assert result.rows_converted == 3

    def test_unconvertible_statement_passes_through(self) -> None:
        """Non-convertible statements (NOW(), etc.) are included as-is."""
        converter = InsertToCopyConverter()
        sql = (
            "INSERT INTO users (id, name) VALUES (1, 'Alice');\n"
            "INSERT INTO events (created_at) VALUES (NOW());\n"
        )

        result = converter.try_convert(sql)

        assert result.success is True
        assert result.rows_converted == 1
        assert result.copy_format is not None
        # Unconvertible statement passed through
        assert "events" in result.copy_format

    def test_all_unconvertible_returns_failure(self) -> None:
        """If no statements are convertible, result is failure."""
        converter = InsertToCopyConverter()
        sql = "INSERT INTO a (ts) VALUES (NOW());\nINSERT INTO b (ts) VALUES (NOW());\n"

        result = converter.try_convert(sql)

        assert result.success is False
        assert result.rows_converted is None
        assert result.reason is not None

    def test_mixed_tables_rows_counted_correctly(self) -> None:
        """rows_converted counts all converted rows across all tables."""
        converter = InsertToCopyConverter()
        sql = (
            "INSERT INTO a (id) VALUES (1);\n"
            "INSERT INTO a (id) VALUES (2);\n"
            "INSERT INTO b (id) VALUES (10);\n"
            "INSERT INTO b (id) VALUES (20);\n"
            "INSERT INTO b (id) VALUES (30);\n"
        )

        result = converter.try_convert(sql)

        assert result.success is True
        assert result.rows_converted == 5

    def test_copy_block_contains_correct_rows_for_each_table(self) -> None:
        """Each COPY block contains only rows for that table."""
        converter = InsertToCopyConverter()
        sql = (
            "INSERT INTO cats (id, name) VALUES (1, 'Luna');\n"
            "INSERT INTO dogs (id, name) VALUES (1, 'Rex');\n"
            "INSERT INTO cats (id, name) VALUES (2, 'Mochi');\n"
        )

        result = converter.try_convert(sql)

        assert result.success is True
        assert result.rows_converted == 3
        assert result.copy_format is not None
        # Both cats rows should be in the cats COPY block
        cats_block_start = result.copy_format.index("COPY cats")
        dogs_block_start = result.copy_format.index("COPY dogs")
        cats_section = (
            result.copy_format[cats_block_start:dogs_block_start]
            if cats_block_start < dogs_block_start
            else result.copy_format[cats_block_start:]
        )
        assert "Luna" in cats_section
        assert "Mochi" in cats_section

    def test_output_is_valid_copy_format(self) -> None:
        """Each COPY block must have header, rows, and terminator."""
        converter = InsertToCopyConverter()
        sql = (
            "INSERT INTO users (id, name) VALUES (1, 'Alice');\n"
            "INSERT INTO users (id, name) VALUES (2, 'Bob');\n"
        )

        result = converter.try_convert(sql)

        assert result.success is True
        copy_format = result.copy_format
        assert copy_format is not None
        assert "COPY users (id, name) FROM stdin;" in copy_format
        assert r"\." in copy_format
