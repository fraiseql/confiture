"""Tests for INSERT to COPY batch conversion.

Phase 11, Cycle 4: Add convert_batch() method for batch processing.
"""

from __future__ import annotations

import pytest

from confiture.core.seed.insert_to_copy_converter import InsertToCopyConverter
from confiture.models.results import ConversionReport


class TestBatchConversion:
    """Test batch conversion of multiple seed files."""

    def test_convert_batch_single_file_success(self) -> None:
        """Test batch conversion with single successful file."""
        converter = InsertToCopyConverter()
        files = {
            "simple.sql": "INSERT INTO users (id, name) VALUES (1, 'Alice');",
        }

        report = converter.convert_batch(files)

        assert report.total_files == 1
        assert report.successful == 1
        assert report.failed == 0
        assert report.success_rate == 100.0
        assert len(report.results) == 1
        assert report.results[0].success is True

    def test_convert_batch_single_file_failure(self) -> None:
        """Test batch conversion with single failed file."""
        converter = InsertToCopyConverter()
        files = {
            "with_now.sql": "INSERT INTO events (created_at) VALUES (NOW());",
        }

        report = converter.convert_batch(files)

        assert report.total_files == 1
        assert report.successful == 0
        assert report.failed == 1
        assert report.success_rate == 0.0
        assert len(report.results) == 1
        assert report.results[0].success is False

    def test_convert_batch_multiple_mixed(self) -> None:
        """Test batch conversion with mix of successful and failed files."""
        converter = InsertToCopyConverter()
        files = {
            "users.sql": "INSERT INTO users (id, name) VALUES (1, 'Alice'), (2, 'Bob');",
            "events_now.sql": "INSERT INTO events (created_at) VALUES (NOW());",
            "posts.sql": "INSERT INTO posts (id, title) VALUES (1, 'Hello'), (2, 'World');",
            "complex_cte.sql": "WITH temp AS (SELECT 1) INSERT INTO data (id) SELECT id FROM temp;",
        }

        report = converter.convert_batch(files)

        assert report.total_files == 4
        assert report.successful == 2
        assert report.failed == 2
        assert report.success_rate == 50.0
        assert len(report.results) == 4

    def test_convert_batch_all_success(self) -> None:
        """Test batch conversion where all files succeed."""
        converter = InsertToCopyConverter()
        files = {
            "file1.sql": "INSERT INTO users (id) VALUES (1);",
            "file2.sql": "INSERT INTO posts (id, title) VALUES (1, 'Post 1');",
            "file3.sql": "INSERT INTO tags (name) VALUES ('tag1'), ('tag2');",
        }

        report = converter.convert_batch(files)

        assert report.total_files == 3
        assert report.successful == 3
        assert report.failed == 0
        assert report.success_rate == 100.0
        assert all(r.success for r in report.results)

    def test_convert_batch_all_failure(self) -> None:
        """Test batch conversion where all files fail."""
        converter = InsertToCopyConverter()
        files = {
            "now.sql": "INSERT INTO events (ts) VALUES (NOW());",
            "uuid.sql": "INSERT INTO ids (id) VALUES (uuid_generate_v4());",
            "select.sql": "INSERT INTO data (value) SELECT value FROM defaults;",
        }

        report = converter.convert_batch(files)

        assert report.total_files == 3
        assert report.successful == 0
        assert report.failed == 3
        assert report.success_rate == 0.0
        assert all(not r.success for r in report.results)

    def test_convert_batch_empty_files(self) -> None:
        """Test batch conversion with empty file dict."""
        converter = InsertToCopyConverter()
        files: dict[str, str] = {}

        report = converter.convert_batch(files)

        assert report.total_files == 0
        assert report.successful == 0
        assert report.failed == 0
        assert report.success_rate == 0.0
        assert len(report.results) == 0

    def test_convert_batch_preserves_file_paths(self) -> None:
        """Test that batch conversion preserves file paths in results."""
        converter = InsertToCopyConverter()
        files = {
            "db/seeds/users.sql": "INSERT INTO users (id) VALUES (1);",
            "db/seeds/posts.sql": "INSERT INTO posts (ts) VALUES (NOW());",
        }

        report = converter.convert_batch(files)

        file_paths = {r.file_path for r in report.results}
        assert file_paths == {"db/seeds/users.sql", "db/seeds/posts.sql"}

    def test_convert_batch_to_dict(self) -> None:
        """Test serialization of batch report to dict."""
        converter = InsertToCopyConverter()
        files = {
            "simple.sql": "INSERT INTO users (id) VALUES (1);",
            "complex.sql": "INSERT INTO events (ts) VALUES (NOW());",
        }

        report = converter.convert_batch(files)
        report_dict = report.to_dict()

        assert report_dict["total_files"] == 2
        assert report_dict["successful"] == 1
        assert report_dict["failed"] == 1
        assert report_dict["success_rate"] == 50.0
        assert len(report_dict["results"]) == 2
        assert isinstance(report_dict["results"][0], dict)

    def test_convert_batch_large_files(self) -> None:
        """Test batch conversion with many files."""
        converter = InsertToCopyConverter()

        # Create 100 test files
        files = {f"file_{i}.sql": f"INSERT INTO t{i} (id) VALUES ({i});" for i in range(100)}

        report = converter.convert_batch(files)

        assert report.total_files == 100
        assert report.successful == 100
        assert report.failed == 0
        assert report.success_rate == 100.0

    def test_convert_batch_row_counts(self) -> None:
        """Test that batch conversion counts rows correctly."""
        converter = InsertToCopyConverter()
        files = {
            "single.sql": "INSERT INTO t1 (id) VALUES (1);",
            "multi.sql": "INSERT INTO t2 (id) VALUES (1), (2), (3);",
            "many.sql": "INSERT INTO t3 (id) VALUES (1), (2), (3), (4), (5);",
        }

        report = converter.convert_batch(files)

        # Filter results by file name and check row counts
        results_by_file = {r.file_path: r for r in report.results}
        assert results_by_file["single.sql"].rows_converted == 1
        assert results_by_file["multi.sql"].rows_converted == 3
        assert results_by_file["many.sql"].rows_converted == 5
