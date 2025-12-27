"""Address masking anonymization strategy.

Provides flexible address anonymization with field-level control:
- Preserve specific fields (city, state, zip, country)
- Anonymize street address
- Combine with other strategies for complete address masking

Supports multiple address formats and field preservation combinations.
"""

import random
from dataclasses import dataclass, field

from confiture.core.anonymization.strategy import AnonymizationStrategy, StrategyConfig


# Sample streets for anonymization
SAMPLE_STREETS = [
    "Main", "Oak", "Elm", "Maple", "Pine", "Cedar", "Birch", "Ash",
    "Walnut", "Cherry", "Spruce", "Fir", "Hickory", "Chestnut",
]

STREET_TYPES = [
    "Street", "Avenue", "Boulevard", "Drive", "Road", "Lane", "Court",
    "Circle", "Trail", "Way", "Terrace", "Place", "Square", "Parkway",
]

# Sample cities (for full anonymization)
SAMPLE_CITIES = [
    "Springfield", "Shelbyville", "Capital City", "Maple Valley",
    "Riverside", "Lakewood", "Summerville", "Hilltown",
]

# US States
US_STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
]


@dataclass
class AddressConfig(StrategyConfig):
    """Configuration for address masking strategy.

    Attributes:
        seed: Seed for deterministic randomization
        preserve_fields: List of fields to preserve:
            - "city": Keep city name
            - "state": Keep state/province
            - "country": Keep country
            - "zip": Keep postal code
        redact_street: If True, anonymize street address
        format: Address format:
            - "freetext": Freetext address (need to parse)
            - "structured": Structured object with street, city, state, zip

    Example:
        >>> config = AddressConfig(seed=12345, preserve_fields=["city", "state"])
    """

    preserve_fields: list[str] = field(default_factory=lambda: ["city", "country"])
    redact_street: bool = True
    format: str = "freetext"  # freetext, structured


class AddressStrategy(AnonymizationStrategy):
    """Anonymization strategy for masking addresses.

    Provides flexible address anonymization with field-level preservation:
    - Preserve selected fields (city, state, zip, country)
    - Anonymize street address
    - Generate realistic addresses from samples

    Features:
    - Field-level control
    - Deterministic output (seed-based)
    - Format-preserving (maintains address structure)
    - Handles multiple address formats

    Example:
        >>> config = AddressConfig(seed=12345, preserve_fields=["city", "state"])
        >>> strategy = AddressStrategy(config)
        >>> strategy.anonymize("123 Main St, Springfield, IL 62701")
        '456 Oak Avenue, Springfield, IL 62701'
    """

    config_type = AddressConfig
    strategy_name = "address"

    def anonymize(self, value: str) -> str:
        """Anonymize an address value.

        Args:
            value: Address string to anonymize

        Returns:
            Anonymized address preserving specified fields

        Example:
            >>> strategy.anonymize("123 Main St, Springfield, IL 62701")
            '456 Oak Avenue, Springfield, IL 62701'
        """
        if value is None:
            return None

        if isinstance(value, str) and not value.strip():
            return value

        if self.config.format == "freetext":
            return self._anonymize_freetext(value)
        elif self.config.format == "structured":
            return self._anonymize_structured(value)
        else:
            raise ValueError(f"Unknown format: {self.config.format}")

    def _anonymize_freetext(self, value: str) -> str:
        """Anonymize freetext address.

        Attempts to parse and preserve specified fields.

        Args:
            value: Address string

        Returns:
            Anonymized address
        """
        # Simple parsing: assume "street, city, state zip" format
        parts = [p.strip() for p in value.split(",")]

        if len(parts) < 2:
            # Cannot parse - return anonymized version
            return self._anonymize_full_address(value)

        # Try to extract components
        street = parts[0] if len(parts) > 0 else ""
        city_state_zip = " ".join(parts[1:]) if len(parts) > 1 else ""

        # Parse city, state, zip
        words = city_state_zip.split()
        city = " ".join(words[:-2]) if len(words) >= 2 else ""
        state = words[-2] if len(words) >= 2 else ""
        zip_code = words[-1] if words else ""

        # Build anonymized address
        result_parts = []

        # Street
        if "street" not in self.config.preserve_fields and self.config.redact_street:
            result_parts.append(self._anonymize_street())
        else:
            result_parts.append(street)

        # City
        if "city" in self.config.preserve_fields:
            result_parts.append(city)
        else:
            result_parts.append(self._anonymize_city())

        # State
        if "state" in self.config.preserve_fields:
            result_parts.append(state)
        else:
            result_parts.append(self._anonymize_state())

        # Zip
        if "zip" in self.config.preserve_fields:
            result_parts.append(zip_code)
        else:
            result_parts.append(self._anonymize_zip())

        return ", ".join(p for p in result_parts if p)

    def _anonymize_structured(self, value: dict) -> dict:
        """Anonymize structured address dict.

        Args:
            value: Address dict with keys like street, city, state, zip

        Returns:
            Anonymized address dict
        """
        result = {}

        for field_name, field_value in value.items():
            if field_value is None:
                result[field_name] = None
            elif field_name in self.config.preserve_fields:
                result[field_name] = field_value
            elif field_name == "street":
                result[field_name] = self._anonymize_street()
            elif field_name == "city":
                result[field_name] = self._anonymize_city()
            elif field_name == "state":
                result[field_name] = self._anonymize_state()
            elif field_name in ("zip", "postal_code"):
                result[field_name] = self._anonymize_zip()
            else:
                result[field_name] = field_value

        return result

    def _anonymize_full_address(self, value: str) -> str:
        """Fully anonymize address (no parsing).

        Args:
            value: Original address

        Returns:
            Anonymized address of similar length
        """
        rng = random.Random(f"{self.config.seed}:{value}".encode())

        street = rng.choice(SAMPLE_STREETS)
        street_type = rng.choice(STREET_TYPES)
        street_num = rng.randint(1, 999)

        city = rng.choice(SAMPLE_CITIES)
        state = rng.choice(US_STATES)
        zip_code = f"{rng.randint(10000, 99999)}"

        return f"{street_num} {street} {street_type}, {city}, {state} {zip_code}"

    def _anonymize_street(self) -> str:
        """Generate anonymized street address.

        Returns:
            Street address like "123 Oak Avenue"
        """
        rng = random.Random(f"{self.config.seed}:street".encode())

        street_num = rng.randint(1, 999)
        street = rng.choice(SAMPLE_STREETS)
        street_type = rng.choice(STREET_TYPES)

        return f"{street_num} {street} {street_type}"

    def _anonymize_city(self) -> str:
        """Generate anonymized city name.

        Returns:
            City name
        """
        rng = random.Random(f"{self.config.seed}:city".encode())
        return rng.choice(SAMPLE_CITIES)

    def _anonymize_state(self) -> str:
        """Generate anonymized state code.

        Returns:
            State code (e.g., "CA")
        """
        rng = random.Random(f"{self.config.seed}:state".encode())
        return rng.choice(US_STATES)

    def _anonymize_zip(self) -> str:
        """Generate anonymized zip code.

        Returns:
            ZIP code (5 digits)
        """
        rng = random.Random(f"{self.config.seed}:zip".encode())
        return f"{rng.randint(10000, 99999)}"

    def validate(self, value: str | dict) -> bool:
        """Check if strategy can handle this value type.

        Args:
            value: Sample value to validate

        Returns:
            True if value is a string, dict, or None
        """
        return isinstance(value, (str, dict)) or value is None

    def short_name(self) -> str:
        """Return short strategy name for logging.

        Returns:
            Short name (e.g., "address:preserve_city_state")
        """
        preserved = "_".join(self.config.preserve_fields) if self.config.preserve_fields else "none"
        return f"{self.strategy_name}:{preserved}"
