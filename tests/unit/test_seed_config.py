"""Tests for SeedConfig model.

Phase 9, Cycle 1: RED - Test SeedConfig defaults
"""

from confiture.config.environment import SeedConfig


def test_seed_config_defaults():
    """Test SeedConfig with default values."""
    config = SeedConfig()
    assert config.execution_mode == "concatenate"
    assert config.continue_on_error is False
    assert config.transaction_mode == "savepoint"


def test_seed_config_sequential_mode():
    """Test SeedConfig with sequential execution mode."""
    config = SeedConfig(execution_mode="sequential")
    assert config.execution_mode == "sequential"
    assert config.continue_on_error is False
    assert config.transaction_mode == "savepoint"


def test_seed_config_continue_on_error():
    """Test SeedConfig with continue_on_error enabled."""
    config = SeedConfig(continue_on_error=True)
    assert config.execution_mode == "concatenate"
    assert config.continue_on_error is True
    assert config.transaction_mode == "savepoint"


def test_seed_config_custom_mode():
    """Test SeedConfig with custom values."""
    config = SeedConfig(
        execution_mode="sequential",
        continue_on_error=True,
        transaction_mode="savepoint",
    )
    assert config.execution_mode == "sequential"
    assert config.continue_on_error is True
    assert config.transaction_mode == "savepoint"


def test_seed_config_is_pydantic_model():
    """Test that SeedConfig is a Pydantic model."""
    config = SeedConfig()
    # Pydantic models have model_dump() method
    assert hasattr(config, "model_dump")
    dumped = config.model_dump()
    assert dumped["execution_mode"] == "concatenate"
    assert dumped["continue_on_error"] is False
    assert dumped["transaction_mode"] == "savepoint"
