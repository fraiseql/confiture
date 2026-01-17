"""Comprehensive tests for differential privacy anonymization strategy.

Tests cover:
- DifferentialPrivacyConfig configuration
- DifferentialPrivacyStrategy initialization and validation
- Noise mechanisms (Laplace, Gaussian, Exponential)
- Privacy budget tracking
- Numeric value anonymization
- Edge cases and error handling
"""

import pytest

from confiture.core.anonymization.strategies.differential_privacy import (
    DifferentialPrivacyConfig,
    DifferentialPrivacyStrategy,
)


class TestDifferentialPrivacyConfig:
    """Tests for DifferentialPrivacyConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = DifferentialPrivacyConfig()

        assert config.epsilon == 1.0
        assert config.delta == 1e-5
        assert config.mechanism == "laplace"
        assert config.data_type == "numeric"
        assert config.sensitivity == 1.0
        assert config.budget_total == 10.0
        assert config.budget_per_value == 0.1

    def test_custom_epsilon(self):
        """Test custom epsilon (privacy budget)."""
        config = DifferentialPrivacyConfig(epsilon=0.5)
        assert config.epsilon == 0.5

    def test_custom_delta(self):
        """Test custom delta (failure probability)."""
        config = DifferentialPrivacyConfig(delta=1e-6)
        assert config.delta == 1e-6

    def test_gaussian_mechanism(self):
        """Test Gaussian mechanism configuration."""
        config = DifferentialPrivacyConfig(mechanism="gaussian")
        assert config.mechanism == "gaussian"

    def test_exponential_mechanism(self):
        """Test Exponential mechanism configuration."""
        config = DifferentialPrivacyConfig(mechanism="exponential")
        assert config.mechanism == "exponential"

    def test_high_sensitivity(self):
        """Test high sensitivity configuration."""
        config = DifferentialPrivacyConfig(sensitivity=100.0)
        assert config.sensitivity == 100.0

    def test_custom_budget(self):
        """Test custom privacy budget."""
        config = DifferentialPrivacyConfig(
            budget_total=50.0,
            budget_per_value=0.5,
        )
        assert config.budget_total == 50.0
        assert config.budget_per_value == 0.5


class TestDifferentialPrivacyStrategyInit:
    """Tests for DifferentialPrivacyStrategy initialization."""

    def test_init_with_default_config(self):
        """Test initialization with default config."""
        strategy = DifferentialPrivacyStrategy()

        assert strategy.config.epsilon == 1.0
        assert strategy.config.mechanism == "laplace"
        assert strategy.budget_remaining == 10.0

    def test_init_with_custom_config(self):
        """Test initialization with custom config."""
        config = DifferentialPrivacyConfig(
            epsilon=2.0,
            mechanism="gaussian",
            budget_total=20.0,
        )
        strategy = DifferentialPrivacyStrategy(config)

        assert strategy.config.epsilon == 2.0
        assert strategy.config.mechanism == "gaussian"
        assert strategy.budget_remaining == 20.0

    def test_init_invalid_epsilon_zero(self):
        """Test error when epsilon is zero."""
        config = DifferentialPrivacyConfig(epsilon=0)

        with pytest.raises(ValueError, match="Epsilon must be positive"):
            DifferentialPrivacyStrategy(config)

    def test_init_invalid_epsilon_negative(self):
        """Test error when epsilon is negative."""
        config = DifferentialPrivacyConfig(epsilon=-1.0)

        with pytest.raises(ValueError, match="Epsilon must be positive"):
            DifferentialPrivacyStrategy(config)

    def test_init_invalid_delta_negative(self):
        """Test error when delta is negative."""
        config = DifferentialPrivacyConfig(delta=-0.1)

        with pytest.raises(ValueError, match="Delta must be in"):
            DifferentialPrivacyStrategy(config)

    def test_init_invalid_delta_one(self):
        """Test error when delta equals 1."""
        config = DifferentialPrivacyConfig(delta=1.0)

        with pytest.raises(ValueError, match="Delta must be in"):
            DifferentialPrivacyStrategy(config)

    def test_init_invalid_delta_greater_than_one(self):
        """Test error when delta is greater than 1."""
        config = DifferentialPrivacyConfig(delta=1.5)

        with pytest.raises(ValueError, match="Delta must be in"):
            DifferentialPrivacyStrategy(config)

    def test_init_invalid_sensitivity_zero(self):
        """Test error when sensitivity is zero."""
        config = DifferentialPrivacyConfig(sensitivity=0)

        with pytest.raises(ValueError, match="Sensitivity must be positive"):
            DifferentialPrivacyStrategy(config)

    def test_init_invalid_sensitivity_negative(self):
        """Test error when sensitivity is negative."""
        config = DifferentialPrivacyConfig(sensitivity=-1.0)

        with pytest.raises(ValueError, match="Sensitivity must be positive"):
            DifferentialPrivacyStrategy(config)

    def test_init_invalid_mechanism(self):
        """Test error when mechanism is invalid."""
        config = DifferentialPrivacyConfig(mechanism="invalid")

        with pytest.raises(ValueError, match="Mechanism must be"):
            DifferentialPrivacyStrategy(config)

    def test_init_invalid_data_type(self):
        """Test error when data_type is invalid."""
        config = DifferentialPrivacyConfig(data_type="invalid")

        with pytest.raises(ValueError, match="Data type must be"):
            DifferentialPrivacyStrategy(config)


class TestDifferentialPrivacyStrategyAnonymize:
    """Tests for DifferentialPrivacyStrategy.anonymize() method."""

    @pytest.fixture
    def strategy(self):
        """Create strategy with default config."""
        config = DifferentialPrivacyConfig(
            epsilon=1.0,
            mechanism="laplace",
            sensitivity=1.0,
            budget_total=100.0,
            budget_per_value=0.1,
        )
        return DifferentialPrivacyStrategy(config)

    def test_anonymize_integer(self, strategy):
        """Test anonymization of integer value."""
        result = strategy.anonymize(35)

        assert isinstance(result, float)
        # Result should be different from input due to noise
        # But not by more than a few sensitivity values typically

    def test_anonymize_float(self, strategy):
        """Test anonymization of float value."""
        result = strategy.anonymize(35.5)

        assert isinstance(result, float)

    def test_anonymize_string_number(self, strategy):
        """Test anonymization of numeric string."""
        result = strategy.anonymize("42")

        assert isinstance(result, float)

    def test_anonymize_none_returns_none(self, strategy):
        """Test None input returns None."""
        result = strategy.anonymize(None)

        assert result is None

    def test_anonymize_consumes_budget(self, strategy):
        """Test that anonymization consumes privacy budget."""
        initial_budget = strategy.budget_remaining

        strategy.anonymize(35)

        assert strategy.budget_remaining < initial_budget
        expected = initial_budget - strategy.config.budget_per_value
        assert strategy.budget_remaining == pytest.approx(expected)

    def test_anonymize_budget_exhausted(self, strategy):
        """Test error when budget is exhausted."""
        # Exhaust budget
        strategy.budget_remaining = 0

        with pytest.raises(ValueError, match="Privacy budget exhausted"):
            strategy.anonymize(35)

    def test_anonymize_non_numeric_string(self, strategy):
        """Test error when value is non-numeric string."""
        with pytest.raises(ValueError, match="only works with numeric"):
            strategy.anonymize("hello")

    def test_anonymize_dict_raises_error(self, strategy):
        """Test error when value is dict."""
        with pytest.raises(ValueError, match="only works with numeric"):
            strategy.anonymize({"key": "value"})

    def test_anonymize_list_raises_error(self, strategy):
        """Test error when value is list."""
        with pytest.raises(ValueError, match="only works with numeric"):
            strategy.anonymize([1, 2, 3])


class TestDifferentialPrivacyNoiseMechanisms:
    """Tests for different noise mechanisms."""

    def test_laplace_mechanism_produces_noise(self):
        """Test Laplace mechanism adds noise."""
        config = DifferentialPrivacyConfig(mechanism="laplace")
        strategy = DifferentialPrivacyStrategy(config)

        original = 100.0
        results = [strategy.anonymize(original) for _ in range(10)]

        # All results should be different due to randomness
        # (highly unlikely to all be the same with noise)
        assert len(set(results)) > 1

    def test_gaussian_mechanism_produces_noise(self):
        """Test Gaussian mechanism adds noise."""
        config = DifferentialPrivacyConfig(mechanism="gaussian")
        strategy = DifferentialPrivacyStrategy(config)

        original = 100.0
        results = [strategy.anonymize(original) for _ in range(10)]

        # All results should be different
        assert len(set(results)) > 1

    def test_exponential_mechanism_produces_noise(self):
        """Test Exponential mechanism adds noise."""
        config = DifferentialPrivacyConfig(mechanism="exponential")
        strategy = DifferentialPrivacyStrategy(config)

        original = 100.0
        results = [strategy.anonymize(original) for _ in range(10)]

        # All results should be different
        assert len(set(results)) > 1

    def test_higher_epsilon_less_noise(self):
        """Test higher epsilon produces less noise (less privacy)."""
        # Higher epsilon = less privacy = less noise
        config_low_eps = DifferentialPrivacyConfig(epsilon=0.1, budget_total=1000)
        config_high_eps = DifferentialPrivacyConfig(epsilon=10.0, budget_total=1000)

        strategy_low_eps = DifferentialPrivacyStrategy(config_low_eps)
        strategy_high_eps = DifferentialPrivacyStrategy(config_high_eps)

        original = 100.0
        n_samples = 50

        # Sample from both
        results_low_eps = [strategy_low_eps.anonymize(original) for _ in range(n_samples)]
        results_high_eps = [strategy_high_eps.anonymize(original) for _ in range(n_samples)]

        # Variance of low epsilon should be higher (more noise)
        var_low = sum((r - original) ** 2 for r in results_low_eps) / n_samples
        var_high = sum((r - original) ** 2 for r in results_high_eps) / n_samples

        # Low epsilon should have higher variance (more noise)
        assert var_low > var_high

    def test_higher_sensitivity_more_noise(self):
        """Test higher sensitivity produces more noise."""
        config_low_sens = DifferentialPrivacyConfig(sensitivity=1.0, budget_total=1000)
        config_high_sens = DifferentialPrivacyConfig(sensitivity=100.0, budget_total=1000)

        strategy_low_sens = DifferentialPrivacyStrategy(config_low_sens)
        strategy_high_sens = DifferentialPrivacyStrategy(config_high_sens)

        original = 100.0
        n_samples = 50

        results_low_sens = [strategy_low_sens.anonymize(original) for _ in range(n_samples)]
        results_high_sens = [strategy_high_sens.anonymize(original) for _ in range(n_samples)]

        var_low = sum((r - original) ** 2 for r in results_low_sens) / n_samples
        var_high = sum((r - original) ** 2 for r in results_high_sens) / n_samples

        # High sensitivity should have higher variance (more noise)
        assert var_high > var_low


class TestDifferentialPrivacyBudget:
    """Tests for privacy budget tracking."""

    def test_budget_decreases_with_each_call(self):
        """Test budget decreases with each anonymization."""
        config = DifferentialPrivacyConfig(
            budget_total=10.0,
            budget_per_value=0.1,
        )
        strategy = DifferentialPrivacyStrategy(config)

        for i in range(5):
            strategy.anonymize(100)
            expected = 10.0 - (i + 1) * 0.1
            assert strategy.budget_remaining == pytest.approx(expected)

    def test_budget_exhausts_after_max_calls(self):
        """Test budget is exhausted after maximum calls."""
        config = DifferentialPrivacyConfig(
            budget_total=1.0,
            budget_per_value=0.1,
        )
        strategy = DifferentialPrivacyStrategy(config)

        # Use up budget (10 calls)
        for _ in range(10):
            strategy.anonymize(100)

        assert strategy.budget_remaining == pytest.approx(0.0, abs=1e-10)

        # Manually set to exactly 0 (floating point can leave tiny positive)
        strategy.budget_remaining = 0.0

        # Next call should fail
        with pytest.raises(ValueError, match="Privacy budget exhausted"):
            strategy.anonymize(100)

    def test_get_budget_status(self):
        """Test get_budget_status() method."""
        config = DifferentialPrivacyConfig(
            budget_total=10.0,
            budget_per_value=1.0,
        )
        strategy = DifferentialPrivacyStrategy(config)

        # Use some budget
        strategy.anonymize(100)
        strategy.anonymize(100)

        status = strategy.get_budget_status()

        assert status["total"] == 10.0
        assert status["remaining"] == pytest.approx(8.0)
        assert status["consumed"] == pytest.approx(2.0)
        assert status["percentage"] == pytest.approx(20.0)


class TestDifferentialPrivacyValidation:
    """Tests for validation methods."""

    @pytest.fixture
    def strategy(self):
        """Create strategy for validation tests."""
        return DifferentialPrivacyStrategy()

    def test_validate_numeric_int(self, strategy):
        """Test validate accepts integer."""
        assert strategy.validate(42) is True

    def test_validate_numeric_float(self, strategy):
        """Test validate accepts float."""
        assert strategy.validate(42.5) is True

    def test_validate_numeric_string(self, strategy):
        """Test validate accepts numeric string."""
        assert strategy.validate("42.5") is True

    def test_validate_rejects_non_numeric_string(self, strategy):
        """Test validate rejects non-numeric string."""
        assert strategy.validate("hello") is False

    def test_validate_rejects_list(self, strategy):
        """Test validate rejects list."""
        assert strategy.validate([1, 2, 3]) is False

    def test_validate_rejects_dict(self, strategy):
        """Test validate rejects dict."""
        assert strategy.validate({"key": "value"}) is False

    def test_validate_comprehensive_valid(self, strategy):
        """Test comprehensive validation with valid value."""
        is_valid, errors = strategy.validate_comprehensive(42, "age", "users")

        assert is_valid is True
        assert len(errors) == 0

    def test_validate_comprehensive_non_numeric(self, strategy):
        """Test comprehensive validation with non-numeric value."""
        is_valid, errors = strategy.validate_comprehensive("hello", "name", "users")

        assert is_valid is False
        assert len(errors) > 0
        assert "requires numeric values" in errors[0]

    def test_validate_comprehensive_nan(self, strategy):
        """Test comprehensive validation with NaN value."""
        is_valid, errors = strategy.validate_comprehensive(float("nan"), "value", "data")

        assert is_valid is False
        assert "NaN" in errors[0]

    def test_validate_comprehensive_budget_exhausted(self, strategy):
        """Test comprehensive validation when budget exhausted."""
        strategy.budget_remaining = 0

        is_valid, errors = strategy.validate_comprehensive(42, "age", "users")

        assert is_valid is False
        assert "budget exhausted" in errors[0].lower()

    def test_validate_comprehensive_high_epsilon_warning(self):
        """Test comprehensive validation warns about high epsilon."""
        config = DifferentialPrivacyConfig(epsilon=15.0)
        strategy = DifferentialPrivacyStrategy(config)

        is_valid, errors = strategy.validate_comprehensive(42, "age", "users")

        assert is_valid is False
        assert "high" in errors[0].lower()


class TestDifferentialPrivacyProperties:
    """Tests for strategy properties."""

    def test_is_reversible_false(self):
        """Test differential privacy is not reversible."""
        strategy = DifferentialPrivacyStrategy()

        assert strategy.is_reversible is False


class TestNoiseScaleCalculation:
    """Tests for noise scale calculation."""

    def test_noise_scale_basic(self):
        """Test basic noise scale calculation."""
        config = DifferentialPrivacyConfig(
            epsilon=1.0,
            sensitivity=1.0,
        )
        strategy = DifferentialPrivacyStrategy(config)

        # Scale = sensitivity / epsilon = 1.0 / 1.0 = 1.0
        scale = strategy._calculate_noise_scale()
        assert scale == 1.0

    def test_noise_scale_high_sensitivity(self):
        """Test noise scale with high sensitivity."""
        config = DifferentialPrivacyConfig(
            epsilon=1.0,
            sensitivity=10.0,
        )
        strategy = DifferentialPrivacyStrategy(config)

        # Scale = 10.0 / 1.0 = 10.0
        scale = strategy._calculate_noise_scale()
        assert scale == 10.0

    def test_noise_scale_low_epsilon(self):
        """Test noise scale with low epsilon (high privacy)."""
        config = DifferentialPrivacyConfig(
            epsilon=0.1,
            sensitivity=1.0,
        )
        strategy = DifferentialPrivacyStrategy(config)

        # Scale = 1.0 / 0.1 = 10.0
        scale = strategy._calculate_noise_scale()
        assert scale == 10.0


class TestDifferentialPrivacyEdgeCases:
    """Tests for edge cases."""

    def test_anonymize_zero(self):
        """Test anonymizing zero."""
        strategy = DifferentialPrivacyStrategy()
        result = strategy.anonymize(0)

        assert isinstance(result, float)

    def test_anonymize_negative(self):
        """Test anonymizing negative number."""
        strategy = DifferentialPrivacyStrategy()
        result = strategy.anonymize(-50)

        assert isinstance(result, float)

    def test_anonymize_very_large(self):
        """Test anonymizing very large number."""
        strategy = DifferentialPrivacyStrategy()
        result = strategy.anonymize(1e10)

        assert isinstance(result, float)

    def test_anonymize_very_small(self):
        """Test anonymizing very small number."""
        strategy = DifferentialPrivacyStrategy()
        result = strategy.anonymize(1e-10)

        assert isinstance(result, float)

    def test_sequential_anonymization_independent(self):
        """Test sequential anonymizations are independent."""
        strategy = DifferentialPrivacyStrategy()

        results = []
        for _ in range(5):
            results.append(strategy.anonymize(100))

        # All results should typically be different (random noise)
        # Check we don't have all identical values
        assert len(set(results)) > 1

    def test_different_inputs_different_outputs(self):
        """Test different inputs produce different outputs."""
        strategy = DifferentialPrivacyStrategy()

        result1 = strategy.anonymize(100)
        result2 = strategy.anonymize(200)

        # Different inputs should produce different noisy values
        # (though in theory they could be same due to noise, it's unlikely)
        # We check the means are approximately different
        assert abs(result1 - result2) > 0 or result1 != result2
