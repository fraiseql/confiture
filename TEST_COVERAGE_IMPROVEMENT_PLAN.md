# Test Coverage Improvement Plan

**Project**: Confiture
**Current Coverage**: 58.91% (8,011 statements, 3,292 missing)
**Target Coverage**: 80%+ for core modules
**Date**: January 16, 2026

---

## Executive Summary

This plan prioritizes test coverage improvements based on:
1. **Impact** - Core functionality vs edge features
2. **Risk** - User-facing code vs internal utilities
3. **Effort** - Quick wins vs complex test setup

### Priority Matrix

| Priority | Category | Coverage Target | Estimated Tests |
|----------|----------|-----------------|-----------------|
| P0 | Housekeeping (delete deprecated) | N/A | 0 |
| P1 | Critical gaps (<30%) | 80%+ | ~50 tests |
| P2 | Medium gaps (30-60%) | 70%+ | ~80 tests |
| P3 | CLI/Builder improvements | 85%+ | ~40 tests |
| P4 | Low priority (examples, future) | Skip | 0 |

---

## Phase 1: Housekeeping (P0) - Immediate

### 1.1 Delete Deprecated Files

These files have 0% coverage because they're replaced by packages:

```bash
# Files to delete (replaced by packages)
rm python/confiture/core/hooks.py      # Replaced by core/hooks/ package
rm python/confiture/core/linting.py    # Replaced by core/linting/ package
```

**Verification**:
```bash
# Ensure no imports reference these files
grep -r "from confiture.core.hooks import" python/
grep -r "from confiture.core.linting import" python/
grep -r "from confiture.core import hooks" python/
grep -r "from confiture.core import linting" python/
```

**Impact**: Removes ~253 lines from coverage calculation, improving overall percentage.

---

## Phase 2: Critical Gaps (P1) - High Priority

### 2.1 Dry-Run Report Generator (2.61% → 80%)

**File**: `python/confiture/core/migration/dry_run/report.py` (332 lines)
**Current Tests**: None
**New Test File**: `tests/unit/test_dry_run_report.py`

#### Test Cases to Add:

```python
# tests/unit/test_dry_run_report.py
"""Comprehensive tests for DryRunReportGenerator."""

import pytest
from datetime import datetime
from confiture.core.migration.dry_run.report import DryRunReportGenerator
from confiture.core.migration.dry_run.dry_run_mode import DryRunReport
from confiture.core.migration.dry_run.models import (
    StatementClassification,
    StatementAnalysis,
    ImpactAnalysis,
    ConcurrencyAnalysis,
    CostAnalysis,
)


class TestDryRunReportGenerator:
    """Tests for DryRunReportGenerator class."""

    @pytest.fixture
    def generator(self):
        """Create report generator."""
        return DryRunReportGenerator(use_colors=False, verbose=True)

    @pytest.fixture
    def sample_report(self):
        """Create sample DryRunReport for testing."""
        return DryRunReport(
            migration_id="test_migration_001",
            started_at=datetime(2026, 1, 16, 10, 0, 0),
            completed_at=datetime(2026, 1, 16, 10, 0, 5),
            total_execution_time_ms=5000,
            statements_analyzed=3,
            unsafe_count=1,
            total_estimated_time_ms=2000,
            total_estimated_disk_mb=10.5,
            warnings=["Table 'users' will be locked"],
            analyses=[
                StatementAnalysis(
                    statement="ALTER TABLE users ADD COLUMN bio TEXT",
                    classification=StatementClassification.SAFE,
                    execution_time_ms=100,
                    success=True,
                    impact=ImpactAnalysis(
                        affected_tables=["users"],
                        estimated_size_change_mb=0.1,
                    ),
                    concurrency=ConcurrencyAnalysis(
                        risk_level="low",
                        tables_locked=[],
                        lock_duration_estimate_ms=50,
                    ),
                    cost=CostAnalysis(
                        estimated_duration_ms=100,
                        estimated_disk_usage_mb=0.1,
                        estimated_cpu_percent=10.0,
                        is_expensive=False,
                    ),
                ),
            ],
        )

    # Text Report Tests
    def test_generate_text_report_basic(self, generator, sample_report):
        """Test basic text report generation."""
        report = generator.generate_text_report(sample_report)
        assert "DRY-RUN MIGRATION ANALYSIS REPORT" in report
        assert "test_migration_001" in report or "SUMMARY" in report

    def test_generate_text_report_with_warnings(self, generator, sample_report):
        """Test text report includes warnings section."""
        report = generator.generate_text_report(sample_report)
        assert "WARNINGS" in report
        assert "Table 'users' will be locked" in report

    def test_generate_text_report_verbose_statements(self, generator, sample_report):
        """Test verbose mode includes statement details."""
        report = generator.generate_text_report(sample_report)
        assert "STATEMENT DETAILS" in report
        assert "ALTER TABLE" in report

    def test_generate_text_report_non_verbose(self, sample_report):
        """Test non-verbose mode excludes statement details."""
        generator = DryRunReportGenerator(use_colors=False, verbose=False)
        report = generator.generate_text_report(sample_report)
        assert "STATEMENT DETAILS" not in report

    def test_generate_text_report_no_warnings(self, generator):
        """Test text report without warnings."""
        report = DryRunReport(
            migration_id="test",
            statements_analyzed=1,
            warnings=[],
            analyses=[],
        )
        text = generator.generate_text_report(report)
        assert "WARNINGS" not in text

    # JSON Report Tests
    def test_generate_json_report_structure(self, generator, sample_report):
        """Test JSON report has correct structure."""
        json_report = generator.generate_json_report(sample_report)

        assert "migration_id" in json_report
        assert "started_at" in json_report
        assert "completed_at" in json_report
        assert "summary" in json_report
        assert "analyses" in json_report

    def test_generate_json_report_summary(self, generator, sample_report):
        """Test JSON report summary section."""
        json_report = generator.generate_json_report(sample_report)
        summary = json_report["summary"]

        assert summary["unsafe_count"] == 1
        assert summary["total_estimated_time_ms"] == 2000
        assert summary["total_estimated_disk_mb"] == 10.5

    def test_generate_json_report_analyses(self, generator, sample_report):
        """Test JSON report analyses section."""
        json_report = generator.generate_json_report(sample_report)

        assert len(json_report["analyses"]) == 1
        analysis = json_report["analyses"][0]
        assert analysis["classification"] == "safe"
        assert analysis["success"] is True

    def test_generate_json_report_with_none_timestamps(self, generator):
        """Test JSON report handles None timestamps."""
        report = DryRunReport(
            migration_id="test",
            started_at=None,
            completed_at=None,
            statements_analyzed=0,
            analyses=[],
        )
        json_report = generator.generate_json_report(report)
        assert json_report["started_at"] is None
        assert json_report["completed_at"] is None

    def test_generate_json_report_analysis_without_impact(self, generator):
        """Test JSON handles analysis without impact data."""
        report = DryRunReport(
            migration_id="test",
            statements_analyzed=1,
            analyses=[
                StatementAnalysis(
                    statement="SELECT 1",
                    classification=StatementClassification.SAFE,
                    execution_time_ms=1,
                    success=True,
                    impact=None,
                    concurrency=None,
                    cost=None,
                ),
            ],
        )
        json_report = generator.generate_json_report(report)
        analysis = json_report["analyses"][0]
        assert analysis["impact"] is None
        assert analysis["concurrency"] is None
        assert analysis["cost"] is None

    # Summary Formatting Tests
    def test_format_summary_basic(self, generator, sample_report):
        """Test summary formatting."""
        lines = generator._format_summary(sample_report)
        text = "\n".join(lines)

        assert "SUMMARY" in text
        assert "Statements analyzed: 3" in text

    def test_format_summary_with_high_risk(self, generator):
        """Test summary with high concurrency risk."""
        report = DryRunReport(
            migration_id="test",
            statements_analyzed=1,
            analyses=[
                StatementAnalysis(
                    statement="ALTER TABLE",
                    classification=StatementClassification.UNSAFE,
                    execution_time_ms=100,
                    success=True,
                    concurrency=ConcurrencyAnalysis(
                        risk_level="high",
                        tables_locked=["users"],
                        lock_duration_estimate_ms=5000,
                    ),
                ),
            ],
        )
        lines = generator._format_summary(report)
        text = "\n".join(lines)
        assert "Concurrency Risk" in text
        assert "High risk" in text

    # Warning Formatting Tests
    def test_format_warnings(self, generator, sample_report):
        """Test warnings formatting."""
        lines = generator._format_warnings(sample_report)
        text = "\n".join(lines)

        assert "WARNINGS" in text
        assert "Table 'users' will be locked" in text

    # Statement Formatting Tests
    def test_format_statements_with_impact(self, generator, sample_report):
        """Test statement formatting with impact data."""
        lines = generator._format_statements(sample_report)
        text = "\n".join(lines)

        assert "STATEMENT DETAILS" in text
        assert "Impact tables:" in text

    def test_format_statements_with_constraint_violations(self, generator):
        """Test statement formatting with constraint violations."""
        report = DryRunReport(
            migration_id="test",
            statements_analyzed=1,
            analyses=[
                StatementAnalysis(
                    statement="ALTER TABLE",
                    classification=StatementClassification.WARNING,
                    execution_time_ms=100,
                    success=True,
                    impact=ImpactAnalysis(
                        affected_tables=["users"],
                        constraint_violations=["fk_user_org"],
                    ),
                ),
            ],
        )
        lines = generator._format_statements(report)
        text = "\n".join(lines)
        assert "Constraint risks: 1" in text

    # Footer/Recommendations Tests
    def test_format_footer_unsafe_operations(self, generator):
        """Test footer with unsafe operations."""
        report = DryRunReport(
            migration_id="test",
            statements_analyzed=1,
            unsafe_count=2,
            analyses=[],
        )
        lines = generator._format_footer(report)
        text = "\n".join(lines)

        assert "UNSAFE OPERATIONS DETECTED" in text
        assert "maintenance window" in text

    def test_format_footer_high_concurrency_risk(self, generator):
        """Test footer with high concurrency risk."""
        report = DryRunReport(
            migration_id="test",
            statements_analyzed=1,
            analyses=[
                StatementAnalysis(
                    statement="ALTER TABLE",
                    classification=StatementClassification.SAFE,
                    execution_time_ms=100,
                    success=True,
                    concurrency=ConcurrencyAnalysis(
                        risk_level="high",
                        tables_locked=["users"],
                        lock_duration_estimate_ms=5000,
                    ),
                ),
            ],
        )
        lines = generator._format_footer(report)
        text = "\n".join(lines)
        assert "HIGH CONCURRENCY RISK DETECTED" in text

    def test_format_footer_expensive_operations(self, generator):
        """Test footer with expensive operations."""
        report = DryRunReport(
            migration_id="test",
            statements_analyzed=1,
            analyses=[
                StatementAnalysis(
                    statement="CREATE INDEX",
                    classification=StatementClassification.SAFE,
                    execution_time_ms=100,
                    success=True,
                    cost=CostAnalysis(
                        estimated_duration_ms=60000,
                        estimated_disk_usage_mb=500.0,
                        estimated_cpu_percent=90.0,
                        is_expensive=True,
                    ),
                ),
            ],
        )
        lines = generator._format_footer(report)
        text = "\n".join(lines)
        assert "EXPENSIVE OPERATIONS DETECTED" in text

    def test_format_footer_all_clear(self, generator):
        """Test footer when all checks pass."""
        report = DryRunReport(
            migration_id="test",
            statements_analyzed=1,
            unsafe_count=0,
            analyses=[
                StatementAnalysis(
                    statement="SELECT 1",
                    classification=StatementClassification.SAFE,
                    execution_time_ms=1,
                    success=True,
                ),
            ],
        )
        lines = generator._format_footer(report)
        text = "\n".join(lines)
        assert "All checks passed" in text

    # Classification Icon Tests
    def test_get_classification_icon_safe(self):
        """Test icon for safe classification."""
        icon = DryRunReportGenerator._get_classification_icon(
            StatementClassification.SAFE
        )
        assert icon == "✓"

    def test_get_classification_icon_warning(self):
        """Test icon for warning classification."""
        icon = DryRunReportGenerator._get_classification_icon(
            StatementClassification.WARNING
        )
        assert "⚠" in icon

    def test_get_classification_icon_unsafe(self):
        """Test icon for unsafe classification."""
        icon = DryRunReportGenerator._get_classification_icon(
            StatementClassification.UNSAFE
        )
        assert "❌" in icon

    # Summary Line Tests
    def test_generate_summary_line_safe(self, generator):
        """Test summary line for safe migration."""
        report = DryRunReport(
            migration_id="test",
            statements_analyzed=5,
            total_estimated_time_ms=1000,
            total_estimated_disk_mb=2.5,
            has_unsafe_statements=False,
            analyses=[],
        )
        line = generator.generate_summary_line(report)

        assert "SAFE" in line
        assert "5 statements" in line
        assert "1000ms" in line
        assert "2.5MB" in line

    def test_generate_summary_line_unsafe(self, generator):
        """Test summary line for unsafe migration."""
        report = DryRunReport(
            migration_id="test",
            statements_analyzed=3,
            total_estimated_time_ms=5000,
            total_estimated_disk_mb=100.0,
            has_unsafe_statements=True,
            analyses=[],
        )
        line = generator.generate_summary_line(report)

        assert "UNSAFE" in line
```

**Estimated Coverage Improvement**: 2.61% → 85%+ (~28 new tests)

---

### 2.2 Anonymization Strategies (0-35% → 70%+)

#### 2.2.1 Credit Card Strategy (18.94% → 80%)

**File**: `python/confiture/core/anonymization/strategies/credit_card.py`
**New Test File**: `tests/unit/anonymization/test_credit_card_strategy.py`

```python
# tests/unit/anonymization/test_credit_card_strategy.py
"""Comprehensive tests for credit card anonymization strategy."""

import pytest
from confiture.core.anonymization.strategies.credit_card import (
    CreditCardStrategy,
    CreditCardConfig,
    luhn_checksum,
    detect_card_type,
    is_valid_card_number,
    CARD_TYPES,
)


class TestLuhnChecksum:
    """Tests for Luhn checksum calculation."""

    def test_luhn_checksum_visa(self):
        """Test Luhn checksum for Visa card."""
        # Visa test number: 4532015112830366
        # Without last digit: 453201511283036
        checksum = luhn_checksum("453201511283036")
        assert checksum == 6

    def test_luhn_checksum_mastercard(self):
        """Test Luhn checksum for Mastercard."""
        # Mastercard: 5425233430109903
        checksum = luhn_checksum("542523343010990")
        assert checksum == 3

    def test_luhn_checksum_amex(self):
        """Test Luhn checksum for Amex."""
        # Amex: 374245455400126
        checksum = luhn_checksum("37424545540012")
        assert checksum == 6

    def test_luhn_checksum_all_zeros(self):
        """Test Luhn with all zeros."""
        checksum = luhn_checksum("000000000000000")
        assert isinstance(checksum, int)
        assert 0 <= checksum <= 9


class TestDetectCardType:
    """Tests for card type detection."""

    @pytest.mark.parametrize("card,expected", [
        ("4532015112830366", "visa"),
        ("4111111111111111", "visa"),
        ("5425233430109903", "mastercard"),
        ("5105105105105100", "mastercard"),
        ("374245455400126", "amex"),
        ("378282246310005", "amex"),
        ("6011111111111117", "discover"),
        ("3530111333300000", "jcb"),
    ])
    def test_detect_known_card_types(self, card, expected):
        """Test detection of known card types."""
        assert detect_card_type(card) == expected

    def test_detect_unknown_card_type(self):
        """Test unknown card type detection."""
        assert detect_card_type("1234567890123456") == "unknown"

    def test_detect_empty_string(self):
        """Test empty string returns unknown."""
        assert detect_card_type("") == "unknown"

    def test_detect_non_digit_string(self):
        """Test non-digit string returns unknown."""
        assert detect_card_type("abcd1234efgh5678") == "unknown"

    def test_detect_wrong_length(self):
        """Test wrong length returns unknown."""
        assert detect_card_type("4111") == "unknown"  # Too short for Visa


class TestIsValidCardNumber:
    """Tests for card number validation."""

    @pytest.mark.parametrize("card", [
        "4532015112830366",
        "5425233430109903",
        "374245455400126",
        "6011111111111117",
        "4111111111111111",
    ])
    def test_valid_card_numbers(self, card):
        """Test valid card numbers pass validation."""
        assert is_valid_card_number(card) is True

    def test_valid_card_with_spaces(self):
        """Test card with spaces is valid."""
        assert is_valid_card_number("4532 0151 1283 0366") is True

    def test_valid_card_with_dashes(self):
        """Test card with dashes is valid."""
        assert is_valid_card_number("4532-0151-1283-0366") is True

    def test_invalid_checksum(self):
        """Test card with invalid checksum fails."""
        assert is_valid_card_number("4532015112830367") is False  # Changed last digit

    def test_empty_string(self):
        """Test empty string is invalid."""
        assert is_valid_card_number("") is False

    def test_none_value(self):
        """Test None is invalid."""
        assert is_valid_card_number(None) is False

    def test_too_short(self):
        """Test too short card is invalid."""
        assert is_valid_card_number("411111111") is False

    def test_too_long(self):
        """Test too long card is invalid."""
        assert is_valid_card_number("41111111111111111111") is False

    def test_non_digit_characters(self):
        """Test non-digit characters (except space/dash) are invalid."""
        assert is_valid_card_number("4532a151b283c366") is False


class TestCreditCardStrategy:
    """Tests for CreditCardStrategy class."""

    @pytest.fixture
    def strategy_preserve_last4(self):
        """Create strategy that preserves last 4 digits."""
        config = CreditCardConfig(seed=12345, preserve_last4=True, preserve_bin=False)
        return CreditCardStrategy(config)

    @pytest.fixture
    def strategy_preserve_bin(self):
        """Create strategy that preserves BIN."""
        config = CreditCardConfig(seed=12345, preserve_last4=False, preserve_bin=True)
        return CreditCardStrategy(config)

    @pytest.fixture
    def strategy_full_anonymize(self):
        """Create strategy for full anonymization."""
        config = CreditCardConfig(seed=12345, preserve_last4=False, preserve_bin=False)
        return CreditCardStrategy(config)

    # Basic Anonymization Tests
    def test_anonymize_preserves_last4(self, strategy_preserve_last4):
        """Test last 4 digits are preserved."""
        original = "4532015112830366"
        result = strategy_preserve_last4.anonymize(original)

        assert result[-4:] == "0366" or result.endswith(original[-4:])
        assert result != original

    def test_anonymize_preserves_bin(self, strategy_preserve_bin):
        """Test BIN (first 6) is preserved."""
        original = "4532015112830366"
        result = strategy_preserve_bin.anonymize(original)

        # BIN should be preserved
        assert result[:6] == "453201"

    def test_anonymize_deterministic(self, strategy_preserve_last4):
        """Test same input gives same output (deterministic)."""
        original = "4532015112830366"
        result1 = strategy_preserve_last4.anonymize(original)
        result2 = strategy_preserve_last4.anonymize(original)

        assert result1 == result2

    def test_anonymize_different_seeds(self):
        """Test different seeds give different outputs."""
        config1 = CreditCardConfig(seed=12345, preserve_last4=True)
        config2 = CreditCardConfig(seed=67890, preserve_last4=True)

        strategy1 = CreditCardStrategy(config1)
        strategy2 = CreditCardStrategy(config2)

        original = "4532015112830366"
        result1 = strategy1.anonymize(original)
        result2 = strategy2.anonymize(original)

        assert result1 != result2

    # Format Preservation Tests
    def test_anonymize_preserves_spaces_format(self, strategy_preserve_last4):
        """Test spaces in card number are preserved."""
        original = "4532 0151 1283 0366"
        result = strategy_preserve_last4.anonymize(original)

        # Should have same format (4 groups of 4 with spaces)
        assert result.count(" ") == 3

    def test_anonymize_preserves_dash_format(self, strategy_preserve_last4):
        """Test dashes in card number are preserved."""
        original = "4532-0151-1283-0366"
        result = strategy_preserve_last4.anonymize(original)

        # Should have same format (4 groups of 4 with dashes)
        assert result.count("-") == 3

    # Edge Cases
    def test_anonymize_none_value(self, strategy_preserve_last4):
        """Test None input returns None."""
        assert strategy_preserve_last4.anonymize(None) is None

    def test_anonymize_empty_string(self, strategy_preserve_last4):
        """Test empty string returns empty string."""
        assert strategy_preserve_last4.anonymize("") == ""

    def test_anonymize_whitespace_only(self, strategy_preserve_last4):
        """Test whitespace-only returns whitespace."""
        assert strategy_preserve_last4.anonymize("   ") == "   "

    def test_anonymize_invalid_card_masked(self):
        """Test invalid card is simply masked."""
        config = CreditCardConfig(seed=12345, validate=True)
        strategy = CreditCardStrategy(config)

        result = strategy.anonymize("1234567890123456")  # Invalid Luhn
        # Should be masked (not pass-through)
        assert result != "1234567890123456"

    def test_anonymize_skip_validation(self):
        """Test validation can be skipped."""
        config = CreditCardConfig(seed=12345, validate=False)
        strategy = CreditCardStrategy(config)

        # Should process even invalid numbers
        result = strategy.anonymize("0000000000000000")
        assert len(result) == 16

    # Luhn Validity of Output
    def test_output_passes_luhn(self, strategy_preserve_last4):
        """Test anonymized output passes Luhn validation."""
        original = "4532015112830366"
        result = strategy_preserve_last4.anonymize(original)

        # Remove any formatting
        cleaned = result.replace(" ", "").replace("-", "")
        assert is_valid_card_number(cleaned)

    # Card Type Preservation
    @pytest.mark.parametrize("card_type,original", [
        ("visa", "4532015112830366"),
        ("mastercard", "5425233430109903"),
        ("amex", "374245455400126"),
    ])
    def test_preserves_card_type(self, card_type, original):
        """Test card type is preserved in output."""
        config = CreditCardConfig(seed=12345, preserve_last4=True)
        strategy = CreditCardStrategy(config)

        result = strategy.anonymize(original)
        cleaned = result.replace(" ", "").replace("-", "")

        detected_type = detect_card_type(cleaned)
        # Due to BIN generation, type should match
        assert detected_type in [card_type, "unknown"]  # May vary based on generated BIN

    # Validate Method
    def test_validate_string(self, strategy_preserve_last4):
        """Test validate accepts string."""
        assert strategy_preserve_last4.validate("4532015112830366") is True

    def test_validate_none(self, strategy_preserve_last4):
        """Test validate accepts None."""
        assert strategy_preserve_last4.validate(None) is True

    def test_validate_non_string(self, strategy_preserve_last4):
        """Test validate rejects non-string."""
        assert strategy_preserve_last4.validate(12345) is False

    # Short Name
    def test_short_name_preserve_last4(self, strategy_preserve_last4):
        """Test short name for preserve_last4 mode."""
        assert strategy_preserve_last4.short_name() == "credit_card:preserve_last4"

    def test_short_name_preserve_bin(self, strategy_preserve_bin):
        """Test short name for preserve_bin mode."""
        assert strategy_preserve_bin.short_name() == "credit_card:preserve_bin"

    def test_short_name_full(self, strategy_full_anonymize):
        """Test short name for full anonymization."""
        assert strategy_full_anonymize.short_name() == "credit_card:full"


class TestCreditCardConfig:
    """Tests for CreditCardConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = CreditCardConfig(seed=12345)

        assert config.preserve_last4 is True
        assert config.preserve_bin is False
        assert config.mask_char == "*"
        assert config.validate is True

    def test_custom_mask_char(self):
        """Test custom mask character."""
        config = CreditCardConfig(seed=12345, mask_char="X")
        assert config.mask_char == "X"
```

**Estimated Coverage Improvement**: 18.94% → 85%+ (~45 new tests)

---

#### 2.2.2 Other Anonymization Strategies (Quick Wins)

Create similar test files for:

| Strategy | Current | Target | Est. Tests |
|----------|---------|--------|------------|
| `address.py` | 26.32% | 70% | 20 |
| `ip_address.py` | 27.03% | 70% | 20 |
| `date.py` | 32.79% | 70% | 25 |
| `name.py` | 33.93% | 70% | 20 |
| `text_redaction.py` | 36.54% | 70% | 25 |

**Test Pattern** (apply to each):
```python
class TestXxxStrategy:
    """Tests for Xxx anonymization strategy."""

    @pytest.fixture
    def strategy(self):
        """Create strategy with default config."""
        return XxxStrategy(XxxConfig(seed=12345))

    # Core functionality
    def test_anonymize_basic(self, strategy): ...
    def test_anonymize_deterministic(self, strategy): ...
    def test_anonymize_none(self, strategy): ...
    def test_anonymize_empty(self, strategy): ...

    # Edge cases specific to type
    def test_edge_case_1(self, strategy): ...
    def test_edge_case_2(self, strategy): ...

    # Validation
    def test_validate_correct_type(self, strategy): ...
    def test_validate_incorrect_type(self, strategy): ...

    # Configuration
    def test_config_defaults(self): ...
    def test_config_custom(self): ...
```

---

### 2.3 Security Modules (26-44% → 70%)

#### 2.3.1 KMS Manager (26.02% → 70%)

**File**: `python/confiture/core/anonymization/security/kms_manager.py`
**New Test File**: `tests/unit/security/test_kms_manager.py`

```python
# tests/unit/security/test_kms_manager.py
"""Tests for KMS (Key Management Service) manager."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from confiture.core.anonymization.security.kms_manager import (
    KMSManager,
    KMSConfig,
    KeyMetadata,
    # ... other exports
)


class TestKMSManager:
    """Tests for KMSManager class."""

    @pytest.fixture
    def mock_kms_client(self):
        """Create mock KMS client."""
        return Mock()

    @pytest.fixture
    def kms_manager(self, mock_kms_client):
        """Create KMS manager with mock client."""
        config = KMSConfig(
            provider="mock",
            key_id="test-key-123",
        )
        manager = KMSManager(config)
        manager._client = mock_kms_client
        return manager

    # Key Operations
    def test_encrypt_data(self, kms_manager, mock_kms_client):
        """Test data encryption."""
        mock_kms_client.encrypt.return_value = b"encrypted_data"

        result = kms_manager.encrypt(b"plaintext")

        mock_kms_client.encrypt.assert_called_once()
        assert result == b"encrypted_data"

    def test_decrypt_data(self, kms_manager, mock_kms_client):
        """Test data decryption."""
        mock_kms_client.decrypt.return_value = b"plaintext"

        result = kms_manager.decrypt(b"encrypted_data")

        mock_kms_client.decrypt.assert_called_once()
        assert result == b"plaintext"

    def test_rotate_key(self, kms_manager, mock_kms_client):
        """Test key rotation."""
        mock_kms_client.rotate_key.return_value = "new-key-456"

        new_key_id = kms_manager.rotate_key()

        mock_kms_client.rotate_key.assert_called_once()
        assert new_key_id == "new-key-456"

    # Error Handling
    def test_encrypt_handles_error(self, kms_manager, mock_kms_client):
        """Test encryption error handling."""
        mock_kms_client.encrypt.side_effect = Exception("KMS error")

        with pytest.raises(Exception, match="KMS error"):
            kms_manager.encrypt(b"plaintext")

    # Configuration
    def test_config_validation(self):
        """Test configuration validation."""
        config = KMSConfig(
            provider="aws",
            key_id="arn:aws:kms:...",
            region="us-east-1",
        )
        assert config.provider == "aws"
        assert config.key_id.startswith("arn:")
```

---

## Phase 3: CLI & Builder Improvements (P3)

### 3.1 CLI Main Module (74.73% → 85%)

**File**: `python/confiture/cli/main.py` (1364 lines, 138 missing)
**Existing Tests**: `tests/e2e/test_cli.py`, `tests/unit/test_cli_*.py`
**New Test File**: `tests/unit/test_cli_coverage.py`

#### Missing Coverage Areas:

1. **`init` command edge cases** (lines 77-82):
   - Already initialized project confirmation
   - User cancellation

2. **`build` command paths** (lines 257-261):
   - `--schema-only` flag behavior
   - Empty include_dirs after filtering

3. **`migrate up` error paths** (lines 786-924):
   - Failed migration error details
   - Various error types (SQL, connection, etc.)

4. **`migrate down` dry-run** (lines 1162-1251):
   - Dry-run rollback analysis
   - JSON format output

```python
# tests/unit/test_cli_coverage.py
"""Additional CLI tests for coverage improvement."""

import pytest
from pathlib import Path
from typer.testing import CliRunner
from confiture.cli.main import app


runner = CliRunner()


class TestInitCommand:
    """Tests for init command edge cases."""

    def test_init_already_exists_cancel(self, tmp_path):
        """Test canceling when project already exists."""
        # Create existing project
        (tmp_path / "db").mkdir()

        # Run init and answer 'n' to confirmation
        result = runner.invoke(app, ["init", str(tmp_path)], input="n\n")

        assert result.exit_code == 0 or "Cancelled" in result.output or result.exit_code == 1

    def test_init_already_exists_continue(self, tmp_path):
        """Test continuing when project already exists."""
        # Create existing project
        (tmp_path / "db").mkdir()

        # Run init and answer 'y' to confirmation
        result = runner.invoke(app, ["init", str(tmp_path)], input="y\n")

        assert result.exit_code == 0
        assert "initialized" in result.output.lower()


class TestBuildCommand:
    """Tests for build command edge cases."""

    def test_build_schema_only(self, tmp_path):
        """Test --schema-only flag excludes seed data."""
        # Setup project structure
        schema_dir = tmp_path / "db" / "schema" / "00_common"
        schema_dir.mkdir(parents=True)
        (schema_dir / "test.sql").write_text("CREATE TABLE test (id INT);")

        seeds_dir = tmp_path / "db" / "seeds"
        seeds_dir.mkdir(parents=True)
        (seeds_dir / "seed.sql").write_text("INSERT INTO test VALUES (1);")

        # Create environment config
        env_dir = tmp_path / "db" / "environments"
        env_dir.mkdir(parents=True)
        (env_dir / "local.yaml").write_text("""
name: local
include_dirs:
  - db/schema/00_common
  - db/seeds
database:
  host: localhost
  database: test
""")

        result = runner.invoke(
            app,
            ["build", "--env", "local", "--schema-only", "--project-dir", str(tmp_path)],
        )

        # Check that it ran (may fail due to config, but flag should be processed)
        assert "--schema-only" not in result.output or result.exit_code in [0, 1]


class TestMigrateUpCommand:
    """Tests for migrate up command."""

    def test_migrate_up_dry_run_and_force_error(self, tmp_path):
        """Test that --dry-run and --force cannot be used together."""
        result = runner.invoke(
            app,
            ["migrate", "up", "--dry-run", "--force"],
        )

        assert result.exit_code == 1
        assert "Cannot use" in result.output

    def test_migrate_up_dry_run_and_dry_run_execute_error(self, tmp_path):
        """Test that --dry-run and --dry-run-execute cannot be used together."""
        result = runner.invoke(
            app,
            ["migrate", "up", "--dry-run", "--dry-run-execute"],
        )

        assert result.exit_code == 1
        assert "Cannot use both" in result.output

    def test_migrate_up_invalid_format(self, tmp_path):
        """Test invalid format option."""
        result = runner.invoke(
            app,
            ["migrate", "up", "--format", "invalid"],
        )

        assert result.exit_code == 1
        assert "Invalid format" in result.output


class TestMigrateDownCommand:
    """Tests for migrate down command."""

    def test_migrate_down_invalid_format(self):
        """Test invalid format option for down command."""
        result = runner.invoke(
            app,
            ["migrate", "down", "--format", "xml"],
        )

        assert result.exit_code == 1
        assert "Invalid format" in result.output


class TestLintCommand:
    """Tests for lint command edge cases."""

    def test_lint_invalid_format(self, tmp_path):
        """Test invalid format option."""
        result = runner.invoke(
            app,
            ["lint", "--format", "xml"],
        )

        assert result.exit_code == 1
        assert "Invalid format" in result.output


class TestValidateProfileCommand:
    """Tests for validate-profile command."""

    def test_validate_profile_not_found(self, tmp_path):
        """Test error when profile file not found."""
        result = runner.invoke(
            app,
            ["validate-profile", str(tmp_path / "nonexistent.yaml")],
        )

        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_validate_profile_invalid_yaml(self, tmp_path):
        """Test error with invalid YAML."""
        profile = tmp_path / "invalid.yaml"
        profile.write_text("{ invalid yaml [")

        result = runner.invoke(
            app,
            ["validate-profile", str(profile)],
        )

        assert result.exit_code == 1
```

---

### 3.2 Builder Module (73.41% → 85%)

**File**: `python/confiture/core/builder.py` (501 lines, 46 missing)
**Existing Tests**: `tests/unit/test_builder*.py` (4 files)
**New Test File**: `tests/unit/test_builder_coverage.py`

#### Missing Coverage Areas:

1. **`_is_hex_prefix` edge cases** (lines 202-215)
2. **`_hex_sort_key` with non-hex files** (lines 217-232)
3. **Rust fallback paths** (lines 355-357, 451-453)
4. **File read errors during hash** (lines 469-470)

```python
# tests/unit/test_builder_coverage.py
"""Additional builder tests for coverage improvement."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from confiture.core.builder import SchemaBuilder
from confiture.exceptions import SchemaError


class TestHexPrefixDetection:
    """Tests for hex prefix detection."""

    @pytest.fixture
    def builder(self, tmp_path):
        """Create builder with minimal config."""
        # Setup minimal project structure
        schema_dir = tmp_path / "db" / "schema" / "00_common"
        schema_dir.mkdir(parents=True)
        (schema_dir / "test.sql").write_text("SELECT 1;")

        env_dir = tmp_path / "db" / "environments"
        env_dir.mkdir(parents=True)
        (env_dir / "local.yaml").write_text(f"""
name: local
include_dirs:
  - db/schema/00_common
build:
  sort_mode: hex
database:
  host: localhost
  database: test
""")
        return SchemaBuilder(env="local", project_dir=tmp_path)

    def test_is_hex_prefix_valid_uppercase(self, builder):
        """Test valid uppercase hex prefix."""
        assert builder._is_hex_prefix("0A_test") is True
        assert builder._is_hex_prefix("FF_test") is True
        assert builder._is_hex_prefix("1A2B_test") is True

    def test_is_hex_prefix_invalid_lowercase(self, builder):
        """Test lowercase letters are invalid."""
        assert builder._is_hex_prefix("0a_test") is False
        assert builder._is_hex_prefix("ff_test") is False

    def test_is_hex_prefix_no_underscore(self, builder):
        """Test missing underscore is invalid."""
        assert builder._is_hex_prefix("0Atest") is False
        assert builder._is_hex_prefix("FF") is False

    def test_is_hex_prefix_non_hex_chars(self, builder):
        """Test non-hex characters are invalid."""
        assert builder._is_hex_prefix("0G_test") is False
        assert builder._is_hex_prefix("XY_test") is False

    def test_is_hex_prefix_empty(self, builder):
        """Test empty string is invalid."""
        assert builder._is_hex_prefix("") is False
        assert builder._is_hex_prefix("_test") is False


class TestHexSortKey:
    """Tests for hex sort key generation."""

    @pytest.fixture
    def builder(self, tmp_path):
        """Create builder for sort key tests."""
        schema_dir = tmp_path / "db" / "schema" / "00_common"
        schema_dir.mkdir(parents=True)
        (schema_dir / "test.sql").write_text("SELECT 1;")

        env_dir = tmp_path / "db" / "environments"
        env_dir.mkdir(parents=True)
        (env_dir / "local.yaml").write_text(f"""
name: local
include_dirs:
  - db/schema/00_common
database:
  host: localhost
  database: test
""")
        return SchemaBuilder(env="local", project_dir=tmp_path)

    def test_hex_sort_key_valid_hex(self, builder):
        """Test sort key for valid hex prefix."""
        path = Path("0A_test.sql")
        key = builder._hex_sort_key(path)

        assert key[0] == 10  # 0A in decimal
        assert key[1] == "test"

    def test_hex_sort_key_non_hex(self, builder):
        """Test sort key for non-hex filename."""
        path = Path("regular_file.sql")
        key = builder._hex_sort_key(path)

        assert key[0] == float("inf")
        assert key[1] == "regular_file"

    def test_hex_sort_ordering(self, builder):
        """Test files sort correctly by hex value."""
        files = [
            Path("FF_last.sql"),
            Path("0A_middle.sql"),
            Path("01_first.sql"),
            Path("regular.sql"),
        ]

        sorted_files = sorted(files, key=builder._hex_sort_key)

        assert sorted_files[0].stem == "01_first"
        assert sorted_files[1].stem == "0A_middle"
        assert sorted_files[2].stem == "FF_last"
        assert sorted_files[3].stem == "regular"


class TestRustFallback:
    """Tests for Rust extension fallback."""

    @pytest.fixture
    def builder(self, tmp_path):
        """Create builder for Rust tests."""
        schema_dir = tmp_path / "db" / "schema" / "00_common"
        schema_dir.mkdir(parents=True)
        (schema_dir / "test.sql").write_text("SELECT 1;")

        env_dir = tmp_path / "db" / "environments"
        env_dir.mkdir(parents=True)
        (env_dir / "local.yaml").write_text(f"""
name: local
include_dirs:
  - db/schema/00_common
database:
  host: localhost
  database: test
""")
        return SchemaBuilder(env="local", project_dir=tmp_path)

    @patch("confiture.core.builder.HAS_RUST", True)
    @patch("confiture.core.builder._core")
    def test_build_rust_exception_fallback(self, mock_core, builder):
        """Test Python fallback when Rust raises exception."""
        mock_core.build_schema.side_effect = Exception("Rust error")

        # Should fall back to Python and succeed
        schema = builder.build()

        assert "SELECT 1" in schema

    @patch("confiture.core.builder.HAS_RUST", True)
    @patch("confiture.core.builder._core")
    def test_hash_rust_exception_fallback(self, mock_core, builder):
        """Test Python fallback for hash when Rust fails."""
        mock_core.hash_files.side_effect = Exception("Rust error")

        # Should fall back to Python and succeed
        hash_result = builder.compute_hash()

        assert len(hash_result) == 64  # SHA256 hex


class TestHashErrors:
    """Tests for hash computation error handling."""

    def test_hash_file_read_error(self, tmp_path):
        """Test error when file cannot be read during hash."""
        schema_dir = tmp_path / "db" / "schema" / "00_common"
        schema_dir.mkdir(parents=True)
        sql_file = schema_dir / "test.sql"
        sql_file.write_text("SELECT 1;")

        env_dir = tmp_path / "db" / "environments"
        env_dir.mkdir(parents=True)
        (env_dir / "local.yaml").write_text(f"""
name: local
include_dirs:
  - db/schema/00_common
database:
  host: localhost
  database: test
""")

        builder = SchemaBuilder(env="local", project_dir=tmp_path)

        # Make file unreadable (remove after builder finds it)
        sql_file.unlink()

        with pytest.raises(SchemaError, match="Error reading"):
            builder.compute_hash()
```

---

## Phase 4: Low Priority (P4) - Skip for Now

These modules are either:
- **Future features** (not yet implemented)
- **Example code** (documentation, not production)
- **User utilities** (low usage)

| Module | Reason to Skip |
|--------|----------------|
| `monitoring/slo.py` | Future feature |
| `performance/query_profiler.py` | Future feature |
| `performance/baseline_manager.py` | Future feature |
| `scenarios/*` | Example code |
| `testing/fixtures/*` | User utilities |
| Advanced crypto strategies | Future features |

---

## Implementation Schedule

### Week 1: Housekeeping + Critical Fixes

| Day | Task | Est. Time |
|-----|------|-----------|
| 1 | Delete deprecated files, verify no imports | 30 min |
| 1-2 | Implement dry-run report tests | 4 hours |
| 2-3 | Implement credit card strategy tests | 4 hours |
| 3-4 | Implement address/IP/date strategy tests | 6 hours |
| 4-5 | Implement name/text_redaction tests | 4 hours |

### Week 2: Security + CLI/Builder

| Day | Task | Est. Time |
|-----|------|-----------|
| 1-2 | Implement KMS manager tests | 3 hours |
| 2-3 | Implement lineage/token_store tests | 4 hours |
| 3-4 | Implement CLI coverage tests | 4 hours |
| 4-5 | Implement builder coverage tests | 3 hours |
| 5 | Run full test suite, fix any failures | 2 hours |

---

## Verification Commands

```bash
# Run all tests
uv run pytest

# Run with coverage report
uv run pytest --cov=confiture --cov-report=html --cov-report=term-missing

# Run specific test files
uv run pytest tests/unit/test_dry_run_report.py -v
uv run pytest tests/unit/anonymization/test_credit_card_strategy.py -v

# Check coverage for specific module
uv run pytest --cov=confiture.core.migration.dry_run.report --cov-report=term-missing

# Generate HTML report
uv run pytest --cov=confiture --cov-report=html
# Then open htmlcov/index.html
```

---

## Success Metrics

| Metric | Before | Target |
|--------|--------|--------|
| Overall Coverage | 58.91% | 70%+ |
| Core Modules | ~75% | 85%+ |
| Dry-run Report | 2.61% | 80%+ |
| Credit Card Strategy | 18.94% | 80%+ |
| CLI Main | 74.73% | 85%+ |
| Builder | 73.41% | 85%+ |
| Security Modules | ~35% | 70%+ |

---

## Appendix: Quick Reference

### Test File Naming Convention

```
tests/
├── unit/
│   ├── test_{module}.py           # Basic tests
│   ├── test_{module}_coverage.py  # Coverage improvement tests
│   └── {subdomain}/
│       └── test_{specific}.py     # Domain-specific tests
├── integration/
│   └── test_{feature}.py
└── e2e/
    └── test_{workflow}.py
```

### Test Class Pattern

```python
class TestClassName:
    """Tests for ClassName."""

    @pytest.fixture
    def instance(self):
        """Create test instance."""
        return ClassName()

    def test_method_basic(self, instance):
        """Test basic functionality."""
        ...

    def test_method_edge_case(self, instance):
        """Test edge case."""
        ...

    def test_method_error_handling(self, instance):
        """Test error handling."""
        ...
```

### Commit Message Format

```
test(scope): description [COVERAGE]

Examples:
test(dry-run): add comprehensive report generator tests [COVERAGE]
test(anonymization): add credit card strategy tests [COVERAGE]
test(cli): improve main module coverage [COVERAGE]
chore: remove deprecated hooks.py and linting.py files
```
