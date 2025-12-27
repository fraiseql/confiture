"""IP address masking anonymization strategy.

Provides IPv4 and IPv6 anonymization with:
- Preserve subnet masks (network topology)
- Anonymize individual host addresses
- Format preservation (IPv4 vs IPv6)
- Deterministic anonymization based on seed
- Support for CIDR notation

Useful for log anonymization while preserving network patterns.
"""

import random
import ipaddress
from dataclasses import dataclass
from confiture.core.anonymization.strategy import AnonymizationStrategy, StrategyConfig


@dataclass
class IPAddressConfig(StrategyConfig):
    """Configuration for IP address masking strategy.

    Attributes:
        seed: Seed for deterministic randomization
        preserve_subnet: If True, preserve subnet mask bits (default True)
        subnet_bits_ipv4: Number of bits to preserve for IPv4 (default 8)
        subnet_bits_ipv6: Number of bits to preserve for IPv6 (default 16)
        anonymize_localhost: If True, anonymize 127.0.0.1/::1 (default False)

    Example:
        >>> config = IPAddressConfig(seed=12345, preserve_subnet=True, subnet_bits_ipv4=8)
    """

    preserve_subnet: bool = True
    subnet_bits_ipv4: int = 8  # Preserve /8 subnet (class A)
    subnet_bits_ipv6: int = 16  # Preserve /16 subnet
    anonymize_localhost: bool = False


class IPAddressStrategy(AnonymizationStrategy):
    """Anonymization strategy for masking IP addresses.

    Provides IPv4 and IPv6 anonymization with optional subnet preservation:
    - Preserve subnet mask for network patterns
    - Anonymize host bits
    - Support CIDR notation
    - Format preservation

    Features:
    - Dual IPv4/IPv6 support
    - Subnet preservation
    - Format validation
    - Deterministic output

    Example:
        >>> config = IPAddressConfig(seed=12345, preserve_subnet=True)
        >>> strategy = IPAddressStrategy(config)
        >>> strategy.anonymize("192.168.1.100")
        '192.x.x.x'  # Preserve /8 subnet
    """

    config_type = IPAddressConfig
    strategy_name = "ip_address"

    def anonymize(self, value: str) -> str:
        """Anonymize an IP address.

        Args:
            value: IP address (IPv4 or IPv6, with optional CIDR notation)

        Returns:
            Anonymized IP address

        Example:
            >>> strategy.anonymize("192.168.1.100")
            '192.xxx.xxx.xxx'
        """
        if value is None:
            return None

        if isinstance(value, str) and not value.strip():
            return value

        try:
            # Try to parse as IP address with optional CIDR
            if "/" in value:
                # CIDR notation
                network = ipaddress.ip_network(value, strict=False)
                anon_ip = self._anonymize_network(network)
                return f"{anon_ip}/{network.prefixlen}"
            else:
                # Single IP address
                ip = ipaddress.ip_address(value)
                return self._anonymize_address(ip)
        except ValueError:
            # Invalid IP address - return as-is
            return value

    def validate(self, value: str) -> bool:
        """Check if strategy can handle this value type.

        Args:
            value: Sample value to validate

        Returns:
            True if value is a string or None
        """
        return isinstance(value, str) or value is None

    def _anonymize_address(self, ip: ipaddress.ip_address) -> str:
        """Anonymize a single IP address.

        Args:
            ip: IP address object

        Returns:
            Anonymized IP address string
        """
        # Skip localhost if configured
        if not self.config.anonymize_localhost:
            if isinstance(ip, ipaddress.IPv4Address) and ip == ipaddress.IPv4Address("127.0.0.1"):
                return str(ip)
            elif isinstance(ip, ipaddress.IPv6Address) and ip == ipaddress.IPv6Address("::1"):
                return str(ip)

        if isinstance(ip, ipaddress.IPv4Address):
            return self._anonymize_ipv4(ip)
        else:
            return self._anonymize_ipv6(ip)

    def _anonymize_ipv4(self, ip: ipaddress.IPv4Address) -> str:
        """Anonymize IPv4 address.

        Args:
            ip: IPv4 address object

        Returns:
            Anonymized IPv4 address string
        """
        rng = random.Random(f"{self.config.seed}:{str(ip)}".encode())

        if self.config.preserve_subnet:
            # Preserve first N bits (subnet), anonymize host bits
            bits_to_preserve = self.config.subnet_bits_ipv4
            bits_to_randomize = 32 - bits_to_preserve

            # Convert to integer
            ip_int = int(ip)

            # Create mask for preservation
            preserve_mask = (0xFFFFFFFF << bits_to_randomize) & 0xFFFFFFFF

            # Generate random bits for host part
            random_bits = rng.getrandbits(bits_to_randomize)

            # Combine
            anon_int = (ip_int & preserve_mask) | random_bits

            # Convert back to IP
            anon_ip = ipaddress.IPv4Address(anon_int)
            return str(anon_ip)
        else:
            # Fully randomize
            random_int = rng.getrandbits(32)
            anon_ip = ipaddress.IPv4Address(random_int)
            return str(anon_ip)

    def _anonymize_ipv6(self, ip: ipaddress.IPv6Address) -> str:
        """Anonymize IPv6 address.

        Args:
            ip: IPv6 address object

        Returns:
            Anonymized IPv6 address string
        """
        rng = random.Random(f"{self.config.seed}:{str(ip)}".encode())

        if self.config.preserve_subnet:
            # Preserve first N bits (subnet), anonymize host bits
            bits_to_preserve = self.config.subnet_bits_ipv6
            bits_to_randomize = 128 - bits_to_preserve

            # Convert to integer
            ip_int = int(ip)

            # Create mask for preservation
            preserve_mask = (0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF << bits_to_randomize) & 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF

            # Generate random bits for host part
            random_bits = rng.getrandbits(bits_to_randomize)

            # Combine
            anon_int = (ip_int & preserve_mask) | random_bits

            # Convert back to IP
            anon_ip = ipaddress.IPv6Address(anon_int)
            return str(anon_ip)
        else:
            # Fully randomize
            random_int = rng.getrandbits(128)
            anon_ip = ipaddress.IPv6Address(random_int)
            return str(anon_ip)

    def _anonymize_network(self, network: ipaddress.ip_network) -> str:
        """Anonymize network address.

        Args:
            network: Network object

        Returns:
            Anonymized network address string
        """
        # Anonymize the network address only (not host bits)
        return self._anonymize_address(network.network_address)

    def short_name(self) -> str:
        """Return short strategy name for logging.

        Returns:
            Short name (e.g., "ip_address:preserve_/8")
        """
        if self.config.preserve_subnet:
            if isinstance(self, IPAddressStrategy):
                # Try to detect if it's IPv4 or IPv6
                return f"ip_address:preserve_/{self.config.subnet_bits_ipv4}"
            return "ip_address:preserve"
        return "ip_address:full"
