"""Unit tests for BaselineDetector."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from confiture.core.baseline_detector import BaselineDetector


class TestNormalizeSchema:
    """Tests for BaselineDetector.normalize_schema."""

    def setup_method(self) -> None:
        self.detector = BaselineDetector(Path("/snapshots"))

    def test_collapses_whitespace(self) -> None:
        sql = "CREATE   TABLE   tb_users  (  id   bigint  );"
        result = self.detector.normalize_schema(sql)
        assert "  " not in result

    def test_lowercases_keywords(self) -> None:
        sql = "CREATE TABLE TB_Users (ID BIGINT NOT NULL);"
        result = self.detector.normalize_schema(sql)
        assert "CREATE" not in result
        assert "create table tb_users" in result

    def test_strips_line_comments(self) -> None:
        sql = "-- This is a comment\nCREATE TABLE tb_x (id bigint);"
        result = self.detector.normalize_schema(sql)
        assert "comment" not in result
        assert "create table tb_x" in result

    def test_strips_block_comments(self) -> None:
        sql = "/* block comment */ CREATE TABLE tb_x (id bigint);"
        result = self.detector.normalize_schema(sql)
        assert "block comment" not in result
        assert "create table tb_x" in result

    def test_removes_if_not_exists(self) -> None:
        sql = "CREATE TABLE IF NOT EXISTS tb_users (id bigint);"
        result = self.detector.normalize_schema(sql)
        assert "if not exists" not in result
        assert "create table tb_users" in result

    def test_removes_if_exists(self) -> None:
        sql = "DROP TABLE IF EXISTS tb_old;"
        result = self.detector.normalize_schema(sql)
        assert "if exists" not in result

    def test_sorts_create_table_blocks_alphabetically(self) -> None:
        sql = "CREATE TABLE tb_zebra (id bigint); CREATE TABLE tb_alpha (id bigint);"
        result = self.detector.normalize_schema(sql)
        pos_alpha = result.index("tb_alpha")
        pos_zebra = result.index("tb_zebra")
        assert pos_alpha < pos_zebra

    def test_empty_schema_returns_empty_string(self) -> None:
        result = self.detector.normalize_schema("")
        assert result == ""

    def test_schema_with_no_tables(self) -> None:
        sql = "-- just a comment\n\nSELECT 1;"
        result = self.detector.normalize_schema(sql)
        assert isinstance(result, str)

    def test_idempotent(self) -> None:
        sql = "CREATE TABLE tb_users (id bigint NOT NULL);"
        once = self.detector.normalize_schema(sql)
        twice = self.detector.normalize_schema(once)
        assert once == twice


class TestLoadSnapshots:
    """Tests for BaselineDetector.load_snapshots."""

    def test_returns_empty_when_dir_absent(self, tmp_path: Path) -> None:
        detector = BaselineDetector(tmp_path / "missing")
        assert detector.load_snapshots() == []

    def test_returns_snapshots_newest_first(self, tmp_path: Path) -> None:
        snapshots_dir = tmp_path / "snapshots"
        snapshots_dir.mkdir()
        (snapshots_dir / "001_init.sql").write_text("CREATE TABLE tb_a (id bigint);")
        (snapshots_dir / "003_later.sql").write_text("CREATE TABLE tb_b (id bigint);")
        (snapshots_dir / "002_middle.sql").write_text("CREATE TABLE tb_c (id bigint);")

        detector = BaselineDetector(snapshots_dir)
        snapshots = detector.load_snapshots()

        versions = [v for v, _ in snapshots]
        assert versions == ["003", "002", "001"]

    def test_ignores_non_sql_files(self, tmp_path: Path) -> None:
        snapshots_dir = tmp_path / "snapshots"
        snapshots_dir.mkdir()
        (snapshots_dir / "001_init.sql").write_text("CREATE TABLE tb_a (id bigint);")
        (snapshots_dir / "README.md").write_text("docs")
        (snapshots_dir / "001_init.py").write_text("# python")

        detector = BaselineDetector(snapshots_dir)
        snapshots = detector.load_snapshots()
        assert len(snapshots) == 1


class TestFindMatchingSnapshot:
    """Tests for BaselineDetector.find_matching_snapshot."""

    def test_returns_none_when_no_snapshots(self, tmp_path: Path) -> None:
        detector = BaselineDetector(tmp_path / "empty")
        result = detector.find_matching_snapshot("CREATE TABLE tb_x (id bigint);")
        assert result is None

    def test_exact_match_returns_version(self, tmp_path: Path) -> None:
        snapshots_dir = tmp_path / "snapshots"
        snapshots_dir.mkdir()
        sql = "CREATE TABLE tb_users (id bigint NOT NULL);"
        (snapshots_dir / "005_add_users.sql").write_text(sql)

        detector = BaselineDetector(snapshots_dir)
        result = detector.find_matching_snapshot(sql)
        assert result == "005"

    def test_match_ignores_keyword_case_differences(self, tmp_path: Path) -> None:
        snapshots_dir = tmp_path / "snapshots"
        snapshots_dir.mkdir()
        stored = "CREATE TABLE tb_users (id bigint NOT NULL);"
        live = "create table tb_users (id bigint not null);"
        (snapshots_dir / "005_add_users.sql").write_text(stored)

        detector = BaselineDetector(snapshots_dir)
        result = detector.find_matching_snapshot(live)
        assert result == "005"

    def test_match_ignores_comment_differences(self, tmp_path: Path) -> None:
        snapshots_dir = tmp_path / "snapshots"
        snapshots_dir.mkdir()
        stored = "-- header\nCREATE TABLE tb_users (id bigint);"
        live = "CREATE TABLE tb_users (id bigint);"
        (snapshots_dir / "003_users.sql").write_text(stored)

        detector = BaselineDetector(snapshots_dir)
        result = detector.find_matching_snapshot(live)
        assert result == "003"

    def test_no_match_returns_none(self, tmp_path: Path) -> None:
        snapshots_dir = tmp_path / "snapshots"
        snapshots_dir.mkdir()
        (snapshots_dir / "001_init.sql").write_text("CREATE TABLE tb_a (x bigint);")

        detector = BaselineDetector(snapshots_dir)
        result = detector.find_matching_snapshot("CREATE TABLE tb_b (y text);")
        assert result is None

    def test_no_match_populates_last_closest(self, tmp_path: Path) -> None:
        snapshots_dir = tmp_path / "snapshots"
        snapshots_dir.mkdir()
        (snapshots_dir / "001_init.sql").write_text("CREATE TABLE tb_a (id bigint);")

        detector = BaselineDetector(snapshots_dir)
        detector.find_matching_snapshot("CREATE TABLE tb_b (name text);")
        assert detector.last_closest is not None
        version, ratio = detector.last_closest
        assert version == "001"
        assert 0.0 <= ratio <= 1.0

    def test_multiple_snapshots_returns_newest_match(self, tmp_path: Path) -> None:
        snapshots_dir = tmp_path / "snapshots"
        snapshots_dir.mkdir()
        sql = "CREATE TABLE tb_users (id bigint);"
        # Both snapshots have same content — should return newest (003)
        (snapshots_dir / "001_init.sql").write_text(sql)
        (snapshots_dir / "003_same.sql").write_text(sql)

        detector = BaselineDetector(snapshots_dir)
        result = detector.find_matching_snapshot(sql)
        assert result == "003"


class TestFuzzyMatching:
    """Tests for fuzzy/structural matching with sparse snapshots (Issue #58)."""

    def test_fuzzy_match_returns_version_when_above_threshold(self, tmp_path: Path) -> None:
        """Fuzzy match is accepted when similarity >= threshold (default 0.85)."""
        snapshots_dir = tmp_path / "snapshots"
        snapshots_dir.mkdir()
        # Snapshot with 3 tables
        snapshot = """
            CREATE TABLE tb_a (id bigint);
            CREATE TABLE tb_b (id bigint);
            CREATE TABLE tb_c (id bigint);
        """
        (snapshots_dir / "001_baseline.sql").write_text(snapshot)

        # Live DB at intermediate state: has all tables from snapshot + 1 new table
        # This simulates migration 002 state when only 001 snapshot exists
        live = """
            CREATE TABLE tb_a (id bigint);
            CREATE TABLE tb_b (id bigint);
            CREATE TABLE tb_c (id bigint);
            CREATE TABLE tb_d (id bigint);
        """

        detector = BaselineDetector(snapshots_dir, similarity_threshold=0.85)
        result = detector.find_matching_snapshot(live)
        # Should match 001 (similarity ~0.856)
        assert result == "001"

    def test_fuzzy_match_respects_custom_threshold(self, tmp_path: Path) -> None:
        """Custom similarity threshold can make matching stricter."""
        snapshots_dir = tmp_path / "snapshots"
        snapshots_dir.mkdir()
        snapshot = """
            CREATE TABLE tb_a (id bigint);
            CREATE TABLE tb_b (id bigint);
        """
        (snapshots_dir / "001_baseline.sql").write_text(snapshot)

        # Live DB differs significantly
        live = """
            CREATE TABLE tb_x (id bigint);
            CREATE TABLE tb_y (id bigint);
            CREATE TABLE tb_z (id bigint);
        """

        # With high threshold, no match
        detector_strict = BaselineDetector(snapshots_dir, similarity_threshold=0.99)
        result = detector_strict.find_matching_snapshot(live)
        assert result is None

        # With low threshold, should match
        detector_loose = BaselineDetector(snapshots_dir, similarity_threshold=0.01)
        result = detector_loose.find_matching_snapshot(live)
        assert result == "001"

    def test_sparse_snapshots_scenario(self, tmp_path: Path) -> None:
        """After migration consolidation (001, 015 snapshots), intermediate states match best."""
        snapshots_dir = tmp_path / "snapshots"
        snapshots_dir.mkdir()

        # Only 2 snapshots after consolidation
        (snapshots_dir / "001_baseline.sql").write_text(
            "CREATE TABLE tb_catalog (id bigint); CREATE TABLE tb_users (id bigint);"
        )
        (snapshots_dir / "015_final.sql").write_text(
            "CREATE TABLE tb_catalog (id bigint); CREATE TABLE tb_users (id bigint); "
            "CREATE TABLE tb_orders (id bigint); CREATE TABLE tb_payments (id bigint); "
            "CREATE TABLE tb_shipments (id bigint);"
        )

        # Live DB is at migration 002 state (matches 001 + adds tb_orders from migration 002)
        live = (
            "CREATE TABLE tb_catalog (id bigint); CREATE TABLE tb_users (id bigint); "
            "CREATE TABLE tb_orders (id bigint);"
        )

        detector = BaselineDetector(snapshots_dir, similarity_threshold=0.75)
        result = detector.find_matching_snapshot(live)
        # Should match 001 (the closest match, ~0.8 similarity)
        assert result == "001"

    def test_exact_match_preferred_over_fuzzy(self, tmp_path: Path) -> None:
        """Exact match is returned immediately, even if a fuzzy match also exists."""
        snapshots_dir = tmp_path / "snapshots"
        snapshots_dir.mkdir()
        (snapshots_dir / "001_init.sql").write_text("CREATE TABLE tb_a (id bigint);")
        (snapshots_dir / "002_exact.sql").write_text("CREATE TABLE tb_a (id bigint);")

        # Exact match with 002
        detector = BaselineDetector(snapshots_dir)
        result = detector.find_matching_snapshot("CREATE TABLE tb_a (id bigint);")
        # Should return 002 (newest exact match), not 001
        assert result == "002"


class TestIntrospectLiveSchema:
    """Tests for BaselineDetector.introspect_live_schema (mocked)."""

    def test_delegates_to_schema_introspector(self, tmp_path: Path) -> None:
        detector = BaselineDetector(tmp_path / "snapshots")

        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.tables = []

        with patch("confiture.core.baseline_detector.SchemaIntrospector") as mock_cls:
            mock_introspector = MagicMock()
            mock_introspector.introspect.return_value = mock_result
            mock_cls.return_value = mock_introspector

            sql = detector.introspect_live_schema(mock_conn)

        mock_cls.assert_called_once_with(mock_conn)
        mock_introspector.introspect.assert_called_once_with(all_tables=True, include_hints=False)
        assert isinstance(sql, str)

    def test_converts_tables_to_sql(self, tmp_path: Path) -> None:
        from confiture.models.introspection import IntrospectedColumn, IntrospectedTable

        detector = BaselineDetector(tmp_path / "snapshots")
        mock_conn = MagicMock()

        col = IntrospectedColumn(name="id", pg_type="bigint", nullable=False, is_primary_key=True)
        table = IntrospectedTable(
            name="tb_users",
            columns=[col],
            outbound_fks=[],
            inbound_fks=[],
            hints=None,
        )
        mock_result = MagicMock()
        mock_result.tables = [table]

        with patch("confiture.core.baseline_detector.SchemaIntrospector") as mock_cls:
            mock_introspector = MagicMock()
            mock_introspector.introspect.return_value = mock_result
            mock_cls.return_value = mock_introspector

            sql = detector.introspect_live_schema(mock_conn)

        assert "tb_users" in sql
        assert "id" in sql
        assert "bigint" in sql
