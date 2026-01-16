"""Comprehensive tests for IP address anonymization strategy."""

import pytest

from confiture.core.anonymization.strategies.ip_address import (
    IPAddressConfig,
    IPAddressStrategy,
)


class TestIPAddressStrategy:
    """Tests for IPAddressStrategy class."""

    @pytest.fixture
    def strategy_default(self):
        """Create strategy with default config."""
        config = IPAddressConfig(seed=12345)
        return IPAddressStrategy(config)

    @pytest.fixture
    def strategy_no_subnet_preserve(self):
        """Create strategy without subnet preservation."""
        config = IPAddressConfig(seed=12345, preserve_subnet=False)
        return IPAddressStrategy(config)

    @pytest.fixture
    def strategy_preserve_16(self):
        """Create strategy preserving /16 subnet for IPv4."""
        config = IPAddressConfig(seed=12345, preserve_subnet=True, subnet_bits_ipv4=16)
        return IPAddressStrategy(config)

    @pytest.fixture
    def strategy_anonymize_localhost(self):
        """Create strategy that anonymizes localhost."""
        config = IPAddressConfig(seed=12345, anonymize_localhost=True)
        return IPAddressStrategy(config)

    # Basic IPv4 anonymization tests
    def test_anonymize_ipv4_basic(self, strategy_default):
        """Test basic IPv4 anonymization."""
        result = strategy_default.anonymize("192.168.1.100")
        assert result != "192.168.1.100"
        # Should still be a valid IPv4-like string
        assert len(result.split(".")) == 4

    def test_anonymize_ipv4_deterministic(self, strategy_default):
        """Test same input gives same output."""
        ip = "192.168.1.100"
        result1 = strategy_default.anonymize(ip)
        result2 = strategy_default.anonymize(ip)
        assert result1 == result2

    def test_anonymize_ipv4_different_seeds(self):
        """Test different seeds give different outputs."""
        config1 = IPAddressConfig(seed=12345, preserve_subnet=False)
        config2 = IPAddressConfig(seed=67890, preserve_subnet=False)
        strategy1 = IPAddressStrategy(config1)
        strategy2 = IPAddressStrategy(config2)

        ip = "192.168.1.100"
        result1 = strategy1.anonymize(ip)
        result2 = strategy2.anonymize(ip)
        assert result1 != result2

    def test_anonymize_ipv4_preserve_subnet_8(self, strategy_default):
        """Test preserving /8 subnet (default)."""
        result = strategy_default.anonymize("192.168.1.100")
        # First octet should be preserved
        assert result.startswith("192.")

    def test_anonymize_ipv4_preserve_subnet_16(self, strategy_preserve_16):
        """Test preserving /16 subnet."""
        result = strategy_preserve_16.anonymize("192.168.1.100")
        # First two octets should be preserved
        assert result.startswith("192.168.")

    def test_anonymize_ipv4_no_preserve_subnet(self, strategy_no_subnet_preserve):
        """Test full anonymization without subnet preservation."""
        result = strategy_no_subnet_preserve.anonymize("192.168.1.100")
        # Entire IP should be randomized
        assert result != "192.168.1.100"
        # Very unlikely to start with same octet
        # (Just verify it's valid format)
        parts = result.split(".")
        assert len(parts) == 4
        for part in parts:
            assert 0 <= int(part) <= 255

    # IPv6 anonymization tests
    def test_anonymize_ipv6_basic(self, strategy_default):
        """Test basic IPv6 anonymization."""
        result = strategy_default.anonymize("2001:0db8:85a3:0000:0000:8a2e:0370:7334")
        assert result != "2001:0db8:85a3:0000:0000:8a2e:0370:7334"
        assert ":" in result  # Still an IPv6 address

    def test_anonymize_ipv6_shortened(self, strategy_default):
        """Test IPv6 anonymization with shortened notation."""
        result = strategy_default.anonymize("2001:db8::1")
        assert result != "2001:db8::1"
        assert ":" in result

    def test_anonymize_ipv6_deterministic(self, strategy_default):
        """Test IPv6 is deterministic."""
        ip = "2001:db8::1"
        result1 = strategy_default.anonymize(ip)
        result2 = strategy_default.anonymize(ip)
        assert result1 == result2

    def test_anonymize_ipv6_preserve_subnet(self, strategy_default):
        """Test IPv6 subnet preservation."""
        result = strategy_default.anonymize("2001:db8:85a3::8a2e:370:7334")
        # With default 16-bit preservation, first 16 bits should match
        # 2001 has the first 16 bits preserved
        assert result.startswith("2001:")

    def test_anonymize_ipv6_no_preserve_subnet(self, strategy_no_subnet_preserve):
        """Test IPv6 full anonymization."""
        result = strategy_no_subnet_preserve.anonymize("2001:db8::1")
        assert result != "2001:db8::1"
        assert ":" in result

    # CIDR notation tests
    def test_anonymize_cidr_ipv4(self, strategy_default):
        """Test IPv4 CIDR notation anonymization."""
        result = strategy_default.anonymize("192.168.1.0/24")
        assert "/24" in result  # Prefix length preserved
        # Network address should be anonymized
        assert result != "192.168.1.0/24"

    def test_anonymize_cidr_ipv6(self, strategy_default):
        """Test IPv6 CIDR notation anonymization."""
        result = strategy_default.anonymize("2001:db8::/32")
        assert "/32" in result  # Prefix length preserved

    # Localhost handling tests
    def test_localhost_ipv4_not_anonymized(self, strategy_default):
        """Test localhost IPv4 is not anonymized by default."""
        result = strategy_default.anonymize("127.0.0.1")
        assert result == "127.0.0.1"

    def test_localhost_ipv6_not_anonymized(self, strategy_default):
        """Test localhost IPv6 is not anonymized by default."""
        result = strategy_default.anonymize("::1")
        assert result == "::1"

    def test_localhost_ipv4_anonymized_when_configured(self, strategy_anonymize_localhost):
        """Test localhost IPv4 is anonymized when configured."""
        result = strategy_anonymize_localhost.anonymize("127.0.0.1")
        assert result != "127.0.0.1"

    def test_localhost_ipv6_anonymized_when_configured(self, strategy_anonymize_localhost):
        """Test localhost IPv6 is anonymized when configured."""
        result = strategy_anonymize_localhost.anonymize("::1")
        assert result != "::1"

    # Edge cases
    def test_anonymize_none_returns_none(self, strategy_default):
        """Test None input returns None."""
        assert strategy_default.anonymize(None) is None

    def test_anonymize_empty_string(self, strategy_default):
        """Test empty string returns empty string."""
        assert strategy_default.anonymize("") == ""

    def test_anonymize_whitespace_only(self, strategy_default):
        """Test whitespace returns whitespace."""
        assert strategy_default.anonymize("   ") == "   "

    def test_anonymize_invalid_ip_returns_unchanged(self, strategy_default):
        """Test invalid IP address returns unchanged."""
        result = strategy_default.anonymize("not-an-ip-address")
        assert result == "not-an-ip-address"

    def test_anonymize_partial_ip_returns_unchanged(self, strategy_default):
        """Test partial IP address returns unchanged."""
        result = strategy_default.anonymize("192.168")
        assert result == "192.168"

    def test_anonymize_ip_with_port_returns_unchanged(self, strategy_default):
        """Test IP with port returns unchanged (not valid IP format)."""
        result = strategy_default.anonymize("192.168.1.1:8080")
        assert result == "192.168.1.1:8080"

    # Validate method
    def test_validate_string(self, strategy_default):
        """Test validate accepts string."""
        assert strategy_default.validate("192.168.1.1") is True

    def test_validate_none(self, strategy_default):
        """Test validate accepts None."""
        assert strategy_default.validate(None) is True

    def test_validate_non_string(self, strategy_default):
        """Test validate rejects non-string."""
        assert strategy_default.validate(12345) is False
        assert strategy_default.validate(["192.168.1.1"]) is False

    # Short name
    def test_short_name_preserve_subnet(self, strategy_default):
        """Test short name with subnet preservation."""
        assert strategy_default.short_name() == "ip_address:preserve_/8"

    def test_short_name_preserve_subnet_16(self, strategy_preserve_16):
        """Test short name with /16 subnet preservation."""
        assert strategy_preserve_16.short_name() == "ip_address:preserve_/16"

    def test_short_name_no_preserve(self, strategy_no_subnet_preserve):
        """Test short name without subnet preservation."""
        assert strategy_no_subnet_preserve.short_name() == "ip_address:full"

    # Strategy name and config type
    def test_strategy_name(self, strategy_default):
        """Test strategy name is ip_address."""
        assert strategy_default.strategy_name == "ip_address"

    def test_config_type(self, strategy_default):
        """Test config type is IPAddressConfig."""
        assert strategy_default.config_type == IPAddressConfig


class TestIPAddressConfig:
    """Tests for IPAddressConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = IPAddressConfig(seed=12345)
        assert config.preserve_subnet is True
        assert config.subnet_bits_ipv4 == 8
        assert config.subnet_bits_ipv6 == 16
        assert config.anonymize_localhost is False

    def test_custom_preserve_subnet(self):
        """Test custom preserve_subnet."""
        config = IPAddressConfig(seed=12345, preserve_subnet=False)
        assert config.preserve_subnet is False

    def test_custom_subnet_bits_ipv4(self):
        """Test custom subnet bits for IPv4."""
        config = IPAddressConfig(seed=12345, subnet_bits_ipv4=24)
        assert config.subnet_bits_ipv4 == 24

    def test_custom_subnet_bits_ipv6(self):
        """Test custom subnet bits for IPv6."""
        config = IPAddressConfig(seed=12345, subnet_bits_ipv6=64)
        assert config.subnet_bits_ipv6 == 64

    def test_custom_anonymize_localhost(self):
        """Test custom anonymize_localhost."""
        config = IPAddressConfig(seed=12345, anonymize_localhost=True)
        assert config.anonymize_localhost is True

    def test_all_custom_values(self):
        """Test all custom values together."""
        config = IPAddressConfig(
            seed=12345,
            preserve_subnet=False,
            subnet_bits_ipv4=16,
            subnet_bits_ipv6=32,
            anonymize_localhost=True,
        )
        assert config.preserve_subnet is False
        assert config.subnet_bits_ipv4 == 16
        assert config.subnet_bits_ipv6 == 32
        assert config.anonymize_localhost is True


class TestIPAddressEdgeCases:
    """Edge case tests for IP address anonymization."""

    def test_various_ipv4_addresses(self):
        """Test various IPv4 addresses."""
        config = IPAddressConfig(seed=12345)
        strategy = IPAddressStrategy(config)

        addresses = [
            "0.0.0.0",
            "255.255.255.255",
            "10.0.0.1",
            "172.16.0.1",
            "192.168.0.1",
        ]

        for addr in addresses:
            result = strategy.anonymize(addr)
            assert result != addr or addr == "127.0.0.1"  # Localhost special case
            parts = result.split(".")
            assert len(parts) == 4
            for part in parts:
                assert 0 <= int(part) <= 255

    def test_various_ipv6_addresses(self):
        """Test various IPv6 addresses."""
        config = IPAddressConfig(seed=12345)
        strategy = IPAddressStrategy(config)

        addresses = [
            "fe80::1",  # Link-local
            "::ffff:192.168.1.1",  # IPv4-mapped IPv6
            "fc00::1",  # Unique local
        ]

        for addr in addresses:
            result = strategy.anonymize(addr)
            # All should be anonymized (not localhost)
            assert result != addr

    def test_various_cidr_notations(self):
        """Test various CIDR notations."""
        config = IPAddressConfig(seed=12345)
        strategy = IPAddressStrategy(config)

        cidrs = [
            ("10.0.0.0/8", "/8"),
            ("192.168.0.0/16", "/16"),
            ("172.16.0.0/12", "/12"),
            ("2001:db8::/32", "/32"),
        ]

        for cidr, expected_suffix in cidrs:
            result = strategy.anonymize(cidr)
            assert expected_suffix in result
