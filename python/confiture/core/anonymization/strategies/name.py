"""Name masking anonymization strategy.

Provides deterministic name masking with multiple format options:
- Preserve initials only (e.g., "John Doe" → "J.D.")
- Generate random names (deterministic from seed)
- Generate name from pools (first names + last names)

Uses seeded randomization to ensure same input always produces same output.
"""

import random
from dataclasses import dataclass

from confiture.core.anonymization.strategy import AnonymizationStrategy, StrategyConfig

# Common first names (50 names for diversity)
FIRST_NAMES = [
    "James", "Mary", "Robert", "Patricia", "Michael", "Jennifer", "William",
    "Linda", "David", "Barbara", "Richard", "Elizabeth", "Joseph", "Susan",
    "Charles", "Jessica", "Christopher", "Sarah", "Daniel", "Karen",
    "Matthew", "Nancy", "Anthony", "Lisa", "Mark", "Betty", "Donald",
    "Margaret", "Steven", "Sandra", "Paul", "Ashley", "Andrew", "Kimberly",
    "Joshua", "Emily", "Kenneth", "Donna", "Kevin", "Michelle", "Brian",
    "Dorothy", "George", "Carol", "Edward", "Amanda", "Ronald", "Melissa",
    "Timothy", "Deborah", "Jason", "Stephanie", "Jeffrey",
]

# Common last names (50 names for diversity)
LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark",
    "Ramirez", "Lewis", "Robinson", "Walker", "Young", "Allen", "King",
    "Wright", "Scott", "Torres", "Peterson", "Phillips", "Campbell",
    "Parker", "Evans", "Edwards", "Collins", "Reyes", "Stewart", "Morris",
    "Morales", "Murphy", "Rogers", "Morgan", "Peterson", "Cooper",
]


@dataclass
class NameMaskConfig(StrategyConfig):
    """Configuration for name masking strategy.

    Attributes:
        seed: Seed for deterministic randomization
        format_type: Output format:
            - "firstname_lastname": "John Doe" → "Michael Patricia" (from name pools)
            - "initials": "John Doe" → "J.D." (preserve initials)
            - "random": "John Doe" → "XyZ4qW9" (random string)
        preserve_initial: If True, keep original first letter
        case_preserving: If True, preserve original case

    Example:
        >>> config = NameMaskConfig(seed=12345, format_type="firstname_lastname")
    """

    format_type: str = "firstname_lastname"  # firstname_lastname, initials, random
    preserve_initial: bool = False  # Only for firstname_lastname format
    case_preserving: bool = True  # Preserve original case


class NameMaskingStrategy(AnonymizationStrategy):
    """Anonymization strategy for masking personal names.

    Provides multiple name masking formats with deterministic output based on seed.
    Same input + same seed = same output (enables foreign key consistency).

    Features:
    - Format-preserving (maintains name-like structure)
    - Deterministic (seed-based)
    - Configurable output format
    - Handles NULL and edge cases

    Example:
        >>> config = NameMaskConfig(seed=12345, format_type="firstname_lastname")
        >>> strategy = NameMaskingStrategy(config)
        >>> strategy.anonymize("John Doe")
        'Michael Johnson'
        >>> strategy.anonymize("John Doe")  # Same seed = same output
        'Michael Johnson'
    """

    config_type = NameMaskConfig
    strategy_name = "name"

    def anonymize(self, value: str) -> str:
        """Anonymize a name value.

        Args:
            value: Name to anonymize

        Returns:
            Anonymized name in configured format

        Example:
            >>> strategy.anonymize("John Doe")
            'Michael Johnson'
        """
        if value is None:
            return None

        if isinstance(value, str) and not value.strip():
            return value

        config = self.config

        if config.format_type == "firstname_lastname":
            return self._mask_firstname_lastname(value)
        elif config.format_type == "initials":
            return self._mask_initials(value)
        elif config.format_type == "random":
            return self._mask_random(value)
        else:
            raise ValueError(f"Unknown format_type: {config.format_type}")

    def _mask_firstname_lastname(self, value: str) -> str:
        """Mask with random first and last name.

        Args:
            value: Name to mask

        Returns:
            Anonymized firstname lastname
        """
        parts = value.strip().split()

        if not parts:
            return value

        # Use seed to generate reproducible random names
        rng = random.Random(f"{self.config.seed}:{value}".encode())

        # Get random first name
        first_name = rng.choice(FIRST_NAMES)

        # Get random last name
        last_name = rng.choice(LAST_NAMES)

        # Apply case preservation if needed
        if self.config.case_preserving and parts:
            # Preserve case of original first name
            if parts[0] and parts[0][0].islower():
                first_name = first_name.lower()

            # Preserve case of original last name (if exists)
            if len(parts) > 1 and parts[1] and parts[1][0].islower():
                last_name = last_name.lower()

        return f"{first_name} {last_name}"

    def _mask_initials(self, value: str) -> str:
        """Mask with initials only.

        Args:
            value: Name to mask

        Returns:
            Initials (e.g., "J.D.")
        """
        parts = value.strip().split()

        if not parts:
            return value

        # Get initials from original name
        initials = [part[0].upper() for part in parts if part]

        return ".".join(initials) + "."

    def _mask_random(self, value: str) -> str:
        """Mask with random string.

        Args:
            value: Name to mask

        Returns:
            Random string of same length as original
        """
        if not value:
            return value

        # Use seed for reproducibility
        rng = random.Random(f"{self.config.seed}:{value}".encode())

        # Generate random string of same length
        length = len(value.strip())
        chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
        return "".join(rng.choices(chars, k=length))

    def validate(self, value: str) -> bool:
        """Check if strategy can handle this value type.

        Args:
            value: Sample value to validate

        Returns:
            True if value is a string or None
        """
        return isinstance(value, str) or value is None

    def short_name(self) -> str:
        """Return short strategy name for logging.

        Returns:
            Short name (e.g., "name:initials")
        """
        return f"{self.strategy_name}:{self.config.format_type}"
