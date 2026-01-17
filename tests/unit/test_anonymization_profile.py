"""Tests for AnonymizationProfile YAML security and schema validation.

Tests cover:
- YAML injection prevention (using safe_load)
- Strategy type whitelist enforcement
- Pydantic schema validation
- Profile loading and structure validation
- Seed resolution with proper precedence
"""

import tempfile

import pytest
import yaml

from confiture.core.anonymization.profile import (
    AnonymizationProfile,
    AnonymizationRule,
    StrategyDefinition,
    StrategyType,
    TableDefinition,
    resolve_seed_for_column,
)


class TestStrategyTypeWhitelist:
    """Test that only whitelisted strategy types are allowed."""

    def test_strategy_type_values(self):
        """StrategyType enum has expected values."""
        assert StrategyType.HASH.value == "hash"
        assert StrategyType.EMAIL.value == "email"
        assert StrategyType.PHONE.value == "phone"
        assert StrategyType.REDACT.value == "redact"

    def test_strategy_type_count(self):
        """Only 4 strategies in whitelist."""
        assert len(StrategyType) == 4


class TestStrategyDefinitionValidation:
    """Test Pydantic validation of strategy definitions."""

    def test_valid_strategy_definition(self):
        """Valid strategy definition accepts type in whitelist."""
        strategy = StrategyDefinition(type="email")
        assert strategy.type == "email"
        assert strategy.config is None

    def test_strategy_with_config(self):
        """Strategy definition accepts optional config."""
        strategy = StrategyDefinition(type="hash", config={"algorithm": "sha256", "length": 16})
        assert strategy.config["algorithm"] == "sha256"
        assert strategy.config["length"] == 16

    def test_strategy_with_seed_env_var(self):
        """Strategy definition accepts seed_env_var."""
        strategy = StrategyDefinition(type="email", seed_env_var="MY_SEED")
        assert strategy.seed_env_var == "MY_SEED"

    def test_invalid_strategy_type_rejected(self):
        """Invalid strategy type is rejected with clear error."""
        with pytest.raises(ValueError) as exc_info:
            StrategyDefinition(type="unknown_strategy")
        assert "not allowed" in str(exc_info.value)
        assert "unknown_strategy" in str(exc_info.value)

    def test_all_whitelisted_types_accepted(self):
        """All whitelisted types are accepted."""
        for strategy_type in StrategyType:
            strategy = StrategyDefinition(type=strategy_type.value)
            assert strategy.type == strategy_type.value

    def test_case_sensitive_strategy_types(self):
        """Strategy types are case-sensitive."""
        with pytest.raises(ValueError):
            StrategyDefinition(type="HASH")  # Must be lowercase

        with pytest.raises(ValueError):
            StrategyDefinition(type="Email")  # Must be lowercase


class TestAnonymizationRuleValidation:
    """Test Pydantic validation of anonymization rules."""

    def test_minimal_rule(self):
        """Minimal rule with required fields."""
        rule = AnonymizationRule(column="email", strategy="email")
        assert rule.column == "email"
        assert rule.strategy == "email"
        assert rule.seed is None
        assert rule.options is None

    def test_rule_with_seed(self):
        """Rule with column-specific seed."""
        rule = AnonymizationRule(column="email", strategy="email", seed=12345)
        assert rule.seed == 12345

    def test_rule_with_options(self):
        """Rule with strategy-specific options."""
        rule = AnonymizationRule(
            column="email", strategy="email", options={"preserve_domain": True}
        )
        assert rule.options["preserve_domain"] is True

    def test_rule_missing_required_field(self):
        """Rule without required field raises ValueError."""
        with pytest.raises(ValueError):
            AnonymizationRule(column="email")  # Missing strategy

        with pytest.raises(ValueError):
            AnonymizationRule(strategy="email")  # Missing column


class TestAnonymizationProfileValidation:
    """Test Pydantic validation of AnonymizationProfile."""

    def test_minimal_valid_profile(self):
        """Minimal valid profile with required fields."""
        profile = AnonymizationProfile(
            name="test",
            version="1.0",
            strategies={},
            tables={},
        )
        assert profile.name == "test"
        assert profile.version == "1.0"
        assert profile.global_seed is None

    def test_profile_with_global_seed(self):
        """Profile with global_seed for consistency."""
        profile = AnonymizationProfile(
            name="test",
            version="1.0",
            global_seed=12345,
            strategies={},
            tables={},
        )
        assert profile.global_seed == 12345

    def test_profile_with_strategies(self):
        """Profile with multiple strategies."""
        profile = AnonymizationProfile(
            name="test",
            version="1.0",
            strategies={
                "email_mask": StrategyDefinition(type="email"),
                "phone_mask": StrategyDefinition(type="phone"),
                "hash": StrategyDefinition(type="hash"),
            },
            tables={},
        )
        assert len(profile.strategies) == 3
        assert "email_mask" in profile.strategies

    def test_profile_with_tables(self):
        """Profile with table definitions."""
        profile = AnonymizationProfile(
            name="test",
            version="1.0",
            strategies={"email": StrategyDefinition(type="email")},
            tables={
                "users": TableDefinition(
                    rules=[AnonymizationRule(column="email", strategy="email")]
                )
            },
        )
        assert "users" in profile.tables
        assert len(profile.tables["users"].rules) == 1

    def test_profile_missing_required_field(self):
        """Profile without required field raises ValueError."""
        with pytest.raises(ValueError):
            AnonymizationProfile(version="1.0", strategies={}, tables={})  # Missing name

    def test_profile_from_dict(self):
        """Create profile from dictionary."""
        data = {
            "name": "production",
            "version": "1.0",
            "global_seed": 12345,
            "strategies": {"email": {"type": "email"}},
            "tables": {"users": {"rules": [{"column": "email", "strategy": "email"}]}},
        }
        profile = AnonymizationProfile.from_dict(data)
        assert profile.name == "production"
        assert profile.global_seed == 12345


class TestYAMLSafeLoading:
    """Test that YAML safe_load prevents injection attacks."""

    def test_yaml_injection_prevented(self):
        """YAML injection attack with !!python/object is prevented."""
        # This is a classic YAML injection attack that would execute code with yaml.load()
        malicious_yaml = """
strategies:
  evil:
    type: !!python/object/apply:os.system
    args: ['rm -rf /']
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(malicious_yaml)
            f.flush()

            # With yaml.safe_load, this should fail with a safety error
            with pytest.raises((ValueError, yaml.constructor.ConstructorError)):
                AnonymizationProfile.load(f.name)

    def test_yaml_object_constructor_blocked(self):
        """YAML object constructor !!python/object is blocked."""
        malicious_yaml = """
name: test
version: "1.0"
strategies:
  bad:
    type: !!python/object:subprocess.Popen
    args: [['touch', '/tmp/pwned']]
tables: {}
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(malicious_yaml)
            f.flush()

            # Should fail with constructor error
            with pytest.raises((ValueError, yaml.constructor.ConstructorError)):
                AnonymizationProfile.load(f.name)

    def test_valid_yaml_still_loads(self):
        """Valid YAML loads correctly."""
        valid_yaml = """
name: production
version: "1.0"
global_seed: 12345
strategies:
  email:
    type: email
  hash:
    type: hash
    config:
      algorithm: sha256
      length: 16
tables:
  users:
    rules:
      - column: email
        strategy: email
      - column: phone
        strategy: hash
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(valid_yaml)
            f.flush()

            profile = AnonymizationProfile.load(f.name)
            assert profile.name == "production"
            assert profile.version == "1.0"
            assert profile.global_seed == 12345
            assert "email" in profile.strategies
            assert "users" in profile.tables


class TestProfileLoading:
    """Test loading profiles from YAML files."""

    def test_load_minimal_profile(self):
        """Load minimal valid profile."""
        yaml_content = """
name: test
version: "1.0"
strategies: {}
tables: {}
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()

            profile = AnonymizationProfile.load(f.name)
            assert profile.name == "test"
            assert profile.version == "1.0"

    def test_load_complete_profile(self):
        """Load complete profile with all features."""
        yaml_content = """
name: production
version: "1.0"
global_seed: 12345
strategies:
  email_mask:
    type: email
    seed_env_var: ANONYMIZATION_SEED
  phone_mask:
    type: phone
  hash:
    type: hash
    config:
      algorithm: sha256
      length: 16
  redact:
    type: redact
    config:
      replacement: "[REDACTED]"
tables:
  users:
    rules:
      - column: email
        strategy: email_mask
      - column: phone
        strategy: phone_mask
        seed: 99999
      - column: internal_id
        strategy: hash
  orders:
    rules:
      - column: user_email
        strategy: email_mask
      - column: notes
        strategy: redact
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()

            profile = AnonymizationProfile.load(f.name)
            assert profile.name == "production"
            assert profile.global_seed == 12345
            assert len(profile.strategies) == 4
            assert len(profile.tables) == 2
            assert len(profile.tables["users"].rules) == 3

    def test_load_file_not_found(self):
        """Loading non-existent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            AnonymizationProfile.load("/nonexistent/path/profile.yaml")

    def test_load_malformed_yaml(self):
        """Loading malformed YAML raises ValueError."""
        yaml_content = """
name: test
version: "1.0"
strategies:
  - this is not valid YAML
  - structure: [
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()

            with pytest.raises(ValueError):
                AnonymizationProfile.load(f.name)

    def test_load_empty_yaml(self):
        """Loading empty YAML raises ValueError."""
        yaml_content = ""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()

            with pytest.raises(ValueError):
                AnonymizationProfile.load(f.name)

    def test_load_yaml_with_comments(self):
        """YAML with comments loads correctly."""
        yaml_content = """
# Production anonymization profile
name: production
version: "1.0"
# Global seed for all columns
global_seed: 12345
# Strategy definitions
strategies:
  email_mask:
    type: email  # Email masking strategy
# Table rules
tables:
  users:
    rules:
      - column: email
        strategy: email_mask
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()

            profile = AnonymizationProfile.load(f.name)
            assert profile.name == "production"


class TestSeedResolution:
    """Test seed resolution with proper precedence."""

    def test_column_specific_seed_wins(self):
        """Column-specific seed takes precedence over global_seed."""
        profile = AnonymizationProfile(
            name="test",
            version="1.0",
            global_seed=12345,
            strategies={},
            tables={},
        )
        rule = AnonymizationRule(column="email", strategy="email", seed=99999)

        resolved = resolve_seed_for_column(rule, profile)
        assert resolved == 99999  # Not 12345

    def test_global_seed_applies_to_column(self):
        """Global seed applies when column-specific seed not set."""
        profile = AnonymizationProfile(
            name="test",
            version="1.0",
            global_seed=12345,
            strategies={},
            tables={},
        )
        rule = AnonymizationRule(column="email", strategy="email")

        resolved = resolve_seed_for_column(rule, profile)
        assert resolved == 12345

    def test_default_seed_when_no_global(self):
        """Default seed (0) when no global or column-specific seed."""
        profile = AnonymizationProfile(
            name="test",
            version="1.0",
            strategies={},
            tables={},
        )
        rule = AnonymizationRule(column="email", strategy="email")

        resolved = resolve_seed_for_column(rule, profile)
        assert resolved == 0

    def test_foreign_key_consistency(self):
        """Same PII values hash to same output with global_seed."""
        profile = AnonymizationProfile(
            name="test",
            version="1.0",
            global_seed=12345,
            strategies={},
            tables={},
        )

        # Email in users table
        users_rule = AnonymizationRule(column="email", strategy="email")
        # Email in orders table (different name, same purpose)
        orders_rule = AnonymizationRule(column="user_email", strategy="email")

        # Both should resolve to same seed
        users_seed = resolve_seed_for_column(users_rule, profile)
        orders_seed = resolve_seed_for_column(orders_rule, profile)

        assert users_seed == 12345
        assert orders_seed == 12345
        assert users_seed == orders_seed

    def test_column_override_breaks_consistency(self):
        """Column-specific seed overrides global for intentional differentiation."""
        profile = AnonymizationProfile(
            name="test",
            version="1.0",
            global_seed=12345,
            strategies={},
            tables={},
        )

        # Same column name in different tables
        rule1 = AnonymizationRule(column="email", strategy="email")  # Uses global
        rule2 = AnonymizationRule(
            column="email", strategy="email", seed=99999
        )  # Uses column-specific

        seed1 = resolve_seed_for_column(rule1, profile)
        seed2 = resolve_seed_for_column(rule2, profile)

        assert seed1 == 12345
        assert seed2 == 99999
        assert seed1 != seed2


class TestStrategyTypeValidationEdgeCases:
    """Test edge cases in strategy type validation."""

    def test_empty_strategy_type_rejected(self):
        """Empty strategy type is rejected."""
        with pytest.raises(ValueError):
            StrategyDefinition(type="")

    def test_whitespace_strategy_type_rejected(self):
        """Strategy type with only whitespace is rejected."""
        with pytest.raises(ValueError):
            StrategyDefinition(type="   ")

    def test_strategy_type_with_spaces_rejected(self):
        """Strategy type with spaces is rejected."""
        with pytest.raises(ValueError):
            StrategyDefinition(type="email mask")

    def test_similar_strategy_name_rejected(self):
        """Similar but different strategy name is rejected."""
        with pytest.raises(ValueError):
            StrategyDefinition(type="emails")  # Should be 'email'

        with pytest.raises(ValueError):
            StrategyDefinition(type="hashing")  # Should be 'hash'


class TestComplexScenarios:
    """Test complex real-world scenarios."""

    def test_multiple_tables_same_strategy(self):
        """Multiple tables using same strategy with global seed."""
        yaml_content = """
name: production
version: "1.0"
global_seed: 12345
strategies:
  email:
    type: email
  phone:
    type: phone
tables:
  users:
    rules:
      - column: email
        strategy: email
      - column: phone
        strategy: phone
  customers:
    rules:
      - column: email_address
        strategy: email
      - column: phone_number
        strategy: phone
  contacts:
    rules:
      - column: email
        strategy: email
      - column: phone
        strategy: phone
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()

            profile = AnonymizationProfile.load(f.name)
            assert len(profile.tables) == 3
            # All tables should have consistent seeds for foreign key integrity
            for table_rules in profile.tables.values():
                for rule in table_rules.rules:
                    seed = resolve_seed_for_column(rule, profile)
                    assert seed == 12345

    def test_mixed_seeds_different_strategies(self):
        """Profile with global seed + column overrides in different strategies."""
        yaml_content = """
name: production
version: "1.0"
global_seed: 12345
strategies:
  email:
    type: email
  hash:
    type: hash
  redact:
    type: redact
tables:
  users:
    rules:
      - column: email
        strategy: email
      - column: internal_id
        strategy: hash
      - column: ssn
        strategy: redact
      - column: special_code
        strategy: hash
        seed: 99999
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()

            profile = AnonymizationProfile.load(f.name)
            rules = profile.tables["users"].rules

            # email, internal_id, ssn should use global seed
            assert resolve_seed_for_column(rules[0], profile) == 12345
            assert resolve_seed_for_column(rules[1], profile) == 12345
            assert resolve_seed_for_column(rules[2], profile) == 12345

            # special_code has column-specific seed
            assert resolve_seed_for_column(rules[3], profile) == 99999
