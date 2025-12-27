"""Tests for foreign key consistency with global_seed.

Tests verify that:
- Same PII values hash to same output across different tables
- Global seed provides consistent anonymization
- Column-specific seeds override global seed
- Proper seed precedence is maintained
"""

from confiture.core.anonymization.profile import (
    AnonymizationProfile,
    AnonymizationRule,
    StrategyDefinition,
    TableDefinition,
    resolve_seed_for_column,
)
from confiture.core.anonymization.strategies.email import (
    EmailMaskConfig,
    EmailMaskingStrategy,
)
from confiture.core.anonymization.strategies.hash import (
    DeterministicHashConfig,
    DeterministicHashStrategy,
)


class TestGlobalSeedConsistency:
    """Test that global_seed provides consistent hashing across tables."""

    def test_same_email_same_hash_in_different_tables(self):
        """Same email hashes to same value in different tables with global_seed."""
        # Create profile with global seed
        profile = AnonymizationProfile(
            name="production",
            version="1.0",
            global_seed=12345,
            strategies={
                "email_mask": StrategyDefinition(type="email"),
            },
            tables={
                "users": TableDefinition(
                    rules=[
                        AnonymizationRule(
                            column="email",
                            strategy="email_mask",
                        )
                    ]
                ),
                "orders": TableDefinition(
                    rules=[
                        AnonymizationRule(
                            column="user_email",
                            strategy="email_mask",
                        )
                    ]
                ),
            },
        )

        # Create strategy instances with same seed
        strategy = EmailMaskingStrategy(
            EmailMaskConfig(seed=profile.global_seed)
        )

        # Anonymize same email
        email = "john@example.com"
        hash1 = strategy.anonymize(email)

        # Anonymize again (should be deterministic)
        hash2 = strategy.anonymize(email)

        # Both should be identical
        assert hash1 == hash2
        # Both should have email format
        assert "@" in hash1
        assert "@" in hash2

    def test_different_emails_different_hashes_with_global_seed(self):
        """Different emails hash to different values with global_seed."""
        profile = AnonymizationProfile(
            name="production",
            version="1.0",
            global_seed=12345,
            strategies={
                "email_mask": StrategyDefinition(type="email"),
            },
            tables={},
        )

        strategy = EmailMaskingStrategy(
            EmailMaskConfig(seed=profile.global_seed)
        )

        hash1 = strategy.anonymize("john@example.com")
        hash2 = strategy.anonymize("jane@example.com")

        assert hash1 != hash2

    def test_hash_strategy_global_seed_consistency(self):
        """Hash strategy produces consistent output with global_seed."""
        profile = AnonymizationProfile(
            name="production",
            version="1.0",
            global_seed=54321,
            strategies={
                "hash": StrategyDefinition(
                    type="hash",
                    config={"algorithm": "sha256"},
                ),
            },
            tables={},
        )

        strategy = DeterministicHashStrategy(
            DeterministicHashConfig(seed=profile.global_seed, length=16)
        )

        # Same value should produce same hash
        value = "user_12345"
        hash1 = strategy.anonymize(value)
        hash2 = strategy.anonymize(value)

        assert hash1 == hash2
        assert len(hash1) == 16  # length configured

    def test_multiple_tables_same_global_seed(self):
        """Multiple tables use same global seed for consistency."""
        profile = AnonymizationProfile(
            name="production",
            version="1.0",
            global_seed=12345,
            strategies={
                "email_mask": StrategyDefinition(type="email"),
            },
            tables={
                "users": TableDefinition(
                    rules=[
                        AnonymizationRule(
                            column="email",
                            strategy="email_mask",
                        )
                    ]
                ),
                "customers": TableDefinition(
                    rules=[
                        AnonymizationRule(
                            column="email_address",
                            strategy="email_mask",
                        )
                    ]
                ),
                "contacts": TableDefinition(
                    rules=[
                        AnonymizationRule(
                            column="email",
                            strategy="email_mask",
                        )
                    ]
                ),
            },
        )

        # Verify all tables use same seed
        for table_def in profile.tables.values():
            for rule in table_def.rules:
                seed = resolve_seed_for_column(rule, profile)
                assert seed == 12345

    def test_column_seed_override_precedence(self):
        """Column-specific seed overrides global_seed."""
        profile = AnonymizationProfile(
            name="production",
            version="1.0",
            global_seed=12345,
            strategies={
                "email_mask": StrategyDefinition(type="email"),
            },
            tables={
                "users": TableDefinition(
                    rules=[
                        AnonymizationRule(
                            column="email",
                            strategy="email_mask",
                        ),
                        AnonymizationRule(
                            column="backup_email",
                            strategy="email_mask",
                            seed=99999,  # Override global seed
                        ),
                    ]
                ),
            },
        )

        rules = profile.tables["users"].rules

        # First rule uses global seed
        seed1 = resolve_seed_for_column(rules[0], profile)
        assert seed1 == 12345

        # Second rule uses column-specific seed
        seed2 = resolve_seed_for_column(rules[1], profile)
        assert seed2 == 99999

        assert seed1 != seed2

    def test_column_seed_override_creates_different_hash(self):
        """Different seeds produce different hashes."""
        strategy1 = EmailMaskingStrategy(EmailMaskConfig(seed=12345))
        strategy2 = EmailMaskingStrategy(EmailMaskConfig(seed=99999))

        email = "john@example.com"
        hash1 = strategy1.anonymize(email)
        hash2 = strategy2.anonymize(email)

        assert hash1 != hash2


class TestForeignKeyIntegration:
    """Test foreign key consistency across tables."""

    def test_user_id_consistency_across_tables(self):
        """User ID hashes consistently across users and orders tables."""
        profile = AnonymizationProfile(
            name="production",
            version="1.0",
            global_seed=12345,
            strategies={
                "hash": StrategyDefinition(type="hash"),
            },
            tables={
                "users": TableDefinition(
                    rules=[
                        AnonymizationRule(
                            column="internal_id",
                            strategy="hash",
                        )
                    ]
                ),
                "orders": TableDefinition(
                    rules=[
                        AnonymizationRule(
                            column="user_id",
                            strategy="hash",
                        )
                    ]
                ),
            },
        )

        strategy = DeterministicHashStrategy(
            DeterministicHashConfig(seed=profile.global_seed)
        )

        # Same user ID hashed in both tables
        user_id = "uuid_123"
        hash_in_users = strategy.anonymize(user_id)
        hash_in_orders = strategy.anonymize(user_id)

        # Should be identical (FK consistency)
        assert hash_in_users == hash_in_orders

    def test_email_consistency_across_users_and_orders(self):
        """Email hashes consistently between users and orders tables."""
        profile = AnonymizationProfile(
            name="production",
            version="1.0",
            global_seed=12345,
            strategies={
                "email_mask": StrategyDefinition(type="email"),
            },
            tables={
                "users": TableDefinition(
                    rules=[
                        AnonymizationRule(
                            column="email",
                            strategy="email_mask",
                        )
                    ]
                ),
                "orders": TableDefinition(
                    rules=[
                        AnonymizationRule(
                            column="customer_email",
                            strategy="email_mask",
                        )
                    ]
                ),
            },
        )

        strategy = EmailMaskingStrategy(
            EmailMaskConfig(seed=profile.global_seed)
        )

        email = "customer@example.com"
        email_in_users = strategy.anonymize(email)
        email_in_orders = strategy.anonymize(email)

        # Should be identical for FK integrity
        assert email_in_users == email_in_orders

    def test_three_table_consistency(self):
        """Email hashes consistently across three tables."""
        profile = AnonymizationProfile(
            name="production",
            version="1.0",
            global_seed=12345,
            strategies={
                "email_mask": StrategyDefinition(type="email"),
            },
            tables={
                "users": TableDefinition(
                    rules=[
                        AnonymizationRule(
                            column="email",
                            strategy="email_mask",
                        )
                    ]
                ),
                "orders": TableDefinition(
                    rules=[
                        AnonymizationRule(
                            column="customer_email",
                            strategy="email_mask",
                        )
                    ]
                ),
                "payments": TableDefinition(
                    rules=[
                        AnonymizationRule(
                            column="payer_email",
                            strategy="email_mask",
                        )
                    ]
                ),
            },
        )

        strategy = EmailMaskingStrategy(
            EmailMaskConfig(seed=profile.global_seed)
        )

        email = "admin@company.com"
        hash1 = strategy.anonymize(email)
        hash2 = strategy.anonymize(email)
        hash3 = strategy.anonymize(email)

        # All three should be identical
        assert hash1 == hash2 == hash3

    def test_no_consistency_without_global_seed(self):
        """Different strategies with different seeds produce different hashes."""
        # Even same value hashes differently with different seeds
        strategy1 = EmailMaskingStrategy(EmailMaskConfig(seed=12345))
        strategy2 = EmailMaskingStrategy(EmailMaskConfig(seed=99999))

        email = "test@example.com"
        hash1 = strategy1.anonymize(email)
        hash2 = strategy2.anonymize(email)

        # Different seeds mean different hashes
        assert hash1 != hash2


class TestSeedPrecedence:
    """Test seed resolution precedence (column > global > default)."""

    def test_column_seed_highest_priority(self):
        """Column-specific seed has highest priority."""
        profile = AnonymizationProfile(
            name="production",
            version="1.0",
            global_seed=1111,
            strategies={},
            tables={
                "table1": TableDefinition(
                    rules=[
                        AnonymizationRule(
                            column="col1",
                            strategy="hash",
                            seed=3333,  # Highest priority
                        )
                    ]
                ),
            },
        )

        rule = profile.tables["table1"].rules[0]
        seed = resolve_seed_for_column(rule, profile)
        assert seed == 3333

    def test_global_seed_second_priority(self):
        """Global seed used when no column-specific seed."""
        profile = AnonymizationProfile(
            name="production",
            version="1.0",
            global_seed=2222,
            strategies={},
            tables={
                "table1": TableDefinition(
                    rules=[
                        AnonymizationRule(
                            column="col1",
                            strategy="hash",
                            # No column-specific seed
                        )
                    ]
                ),
            },
        )

        rule = profile.tables["table1"].rules[0]
        seed = resolve_seed_for_column(rule, profile)
        assert seed == 2222

    def test_default_seed_lowest_priority(self):
        """Default seed (0) used when no global or column seed."""
        profile = AnonymizationProfile(
            name="production",
            version="1.0",
            # No global_seed
            strategies={},
            tables={
                "table1": TableDefinition(
                    rules=[
                        AnonymizationRule(
                            column="col1",
                            strategy="hash",
                            # No column-specific seed
                        )
                    ]
                ),
            },
        )

        rule = profile.tables["table1"].rules[0]
        seed = resolve_seed_for_column(rule, profile)
        assert seed == 0

    def test_precedence_order_complex_scenario(self):
        """Test complete precedence order with multiple rules."""
        profile = AnonymizationProfile(
            name="production",
            version="1.0",
            global_seed=5555,
            strategies={},
            tables={
                "users": TableDefinition(
                    rules=[
                        AnonymizationRule(column="id", strategy="hash", seed=9999),
                        AnonymizationRule(column="email", strategy="hash"),
                        AnonymizationRule(column="ssn", strategy="hash"),
                    ]
                ),
            },
        )

        rules = profile.tables["users"].rules

        # First rule: column seed (9999) > global seed
        assert resolve_seed_for_column(rules[0], profile) == 9999

        # Second rule: global seed (5555) > default
        assert resolve_seed_for_column(rules[1], profile) == 5555

        # Third rule: global seed (5555) > default
        assert resolve_seed_for_column(rules[2], profile) == 5555


class TestRealWorldScenarios:
    """Test realistic production scenarios."""

    def test_ecommerce_schema_consistency(self):
        """Test ecommerce schema with users, orders, payments, reviews."""
        profile = AnonymizationProfile(
            name="production",
            version="1.0",
            global_seed=12345,
            strategies={
                "email_mask": StrategyDefinition(type="email"),
                "hash": StrategyDefinition(type="hash"),
            },
            tables={
                "users": TableDefinition(
                    rules=[
                        AnonymizationRule(
                            column="email",
                            strategy="email_mask",
                        ),
                        AnonymizationRule(
                            column="internal_user_id",
                            strategy="hash",
                        ),
                    ]
                ),
                "orders": TableDefinition(
                    rules=[
                        AnonymizationRule(
                            column="customer_email",
                            strategy="email_mask",
                        ),
                        AnonymizationRule(
                            column="user_id",
                            strategy="hash",
                        ),
                    ]
                ),
                "payments": TableDefinition(
                    rules=[
                        AnonymizationRule(
                            column="payer_email",
                            strategy="email_mask",
                        ),
                    ]
                ),
                "reviews": TableDefinition(
                    rules=[
                        AnonymizationRule(
                            column="reviewer_email",
                            strategy="email_mask",
                        ),
                    ]
                ),
            },
        )

        # Verify all email fields use same seed
        email_strategy = EmailMaskingStrategy(
            EmailMaskConfig(seed=profile.global_seed)
        )

        customer_email = "customer@example.com"
        results = {
            "users": email_strategy.anonymize(customer_email),
            "orders": email_strategy.anonymize(customer_email),
            "payments": email_strategy.anonymize(customer_email),
            "reviews": email_strategy.anonymize(customer_email),
        }

        # All should be identical
        values = list(results.values())
        assert all(v == values[0] for v in values)

        # Verify all ID fields use same seed
        hash_strategy = DeterministicHashStrategy(
            DeterministicHashConfig(seed=profile.global_seed)
        )

        user_id = "uuid_12345"
        id_results = {
            "users": hash_strategy.anonymize(user_id),
            "orders": hash_strategy.anonymize(user_id),
        }

        assert id_results["users"] == id_results["orders"]

    def test_multi_tenant_schema_with_overrides(self):
        """Test multi-tenant scenario where some columns need different seeds."""
        # Create profile (validates structure, not directly used)
        AnonymizationProfile(
            name="production",
            version="1.0",
            global_seed=11111,
            strategies={
                "hash": StrategyDefinition(type="hash"),
            },
            tables={
                "public_profiles": TableDefinition(
                    rules=[
                        AnonymizationRule(
                            column="user_id",
                            strategy="hash",
                        ),  # Uses global_seed (11111)
                        AnonymizationRule(
                            column="api_token",
                            strategy="hash",
                            seed=22222,  # Override: different seed
                        ),
                    ]
                ),
                "orders": TableDefinition(
                    rules=[
                        AnonymizationRule(
                            column="user_id",
                            strategy="hash",
                        ),  # Uses global_seed (11111) - same as public_profiles
                    ]
                ),
            },
        )

        # user_id should be consistent across tables
        hash_strategy = DeterministicHashStrategy(
            DeterministicHashConfig(seed=11111)
        )
        user_id = "uuid_123"
        hash1 = hash_strategy.anonymize(user_id)

        hash_strategy2 = DeterministicHashStrategy(
            DeterministicHashConfig(seed=11111)
        )
        hash2 = hash_strategy2.anonymize(user_id)

        assert hash1 == hash2

        # api_token should be different due to override
        override_strategy = DeterministicHashStrategy(
            DeterministicHashConfig(seed=22222)
        )
        api_token = "secret_token"
        hash_default = hash_strategy.anonymize(api_token)
        hash_override = override_strategy.anonymize(api_token)

        assert hash_default != hash_override
