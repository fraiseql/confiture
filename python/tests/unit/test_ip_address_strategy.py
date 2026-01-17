"""Unit tests for IP address masking strategy.

Tests:
- IPv4 and IPv6 anonymization
- Subnet preservation
- CIDR notation
- Format preservation
- Deterministic output
- Edge cases
"""

from confiture.core.anonymization.strategies.ip_address import (
    IPAddressConfig,
    IPAddressStrategy,
)


class TestIPv4Masking:
    """Tests for IPv4 address masking."""

    def test_anonymize_ipv4_simple(self):
        """Test basic IPv4 anonymization."""
        config = IPAddressConfig(seed=12345, preserve_subnet=False)
        strategy = IPAddressStrategy(config)
        result = strategy.anonymize("192.168.1.100")

        assert result is not None
        assert isinstance(result, str)
        # Should be a valid IP format
        parts = result.split(".")
        assert len(parts) == 4
        assert all(0 <= int(p) <= 255 for p in parts)

    def test_anonymize_ipv4_none_returns_none(self):
        """Test None returns None."""
        config = IPAddressConfig(seed=12345)
        strategy = IPAddressStrategy(config)
        assert strategy.anonymize(None) is None

    def test_anonymize_ipv4_empty_returns_empty(self):
        """Test empty string returns empty."""
        config = IPAddressConfig(seed=12345)
        strategy = IPAddressStrategy(config)
        assert strategy.anonymize("") == ""

    def test_preserve_subnet_ipv4(self):
        """Test subnet preservation for IPv4."""
        config = IPAddressConfig(seed=12345, preserve_subnet=True, subnet_bits_ipv4=8)
        strategy = IPAddressStrategy(config)
        result = strategy.anonymize("192.168.1.100")

        # First octet should be preserved (192)
        assert result.startswith("192.")

    def test_preserve_larger_subnet_ipv4(self):
        """Test preserving larger subnet (16 bits)."""
        config = IPAddressConfig(seed=12345, preserve_subnet=True, subnet_bits_ipv4=16)
        strategy = IPAddressStrategy(config)
        result = strategy.anonymize("192.168.1.100")

        # First two octets should be preserved
        parts = result.split(".")
        assert parts[0] == "192"
        assert parts[1] == "168"

    def test_deterministic_ipv4(self):
        """Test deterministic output with same seed."""
        config = IPAddressConfig(seed=12345)
        strategy = IPAddressStrategy(config)

        result1 = strategy.anonymize("192.168.1.100")
        result2 = strategy.anonymize("192.168.1.100")

        assert result1 == result2

    def test_different_seed_ipv4(self):
        """Test different seed produces different output."""
        strategy1 = IPAddressStrategy(IPAddressConfig(seed=12345))
        strategy2 = IPAddressStrategy(IPAddressConfig(seed=67890))

        result1 = strategy1.anonymize("192.168.1.100")
        result2 = strategy2.anonymize("192.168.1.100")

        assert result1 != result2

    def test_localhost_preservation(self):
        """Test localhost is not anonymized by default."""
        config = IPAddressConfig(seed=12345, anonymize_localhost=False)
        strategy = IPAddressStrategy(config)
        result = strategy.anonymize("127.0.0.1")

        assert result == "127.0.0.1"

    def test_localhost_anonymization(self):
        """Test localhost can be anonymized if configured."""
        config = IPAddressConfig(seed=12345, anonymize_localhost=True)
        strategy = IPAddressStrategy(config)
        result = strategy.anonymize("127.0.0.1")

        assert result != "127.0.0.1"


class TestIPv6Masking:
    """Tests for IPv6 address masking."""

    def test_anonymize_ipv6_simple(self):
        """Test basic IPv6 anonymization."""
        config = IPAddressConfig(seed=12345, preserve_subnet=False)
        strategy = IPAddressStrategy(config)
        result = strategy.anonymize("2001:0db8:85a3:0000:0000:8a2e:0370:7334")

        assert result is not None
        assert isinstance(result, str)

    def test_anonymize_ipv6_short(self):
        """Test IPv6 short notation."""
        config = IPAddressConfig(seed=12345, preserve_subnet=False)
        strategy = IPAddressStrategy(config)
        result = strategy.anonymize("2001:db8::1")

        assert result is not None

    def test_preserve_subnet_ipv6(self):
        """Test subnet preservation for IPv6."""
        config = IPAddressConfig(seed=12345, preserve_subnet=True, subnet_bits_ipv6=32)
        strategy = IPAddressStrategy(config)
        result = strategy.anonymize("2001:0db8:85a3:0000:0000:8a2e:0370:7334")

        # First 32 bits (first 2 groups) should be preserved
        assert result.startswith("2001:db8:")

    def test_deterministic_ipv6(self):
        """Test deterministic output with same seed."""
        config = IPAddressConfig(seed=12345)
        strategy = IPAddressStrategy(config)

        result1 = strategy.anonymize("2001:db8::1")
        result2 = strategy.anonymize("2001:db8::1")

        assert result1 == result2

    def test_localhost_ipv6_preservation(self):
        """Test IPv6 localhost is preserved by default."""
        config = IPAddressConfig(seed=12345, anonymize_localhost=False)
        strategy = IPAddressStrategy(config)
        result = strategy.anonymize("::1")

        assert result == "::1"


class TestCIDRNotation:
    """Tests for CIDR notation support."""

    def test_anonymize_ipv4_cidr(self):
        """Test IPv4 with CIDR notation."""
        config = IPAddressConfig(seed=12345)
        strategy = IPAddressStrategy(config)
        result = strategy.anonymize("192.168.1.0/24")

        # Should preserve CIDR prefix length
        assert "/24" in result

    def test_anonymize_ipv6_cidr(self):
        """Test IPv6 with CIDR notation."""
        config = IPAddressConfig(seed=12345)
        strategy = IPAddressStrategy(config)
        result = strategy.anonymize("2001:db8::/32")

        # Should preserve CIDR prefix length
        assert "/32" in result

    def test_cidr_preserves_prefix_length(self):
        """Test CIDR prefix length is unchanged."""
        config = IPAddressConfig(seed=12345)
        strategy = IPAddressStrategy(config)
        result = strategy.anonymize("10.0.0.0/8")

        assert result.endswith("/8")


class TestInvalidIPs:
    """Tests for invalid IP handling."""

    def test_invalid_ip_returned_as_is(self):
        """Test invalid IP is returned unchanged."""
        config = IPAddressConfig(seed=12345)
        strategy = IPAddressStrategy(config)
        result = strategy.anonymize("not-an-ip-address")

        assert result == "not-an-ip-address"

    def test_invalid_ipv4_returned_as_is(self):
        """Test invalid IPv4 is returned unchanged."""
        config = IPAddressConfig(seed=12345)
        strategy = IPAddressStrategy(config)
        result = strategy.anonymize("999.999.999.999")

        assert result == "999.999.999.999"

    def test_partial_ip_returned_as_is(self):
        """Test partial IP is returned unchanged."""
        config = IPAddressConfig(seed=12345)
        strategy = IPAddressStrategy(config)
        result = strategy.anonymize("192.168.1")

        assert result == "192.168.1"


class TestIPRanges:
    """Tests for various IP ranges."""

    def test_private_ipv4_ranges(self):
        """Test private IPv4 address anonymization."""
        config = IPAddressConfig(seed=12345)
        strategy = IPAddressStrategy(config)

        # Test common private ranges
        private_ips = ["10.0.0.1", "172.16.0.1", "192.168.0.1"]
        for ip in private_ips:
            result = strategy.anonymize(ip)
            assert result is not None
            assert isinstance(result, str)

    def test_public_ipv4_addresses(self):
        """Test public IPv4 address anonymization."""
        config = IPAddressConfig(seed=12345)
        strategy = IPAddressStrategy(config)

        public_ips = ["8.8.8.8", "1.1.1.1", "208.67.222.222"]
        for ip in public_ips:
            result = strategy.anonymize(ip)
            assert result is not None


class TestShortName:
    """Tests for strategy short name."""

    def test_short_name_preserve(self):
        """Test short name for preserve mode."""
        config = IPAddressConfig(seed=12345, preserve_subnet=True)
        strategy = IPAddressStrategy(config)
        short = strategy.short_name()

        assert "preserve" in short

    def test_short_name_full(self):
        """Test short name for full anonymization."""
        config = IPAddressConfig(seed=12345, preserve_subnet=False)
        strategy = IPAddressStrategy(config)
        short = strategy.short_name()

        assert "full" in short


class TestConfigValidation:
    """Tests for configuration."""

    def test_default_config(self):
        """Test default configuration."""
        config = IPAddressConfig()
        assert config.preserve_subnet is True
        assert config.subnet_bits_ipv4 == 8
        assert config.subnet_bits_ipv6 == 16
        assert config.anonymize_localhost is False

    def test_custom_subnet_bits(self):
        """Test custom subnet bits."""
        config = IPAddressConfig(subnet_bits_ipv4=24, subnet_bits_ipv6=64)
        assert config.subnet_bits_ipv4 == 24
        assert config.subnet_bits_ipv6 == 64
