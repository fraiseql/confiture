"""Unit tests for TreeAllocator — Phase 1 of issue #111.

All tests are pure-Python, no database required.  Temporary directories
are created with pytest's ``tmp_path`` fixture so nothing is written to
the real schema tree.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from confiture.core.tree_allocator import (
    PrefixConfig,
    PrefixScheme,
    TreeAllocator,
    _parse_prefix,
)

# ---------------------------------------------------------------------------
# _parse_prefix — low-level helper
# ---------------------------------------------------------------------------


class TestParsePrefix:
    """Tests for the module-level _parse_prefix helper."""

    def test_decimal_standard(self) -> None:
        assert _parse_prefix("00042_create.sql") == 42

    def test_decimal_zero(self) -> None:
        assert _parse_prefix("00000_init.sql") == 0

    def test_decimal_no_leading_zeros(self) -> None:
        assert _parse_prefix("3_create.sql") == 3

    def test_decimal_large_value(self) -> None:
        assert _parse_prefix("99999_drop.sql") == 99999

    def test_hex_lowercase(self) -> None:
        assert _parse_prefix("0001a_create.sql", base=16) == 0x1A

    def test_hex_uppercase(self) -> None:
        assert _parse_prefix("0001A_create.sql", base=16) == 0x1A

    def test_hex_all_digits(self) -> None:
        # "00001" is valid hex and decimal; base param decides
        assert _parse_prefix("00001_create.sql", base=16) == 1

    def test_no_underscore_returns_none(self) -> None:
        assert _parse_prefix("create.sql") is None

    def test_non_numeric_prefix_returns_none(self) -> None:
        assert _parse_prefix("abc_create.sql") is None

    def test_empty_string_returns_none(self) -> None:
        assert _parse_prefix("") is None

    def test_underscore_first_returns_none(self) -> None:
        assert _parse_prefix("_create.sql") is None

    def test_hex_with_g_char_returns_none(self) -> None:
        # 'g' is not valid hex — _parse_prefix falls back to None
        assert _parse_prefix("0001g_create.sql", base=16) is None


# ---------------------------------------------------------------------------
# PrefixConfig — defaults and field values
# ---------------------------------------------------------------------------


class TestPrefixConfig:
    """Tests for PrefixConfig dataclass defaults."""

    def test_default_scheme_is_decimal(self) -> None:
        cfg = PrefixConfig()
        assert cfg.scheme == PrefixScheme.DECIMAL

    def test_default_width_is_5(self) -> None:
        assert PrefixConfig().width == 5

    def test_default_step_is_1(self) -> None:
        assert PrefixConfig().step == 1

    def test_default_start_is_1(self) -> None:
        assert PrefixConfig().start == 1

    def test_custom_values_stored(self) -> None:
        cfg = PrefixConfig(scheme=PrefixScheme.HEX, width=4, step=10, start=16)
        assert cfg.scheme == PrefixScheme.HEX
        assert cfg.width == 4
        assert cfg.step == 10
        assert cfg.start == 16


# ---------------------------------------------------------------------------
# TreeAllocator._detect_config — scheme and width auto-detection
# ---------------------------------------------------------------------------


class TestDetectConfig:
    """Tests for TreeAllocator._detect_config."""

    def _make_allocator(self, schema_dir: Path) -> TreeAllocator:
        return TreeAllocator(schema_dir)

    def test_empty_dir_returns_defaults(self, tmp_path: Path) -> None:
        alloc = self._make_allocator(tmp_path)
        cfg = alloc._detect_config(tmp_path)
        assert cfg == PrefixConfig()

    def test_decimal_files_detected(self, tmp_path: Path) -> None:
        (tmp_path / "00001_create.sql").touch()
        (tmp_path / "00002_update.sql").touch()
        alloc = self._make_allocator(tmp_path)
        cfg = alloc._detect_config(tmp_path)
        assert cfg.scheme == PrefixScheme.DECIMAL
        assert cfg.width == 5

    def test_hex_files_detected(self, tmp_path: Path) -> None:
        (tmp_path / "0001a_create.sql").touch()
        (tmp_path / "0001b_update.sql").touch()
        alloc = self._make_allocator(tmp_path)
        cfg = alloc._detect_config(tmp_path)
        assert cfg.scheme == PrefixScheme.HEX
        assert cfg.width == 5

    def test_width_detected_from_existing_files(self, tmp_path: Path) -> None:
        (tmp_path / "03321_create.sql").touch()
        (tmp_path / "03322_update.sql").touch()
        alloc = self._make_allocator(tmp_path)
        cfg = alloc._detect_config(tmp_path)
        assert cfg.width == 5

    def test_width_2_detected(self, tmp_path: Path) -> None:
        (tmp_path / "00_extensions.sql").touch()
        (tmp_path / "01_tables.sql").touch()
        alloc = self._make_allocator(tmp_path)
        cfg = alloc._detect_config(tmp_path)
        assert cfg.width == 2

    def test_non_sql_files_ignored(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").touch()
        (tmp_path / "00001_create.sql").touch()
        alloc = self._make_allocator(tmp_path)
        cfg = alloc._detect_config(tmp_path)
        assert cfg.scheme == PrefixScheme.DECIMAL

    def test_files_without_prefix_ignored(self, tmp_path: Path) -> None:
        (tmp_path / "helpers.sql").touch()
        (tmp_path / "00001_create.sql").touch()
        alloc = self._make_allocator(tmp_path)
        cfg = alloc._detect_config(tmp_path)
        assert cfg.scheme == PrefixScheme.DECIMAL

    def test_mode_wins_for_width_tie(self, tmp_path: Path) -> None:
        # Two files with width 5, one with width 3
        (tmp_path / "00001_create.sql").touch()
        (tmp_path / "00002_update.sql").touch()
        (tmp_path / "003_delete.sql").touch()
        alloc = self._make_allocator(tmp_path)
        cfg = alloc._detect_config(tmp_path)
        assert cfg.width == 5


# ---------------------------------------------------------------------------
# TreeAllocator._collect_prefixes
# ---------------------------------------------------------------------------


class TestCollectPrefixes:
    """Tests for TreeAllocator._collect_prefixes."""

    def _make_allocator(self, schema_dir: Path) -> TreeAllocator:
        return TreeAllocator(schema_dir)

    def test_collects_decimal_prefixes(self, tmp_path: Path) -> None:
        (tmp_path / "00001_create.sql").touch()
        (tmp_path / "00003_delete.sql").touch()
        alloc = self._make_allocator(tmp_path)
        result = sorted(alloc._collect_prefixes(tmp_path, PrefixScheme.DECIMAL))
        assert result == [1, 3]

    def test_collects_hex_prefixes(self, tmp_path: Path) -> None:
        (tmp_path / "0001a_create.sql").touch()
        (tmp_path / "0001b_delete.sql").touch()
        alloc = self._make_allocator(tmp_path)
        result = sorted(alloc._collect_prefixes(tmp_path, PrefixScheme.HEX))
        assert result == [0x1A, 0x1B]

    def test_ignores_non_sql_files(self, tmp_path: Path) -> None:
        (tmp_path / "00001_create.sql").touch()
        (tmp_path / "00002_update.txt").touch()
        alloc = self._make_allocator(tmp_path)
        result = alloc._collect_prefixes(tmp_path, PrefixScheme.DECIMAL)
        assert result == [1]

    def test_ignores_files_without_prefix(self, tmp_path: Path) -> None:
        (tmp_path / "helpers.sql").touch()
        (tmp_path / "00001_create.sql").touch()
        alloc = self._make_allocator(tmp_path)
        result = alloc._collect_prefixes(tmp_path, PrefixScheme.DECIMAL)
        assert result == [1]

    def test_empty_dir_returns_empty_list(self, tmp_path: Path) -> None:
        alloc = self._make_allocator(tmp_path)
        result = alloc._collect_prefixes(tmp_path, PrefixScheme.DECIMAL)
        assert result == []


# ---------------------------------------------------------------------------
# TreeAllocator._format_prefix
# ---------------------------------------------------------------------------


class TestFormatPrefix:
    """Tests for TreeAllocator._format_prefix."""

    def test_decimal_zero_padding(self) -> None:
        cfg = PrefixConfig(scheme=PrefixScheme.DECIMAL, width=5)
        result = TreeAllocator._format_prefix(42, cfg)
        assert result == "00042"

    def test_decimal_max_fills_width(self) -> None:
        cfg = PrefixConfig(scheme=PrefixScheme.DECIMAL, width=5)
        result = TreeAllocator._format_prefix(99999, cfg)
        assert result == "99999"

    def test_hex_lowercase_output(self) -> None:
        cfg = PrefixConfig(scheme=PrefixScheme.HEX, width=5)
        result = TreeAllocator._format_prefix(0x1A, cfg)
        assert result == "0001a"

    def test_hex_zero_padding(self) -> None:
        cfg = PrefixConfig(scheme=PrefixScheme.HEX, width=4)
        result = TreeAllocator._format_prefix(1, cfg)
        assert result == "0001"

    def test_width_2(self) -> None:
        cfg = PrefixConfig(scheme=PrefixScheme.DECIMAL, width=2)
        result = TreeAllocator._format_prefix(3, cfg)
        assert result == "03"


# ---------------------------------------------------------------------------
# TreeAllocator.alloc — happy paths
# ---------------------------------------------------------------------------


class TestAllocHappyPath:
    """Tests for TreeAllocator.alloc — successful allocation."""

    def test_next_after_existing_decimal(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        target = schema / "functions"
        target.mkdir(parents=True)
        (target / "00001_create.sql").touch()
        (target / "00002_update.sql").touch()

        result = TreeAllocator(schema).alloc(target)
        assert result == target / "00003.sql"

    def test_next_with_gap_in_sequence(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        target = schema / "functions"
        target.mkdir(parents=True)
        (target / "00001_create.sql").touch()
        (target / "00005_other.sql").touch()

        result = TreeAllocator(schema).alloc(target)
        # max is 5, next is 6
        assert result == target / "00006.sql"

    def test_empty_dir_uses_start(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        target = schema / "functions"
        target.mkdir(parents=True)

        result = TreeAllocator(schema).alloc(target)
        assert result == target / "00001.sql"

    def test_verb_appended_to_filename(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        target = schema / "functions"
        target.mkdir(parents=True)
        (target / "00001_create.sql").touch()

        result = TreeAllocator(schema).alloc(target, verb="update")
        assert result == target / "00002_update.sql"

    def test_hex_scheme_detected_and_incremented(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        target = schema / "functions"
        target.mkdir(parents=True)
        (target / "0001a_create.sql").touch()
        (target / "0001b_update.sql").touch()

        result = TreeAllocator(schema).alloc(target)
        # 0x1b = 27, next = 28 = 0x1c
        assert result == target / "0001c.sql"

    def test_explicit_config_overrides_detection(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        target = schema / "functions"
        target.mkdir(parents=True)
        (target / "00001_create.sql").touch()

        cfg = PrefixConfig(scheme=PrefixScheme.DECIMAL, width=3, step=10, start=10)
        result = TreeAllocator(schema, config=cfg).alloc(target)
        # max=1, step=10 → next=11
        assert result == target / "011.sql"

    def test_explicit_config_empty_dir_uses_start(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        target = schema / "functions"
        target.mkdir(parents=True)

        cfg = PrefixConfig(scheme=PrefixScheme.DECIMAL, width=3, step=10, start=100)
        result = TreeAllocator(schema, config=cfg).alloc(target)
        assert result == target / "100.sql"

    def test_returns_path_inside_target_dir(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        target = schema / "catalog" / "manufacturer"
        target.mkdir(parents=True)

        result = TreeAllocator(schema).alloc(target, verb="create")
        assert result.parent == target

    def test_result_has_sql_extension(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        target = schema / "functions"
        target.mkdir(parents=True)

        result = TreeAllocator(schema).alloc(target)
        assert result.suffix == ".sql"

    def test_result_is_deterministic(self, tmp_path: Path) -> None:
        """Same tree state always produces the same answer."""
        schema = tmp_path / "schema"
        target = schema / "functions"
        target.mkdir(parents=True)
        (target / "00003_create.sql").touch()

        alloc = TreeAllocator(schema)
        first = alloc.alloc(target)
        second = alloc.alloc(target)
        assert first == second

    def test_width_2_schema(self, tmp_path: Path) -> None:
        """Handles db/schema/00_common-style narrow prefixes."""
        schema = tmp_path / "schema"
        target = schema / "00_common"
        target.mkdir(parents=True)
        (target / "00_extensions.sql").touch()
        (target / "01_tables.sql").touch()

        result = TreeAllocator(schema).alloc(target)
        assert result == target / "02.sql"

    def test_schema_dir_itself_as_target(self, tmp_path: Path) -> None:
        """target_dir may equal schema_dir (single-level tree)."""
        schema = tmp_path / "schema"
        schema.mkdir()
        (schema / "00001_create.sql").touch()

        result = TreeAllocator(schema).alloc(schema)
        assert result == schema / "00002.sql"


# ---------------------------------------------------------------------------
# TreeAllocator.alloc — error paths
# ---------------------------------------------------------------------------


class TestAllocErrorPaths:
    """Tests for TreeAllocator.alloc — validation failures."""

    def test_nonexistent_dir_raises_value_error(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        schema.mkdir()
        target = schema / "does_not_exist"

        with pytest.raises(ValueError, match="does not exist"):
            TreeAllocator(schema).alloc(target)

    def test_file_path_raises_value_error(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        schema.mkdir()
        target = schema / "some_file.sql"
        target.touch()

        with pytest.raises(ValueError, match="not a directory"):
            TreeAllocator(schema).alloc(target)

    def test_outside_schema_root_raises_value_error(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        schema.mkdir()
        outside = tmp_path / "other"
        outside.mkdir()

        with pytest.raises(ValueError, match="not within schema root"):
            TreeAllocator(schema).alloc(outside)

    def test_sibling_dir_raises_value_error(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        schema.mkdir()
        sibling = tmp_path / "schema_backup"
        sibling.mkdir()

        with pytest.raises(ValueError, match="not within schema root"):
            TreeAllocator(schema).alloc(sibling)
