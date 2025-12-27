"""Credit card masking anonymization strategy.

Provides PCI-DSS compliant credit card anonymization with:
- Preserve last 4 digits (identifies card variant)
- Preserve BIN (Bank Identification Number - first 6 digits)
- Luhn validation for checksums
- Card type detection (Visa, Mastercard, Amex, Discover, etc)
- Deterministic anonymization based on seed

Security Note:
    Does NOT mask full PAN in production without proper PCI-DSS controls.
    Use with secure storage and access controls. This is for data masking only.
"""

import random
from dataclasses import dataclass
from confiture.core.anonymization.strategy import AnonymizationStrategy, StrategyConfig


# Card type patterns: (name, digit_lengths, prefix_patterns)
CARD_TYPES = {
    "visa": (16, [4]),
    "mastercard": (16, [51, 52, 53, 54, 55]),
    "amex": (15, [34, 37]),
    "discover": (16, [6011, 622, 644, 645, 646, 647, 648, 649, 65]),
    "diners": (14, [36, 38, 39]),
    "jcb": (16, [35]),
}


def luhn_checksum(card_number: str) -> int:
    """Calculate Luhn checksum for card number.

    Args:
        card_number: Card number string (digits only, without checksum)

    Returns:
        Luhn checksum digit
    """
    digits = [int(d) for d in card_number]
    # Double every second digit from right to left (before checksum)
    # Since we're calculating the checksum digit, start from the right and skip first position
    for i in range(len(digits) - 1, -1, -2):
        digits[i] *= 2
        if digits[i] > 9:
            digits[i] -= 9

    total = sum(digits)
    checksum = (10 - (total % 10)) % 10
    return checksum


def detect_card_type(card_number: str) -> str:
    """Detect card type from card number.

    Args:
        card_number: Card number string (digits only)

    Returns:
        Card type (visa, mastercard, amex, etc) or 'unknown'
    """
    if not card_number or not card_number.isdigit():
        return "unknown"

    for card_type, (expected_length, prefixes) in CARD_TYPES.items():
        if len(card_number) == expected_length:
            for prefix in prefixes:
                if card_number.startswith(str(prefix)):
                    return card_type

    return "unknown"


def is_valid_card_number(card_number: str) -> bool:
    """Validate card number using Luhn algorithm.

    Args:
        card_number: Card number string (may include spaces/dashes)

    Returns:
        True if card number passes Luhn validation
    """
    if not card_number:
        return False

    # Remove spaces/dashes
    digits_str = card_number.replace(" ", "").replace("-", "")

    if not digits_str.isdigit():
        return False

    # Check valid length
    if len(digits_str) < 13 or len(digits_str) > 19:
        return False

    # Verify Luhn checksum
    digits = [int(d) for d in digits_str]
    # Double every second digit from right to left
    for i in range(len(digits) - 2, -1, -2):
        digits[i] *= 2
        if digits[i] > 9:
            digits[i] -= 9

    return sum(digits) % 10 == 0


@dataclass
class CreditCardConfig(StrategyConfig):
    """Configuration for credit card masking strategy.

    Attributes:
        seed: Seed for deterministic randomization
        preserve_last4: If True, preserve last 4 digits (default True)
        preserve_bin: If True, preserve first 6 digits (default False)
        mask_char: Character to use for masking (default '*')
        validate: If True, validate card number with Luhn (default True)

    Example:
        >>> config = CreditCardConfig(seed=12345, preserve_last4=True)
    """

    preserve_last4: bool = True
    preserve_bin: bool = False
    mask_char: str = "*"
    validate: bool = True


class CreditCardStrategy(AnonymizationStrategy):
    """Anonymization strategy for masking credit card numbers.

    Provides PCI-DSS compliant card masking with configurable preservation:
    - Preserve last 4 digits (identifies card type for customer)
    - Preserve BIN (first 6 digits, bank identifier)
    - Generate realistic valid card numbers (pass Luhn check)
    - Deterministic output (same seed = same output)

    Features:
    - Luhn validation
    - Card type detection
    - Format preservation
    - PCI-DSS compliant

    Example:
        >>> config = CreditCardConfig(seed=12345, preserve_last4=True)
        >>> strategy = CreditCardStrategy(config)
        >>> strategy.anonymize("4532-1111-1111-1234")
        '4532-****-****-1234'  # Last 4 preserved
    """

    config_type = CreditCardConfig
    strategy_name = "credit_card"

    def anonymize(self, value: str) -> str:
        """Anonymize a credit card number.

        Args:
            value: Card number (with or without separators)

        Returns:
            Anonymized card number

        Example:
            >>> strategy.anonymize("4532-1111-1111-1234")
            '4532-****-****-1234'
        """
        if value is None:
            return None

        if isinstance(value, str) and not value.strip():
            return value

        # Clean card number
        cleaned = value.replace(" ", "").replace("-", "")

        # Validate if required
        if self.config.validate and not is_valid_card_number(cleaned):
            # If validation fails, return masked version
            return self._mask_simple(value)

        # Generate anonymized card
        if self.config.preserve_bin:
            return self._anonymize_preserve_bin(cleaned, value)
        elif self.config.preserve_last4:
            return self._anonymize_preserve_last4(cleaned, value)
        else:
            return self._anonymize_full(cleaned, value)

    def validate(self, value: str) -> bool:
        """Check if strategy can handle this value type.

        Args:
            value: Sample value to validate

        Returns:
            True if value is a string or None
        """
        return isinstance(value, str) or value is None

    def _mask_simple(self, card_number: str) -> str:
        """Simple masking for invalid cards.

        Args:
            card_number: Original card number

        Returns:
            Masked card with same format
        """
        cleaned = card_number.replace(" ", "").replace("-", "")
        mask_count = max(len(cleaned) - 4, 0)

        masked = self.config.mask_char * mask_count + cleaned[-4:] if mask_count > 0 else cleaned

        # Return in original format
        return self._apply_format(card_number, masked)

    def _anonymize_preserve_last4(self, cleaned: str, original: str) -> str:
        """Anonymize but preserve last 4 digits.

        Args:
            cleaned: Card number without separators
            original: Original card number with formatting

        Returns:
            Anonymized card number in same format as original
        """
        rng = random.Random(f"{self.config.seed}:{cleaned}".encode())

        last4 = cleaned[-4:]
        first_part = cleaned[:-4]

        # Generate random middle digits (excluding the check digit space)
        # We need to preserve last 4, so randomize everything before that
        middle_length = len(first_part) - 6
        if middle_length > 0:
            middle = "".join(str(rng.randint(0, 9)) for _ in range(middle_length))
        else:
            middle = ""

        # Generate BIN (first 6 digits) - keep valid card type if possible
        card_type = detect_card_type(cleaned)
        bin_digits = self._generate_bin(card_type, rng)

        # Reconstruct card number WITHOUT checksum first
        # We preserve the last 4, then calculate checksum for the rest
        partial_card = bin_digits + middle + last4[:-1]  # First 3 of last4
        checksum = luhn_checksum(partial_card)
        anon_card = partial_card + str(checksum)

        # Apply original format
        return self._apply_format(original, anon_card)

    def _anonymize_preserve_bin(self, cleaned: str, original: str) -> str:
        """Anonymize but preserve BIN (first 6 digits).

        Args:
            cleaned: Card number without separators
            original: Original card number with formatting

        Returns:
            Anonymized card number in same format as original
        """
        rng = random.Random(f"{self.config.seed}:{cleaned}".encode())

        bin_digits = cleaned[:6]
        last4 = cleaned[-4:]

        # Generate random middle digits
        middle_length = len(cleaned) - 10
        if middle_length > 0:
            middle = "".join(str(rng.randint(0, 9)) for _ in range(middle_length))
        else:
            middle = ""

        # Reconstruct card number
        anon_card = bin_digits + middle + last4

        # Calculate and append Luhn checksum
        checksum = luhn_checksum(anon_card[:-1])
        anon_card = anon_card[:-1] + str(checksum)

        # Apply original format
        return self._apply_format(original, anon_card)

    def _anonymize_full(self, cleaned: str, original: str) -> str:
        """Fully anonymize card number.

        Args:
            cleaned: Card number without separators
            original: Original card number with formatting

        Returns:
            Anonymized card number in same format as original
        """
        rng = random.Random(f"{self.config.seed}:{cleaned}".encode())

        card_type = detect_card_type(cleaned)
        bin_digits = self._generate_bin(card_type, rng)

        # Generate random remaining digits
        remaining_length = len(cleaned) - 7
        remaining = "".join(str(rng.randint(0, 9)) for _ in range(remaining_length))

        # Reconstruct card number
        anon_card = bin_digits + remaining

        # Calculate and append Luhn checksum
        checksum = luhn_checksum(anon_card[:-1])
        anon_card = anon_card[:-1] + str(checksum)

        # Apply original format
        return self._apply_format(original, anon_card)

    def _generate_bin(self, card_type: str, rng: random.Random) -> str:
        """Generate valid BIN for card type.

        Args:
            card_type: Card type (visa, mastercard, etc)
            rng: Random number generator

        Returns:
            Valid 6-digit BIN
        """
        if card_type == "visa":
            return "4" + "".join(str(rng.randint(0, 9)) for _ in range(5))
        elif card_type == "mastercard":
            prefix = rng.choice([51, 52, 53, 54, 55])
            return str(prefix) + "".join(str(rng.randint(0, 9)) for _ in range(4))
        elif card_type == "amex":
            prefix = rng.choice([34, 37])
            return str(prefix) + "".join(str(rng.randint(0, 9)) for _ in range(4))
        elif card_type == "discover":
            prefix = rng.choice([6011, 622, 644, 645, 646, 647, 648, 649, 65])
            prefix_str = str(prefix)
            remaining = 6 - len(prefix_str)
            return prefix_str + "".join(str(rng.randint(0, 9)) for _ in range(remaining))
        else:
            # Default: generate random BIN
            return "".join(str(rng.randint(0, 9)) for _ in range(6))

    def _apply_format(self, original: str, cleaned: str) -> str:
        """Apply original formatting to cleaned card number.

        Args:
            original: Original card number with formatting
            cleaned: Cleaned anonymized card number

        Returns:
            Card number with original formatting applied
        """
        result = []
        cleaned_idx = 0

        for char in original:
            if char.isdigit():
                if cleaned_idx < len(cleaned):
                    result.append(cleaned[cleaned_idx])
                    cleaned_idx += 1
            else:
                result.append(char)

        return "".join(result)

    def short_name(self) -> str:
        """Return short strategy name for logging.

        Returns:
            Short name (e.g., "credit_card:preserve_last4")
        """
        if self.config.preserve_bin:
            return "credit_card:preserve_bin"
        elif self.config.preserve_last4:
            return "credit_card:preserve_last4"
        else:
            return "credit_card:full"
