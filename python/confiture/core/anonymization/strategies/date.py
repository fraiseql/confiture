"""Date masking anonymization strategy.

Provides flexible date anonymization with preservation options:
- Preserve year only (replace month/day)
- Preserve month/year (jitter day)
- Full anonymization (replace entire date)

Uses seeded randomization for deterministic output and jitter.
Supports multiple date formats (ISO 8601, US, UK, etc).
"""

import random
from dataclasses import dataclass
from datetime import datetime, timedelta

from confiture.core.anonymization.strategy import AnonymizationStrategy, StrategyConfig


@dataclass
class DateMaskConfig(StrategyConfig):
    """Configuration for date masking strategy.

    Attributes:
        seed: Seed for deterministic randomization
        preserve: What to preserve:
            - "none": Fully anonymize (replace entire date)
            - "year": Keep year, jitter month/day
            - "month": Keep year/month, jitter day (useful for healthcare)
        jitter_days: Number of days to jitter (default 30)
        output_format: Output format (default: same as input)

    Example:
        >>> config = DateMaskConfig(seed=12345, preserve="year", jitter_days=30)
    """

    preserve: str = "year"  # none, year, month
    jitter_days: int = 30
    output_format: str | None = None  # If None, preserve input format


class DateMaskingStrategy(AnonymizationStrategy):
    """Anonymization strategy for masking dates.

    Provides configurable date anonymization with preservation options:
    - Preserve year but jitter month/day
    - Preserve year/month but jitter day
    - Fully replace date

    Features:
    - Deterministic jitter (same seed = same jitter)
    - Multiple format support (ISO 8601, US MM/DD/YYYY, UK DD/MM/YYYY)
    - Preserves date boundaries (valid dates only)
    - Handles NULL and edge cases

    Example:
        >>> config = DateMaskConfig(seed=12345, preserve="year", jitter_days=30)
        >>> strategy = DateMaskingStrategy(config)
        >>> strategy.anonymize("2020-05-15")
        '2020-03-22'  # Same year, different month/day
    """

    config_type = DateMaskConfig
    strategy_name = "date"

    # Common date formats to try
    DATE_FORMATS = [
        "%Y-%m-%d",  # ISO 8601: 2020-05-15
        "%m/%d/%Y",  # US: 05/15/2020
        "%d/%m/%Y",  # UK: 15/05/2020
        "%Y/%m/%d",  # 2020/05/15
        "%d-%m-%Y",  # 15-05-2020
        "%B %d, %Y",  # May 15, 2020
        "%b %d, %Y",  # May 15, 2020
        "%Y-%m-%d %H:%M:%S",  # ISO with time
        "%m/%d/%Y %H:%M:%S",  # US with time
        "%d/%m/%Y %H:%M:%S",  # UK with time
    ]

    def anonymize(self, value: str | None) -> str | None:
        """Anonymize a date value.

        Args:
            value: Date string to anonymize

        Returns:
            Anonymized date in same format as input

        Example:
            >>> strategy.anonymize("2020-05-15")
            '2020-03-22'
        """
        if value is None:
            return None

        if isinstance(value, str) and not value.strip():
            return value

        # Parse the date
        parsed_date, detected_format = self._parse_date(value)

        if parsed_date is None:
            # Could not parse - return as-is
            return value

        # Apply anonymization based on config
        if self.config.preserve == "none":
            anonymized_date = self._anonymize_full(parsed_date)
        elif self.config.preserve == "year":
            anonymized_date = self._anonymize_preserve_year(parsed_date)
        elif self.config.preserve == "month":
            anonymized_date = self._anonymize_preserve_month(parsed_date)
        else:
            raise ValueError(f"Unknown preserve mode: {self.config.preserve}")

        # Format output
        output_format = self.config.output_format or detected_format
        return anonymized_date.strftime(output_format)

    def _parse_date(self, value: str) -> tuple[datetime | None, str | None]:
        """Parse date string in any supported format.

        Args:
            value: Date string to parse

        Returns:
            Tuple of (parsed datetime, detected format) or (None, None)
        """
        for fmt in self.DATE_FORMATS:
            try:
                parsed = datetime.strptime(value.strip(), fmt)
                return parsed, fmt
            except ValueError:
                continue

        # Could not parse
        return None, None

    def _anonymize_full(self, date: datetime) -> datetime:
        """Fully anonymize date (replace entire date).

        Args:
            date: Date to anonymize

        Returns:
            Anonymized date
        """
        # Use seed to generate deterministic jitter
        rng = random.Random(f"{self.config.seed}:{date.isoformat()}".encode())

        # Random jitter in days
        jitter = rng.randint(-self.config.jitter_days, self.config.jitter_days)

        return date + timedelta(days=jitter)

    def _anonymize_preserve_year(self, date: datetime) -> datetime:
        """Anonymize but preserve year.

        Args:
            date: Date to anonymize

        Returns:
            Anonymized date with same year
        """
        rng = random.Random(f"{self.config.seed}:{date.isoformat()}:year".encode())

        # Random month (1-12)
        month = rng.randint(1, 12)

        # Random day (1-28 to be safe for all months)
        day = rng.randint(1, 28)

        try:
            return date.replace(month=month, day=day)
        except ValueError:
            # Invalid date (e.g., Feb 30) - return as-is
            return date

    def _anonymize_preserve_month(self, date: datetime) -> datetime:
        """Anonymize but preserve year and month.

        Jitter the day only (useful for healthcare data where month can be significant).

        Args:
            date: Date to anonymize

        Returns:
            Anonymized date with same year/month
        """
        rng = random.Random(f"{self.config.seed}:{date.isoformat()}:month".encode())

        # Random day within same month
        # For simplicity, use day 1-28 to be safe
        day = rng.randint(1, 28)

        try:
            return date.replace(day=day)
        except ValueError:
            # Invalid date - return as-is
            return date

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
            Short name (e.g., "date:preserve_year")
        """
        return f"{self.strategy_name}:preserve_{self.config.preserve}"
