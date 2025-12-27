"""Strategy factory for creating strategies from profile configurations.

Provides:
- Profile-based strategy creation
- Column-to-strategy mapping
- Strategy suggestion engine
- Factory caching and optimization
- Configuration validation

Enables declarative strategy configuration via profiles.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from confiture.core.anonymization.strategy import AnonymizationStrategy, StrategyConfig
from confiture.core.anonymization.registry import StrategyRegistry
from confiture.core.anonymization.composer import StrategyComposer, CompositionConfig


@dataclass
class StrategyProfile:
    """Configuration profile mapping columns to strategies.

    Attributes:
        name: Profile name (e.g., "ecommerce", "healthcare")
        seed: Global seed for all strategies (can be overridden per column)
        columns: Dict mapping column name to strategy name/config
        defaults: Default strategy for unmapped columns

    Example:
        >>> profile = StrategyProfile(
        ...     name="ecommerce",
        ...     seed=12345,
        ...     columns={
        ...         "customer_name": "name:firstname_lastname",
        ...         "email": "email_mask",
        ...         "phone": "phone_mask"
        ...     }
        ... )
    """

    name: str
    seed: int = 0
    columns: Dict[str, str] = field(default_factory=dict)
    defaults: str = "preserve"


class StrategyFactory:
    """Factory for creating strategies from profiles.

    Creates strategy instances based on profile configuration,
    with caching and validation.

    Features:
    - Profile-based strategy creation
    - Column mapping
    - Strategy caching
    - Configuration validation
    - Suggestion engine

    Example:
        >>> profile = StrategyProfile(
        ...     name="ecommerce",
        ...     columns={"name": "name", "email": "email"}
        ... )
        >>> factory = StrategyFactory(profile)
        >>> strategy = factory.get_strategy("name")
        >>> anonymized = strategy.anonymize("John Doe")
    """

    def __init__(self, profile: StrategyProfile):
        """Initialize factory with profile.

        Args:
            profile: Strategy profile configuration
        """
        self.profile = profile
        self._cache = {}
        self._validate_profile()

    def get_strategy(self, column_name: str) -> AnonymizationStrategy:
        """Get strategy for column.

        Args:
            column_name: Name of column

        Returns:
            AnonymizationStrategy instance

        Raises:
            ValueError: If strategy not found
        """
        # Check cache first
        if column_name in self._cache:
            return self._cache[column_name]

        # Get strategy name from profile
        strategy_name = self.profile.columns.get(
            column_name, self.profile.defaults
        )

        # Create strategy
        try:
            strategy = StrategyRegistry.get(
                strategy_name, {"seed": self.profile.seed}
            )
            self._cache[column_name] = strategy
            return strategy
        except ValueError as e:
            raise ValueError(
                f"Failed to create strategy for column '{column_name}': {e}"
            ) from e

    def get_strategies(
        self, column_names: List[str]
    ) -> Dict[str, AnonymizationStrategy]:
        """Get strategies for multiple columns.

        Args:
            column_names: List of column names

        Returns:
            Dict mapping column name to strategy
        """
        return {col: self.get_strategy(col) for col in column_names}

    def anonymize(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Anonymize entire data dictionary using profile.

        Args:
            data: Dict mapping column names to values

        Returns:
            Dict with anonymized values

        Example:
            >>> data = {"name": "John", "email": "john@example.com"}
            >>> anonymized = factory.anonymize(data)
        """
        result = {}

        for column_name, value in data.items():
            strategy = self.get_strategy(column_name)
            result[column_name] = strategy.anonymize(value)

        return result

    def _validate_profile(self) -> None:
        """Validate profile configuration.

        Raises:
            ValueError: If profile is invalid
        """
        if not self.profile.name:
            raise ValueError("Profile must have a name")

        # Validate strategy names exist
        all_strategies = list(self.profile.columns.values()) + [
            self.profile.defaults
        ]

        for strategy_name in all_strategies:
            if not StrategyRegistry.is_registered(strategy_name):
                raise ValueError(f"Unknown strategy: {strategy_name}")

    def list_column_strategies(self) -> Dict[str, str]:
        """List all column-to-strategy mappings.

        Returns:
            Dict mapping column names to strategy names
        """
        return dict(self.profile.columns)

    def clear_cache(self) -> None:
        """Clear strategy cache (useful for testing)."""
        self._cache.clear()


class StrategySuggester:
    """Suggests appropriate strategies based on column characteristics.

    Analyzes column names, data types, and sample values to suggest
    anonymization strategies.

    Features:
    - Pattern-based column analysis
    - Data type detection
    - Multi-strategy suggestion
    - Confidence scoring
    """

    # Patterns for column name detection
    NAME_PATTERNS = [
        "name", "fullname", "full_name", "firstname", "first_name",
        "lastname", "last_name", "personname", "person_name"
    ]
    EMAIL_PATTERNS = ["email", "email_address", "e_mail", "mail"]
    PHONE_PATTERNS = ["phone", "telephone", "mobile", "cellphone", "cell_phone"]
    ADDRESS_PATTERNS = ["address", "street", "city", "state", "zip", "postal"]
    DATE_PATTERNS = ["date", "born", "birthday", "birthdate", "dob", "created"]
    CC_PATTERNS = ["credit", "card", "cc", "cardnumber", "card_number"]
    IP_PATTERNS = ["ip", "ipaddress", "ip_address", "server"]

    def suggest(
        self, column_name: str, sample_value: str | None = None
    ) -> List[tuple]:
        """Suggest strategies for column.

        Args:
            column_name: Name of column
            sample_value: Optional sample value for analysis

        Returns:
            List of (strategy_name, confidence) tuples, sorted by confidence
        """
        suggestions = []

        # Analyze column name
        col_lower = column_name.lower()

        if any(p in col_lower for p in self.NAME_PATTERNS):
            suggestions.append(("name:firstname_lastname", 0.95))

        if any(p in col_lower for p in self.EMAIL_PATTERNS):
            suggestions.append(("email", 0.95))

        if any(p in col_lower for p in self.PHONE_PATTERNS):
            suggestions.append(("phone", 0.90))

        if any(p in col_lower for p in self.ADDRESS_PATTERNS):
            suggestions.append(("address", 0.85))

        if any(p in col_lower for p in self.DATE_PATTERNS):
            suggestions.append(("date", 0.85))

        if any(p in col_lower for p in self.CC_PATTERNS):
            suggestions.append(("credit_card", 0.90))

        if any(p in col_lower for p in self.IP_PATTERNS):
            suggestions.append(("ip_address", 0.85))

        # Analyze sample value if provided
        if sample_value:
            value_suggestions = self._analyze_value(sample_value)
            suggestions.extend(value_suggestions)

        # Remove duplicates, keep highest confidence
        seen = {}
        for strategy, confidence in suggestions:
            if strategy not in seen or confidence > seen[strategy]:
                seen[strategy] = confidence

        # Sort by confidence descending
        return sorted(
            [(s, c) for s, c in seen.items()],
            key=lambda x: x[1],
            reverse=True
        )

    def _analyze_value(self, value: str) -> List[tuple]:
        """Analyze sample value for pattern matching.

        Args:
            value: Sample value

        Returns:
            List of (strategy_name, confidence) tuples
        """
        suggestions = []

        # Check for email pattern
        if "@" in value and "." in value:
            suggestions.append(("email", 0.85))

        # Check for phone pattern (simple)
        if any(c.isdigit() for c in value) and len(value) >= 10:
            if "-" in value or "(" in value or ")" in value:
                suggestions.append(("phone", 0.75))

        # Check for IP pattern
        if value.count(".") == 3:
            parts = value.split(".")
            if all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
                suggestions.append(("ip_address", 0.90))

        # Check for credit card pattern
        if all(c.isdigit() or c in " -" for c in value):
            cleaned = value.replace(" ", "").replace("-", "")
            if 13 <= len(cleaned) <= 19:
                suggestions.append(("credit_card", 0.70))

        return suggestions

    def create_profile(
        self, name: str, columns: List[str], seed: int = 0
    ) -> StrategyProfile:
        """Create profile based on column suggestions.

        Args:
            name: Profile name
            columns: List of column names
            seed: Global seed

        Returns:
            StrategyProfile with suggested strategies
        """
        column_map = {}

        for col in columns:
            suggestions = self.suggest(col)
            if suggestions:
                # Use strategy with highest confidence
                strategy_name = suggestions[0][0]
                column_map[col] = strategy_name
            else:
                # Default to preserve
                column_map[col] = "preserve"

        return StrategyProfile(
            name=name,
            seed=seed,
            columns=column_map,
            defaults="preserve"
        )
