"""Differential privacy anonymization strategy.

Provides mathematical privacy guarantee using noise addition. Adds carefully
calibrated random noise to numerical data to prevent individual re-identification.

Features:
- Mathematical privacy guarantee (epsilon-delta privacy)
- Noise calibration: Scale noise to data sensitivity
- Budget tracking: Track privacy budget consumption
- Configurable mechanisms: Laplace, Gaussian, Exponential
- Utility-privacy tradeoff: Control accuracy vs privacy

Mathematical Background:
    Differential privacy: For any two adjacent datasets D and D',
    P(M(D) ∈ S) ≤ e^ε * P(M(D') ∈ S) + δ

    Where:
    - M: privacy mechanism (adds noise)
    - ε (epsilon): privacy parameter (lower = more private)
    - δ (delta): failure probability (usually ≈ 1/n)
    - S: set of possible outputs

Use Cases:
    - Statistical aggregate queries (average age, sum of purchases)
    - Census data (count distributions)
    - Salary data (ranges, distributions)
    - Location data (geographic aggregates)
    - Sensor data (aggregate statistics)

Privacy Levels:
    ε = 10: Strong privacy, significant noise, utility degraded
    ε = 1:  Very strong privacy, significant noise impact
    ε = 0.1: Extremely strong privacy, high noise, low utility
    ε = ∞: No privacy (no noise added)

Example:
    Age: 35 → 35 + noise ≈ 37.2 (with ε=1, Δf=1)
    Salary: 50000 → 50000 + noise ≈ 50241.5 (with ε=0.5, Δf=1000)

Mechanisms:
    - Laplace: Fast, simple, works well for small datasets
    - Gaussian: Better utility for large datasets
    - Exponential: For exponential-family distributions

NOT suitable for:
    - Individual records (differential privacy is for aggregates)
    - Categorical data (use hashing instead)
    - Small datasets (noise makes utility poor)
    - Real-time applications (budget tracking needed)
    - High-accuracy requirements (inherent noise trade-off)
"""

import random
from dataclasses import dataclass
from typing import Any

from confiture.core.anonymization.strategy import (
    AnonymizationStrategy,
    StrategyConfig,
)


@dataclass
class DifferentialPrivacyConfig(StrategyConfig):
    """Configuration for DifferentialPrivacyStrategy.

    Attributes:
        epsilon: Privacy budget (lower = more private)
        delta: Failure probability (usually 1/dataset_size)
        mechanism: Noise mechanism ('laplace', 'gaussian', 'exponential')
        data_type: Type of data ('numeric', 'categorical', 'location')
        sensitivity: Data sensitivity (max change in one record)
        budget_total: Total privacy budget available
        budget_per_value: Budget per anonymization operation
    """

    epsilon: float = 1.0
    """Privacy budget (lower = more private, 0.1-10 typical)."""

    delta: float = 1e-5
    """Failure probability (typically 1/dataset_size)."""

    mechanism: str = "laplace"
    """Noise mechanism: laplace, gaussian, exponential."""

    data_type: str = "numeric"
    """Type of data: numeric, categorical, location."""

    sensitivity: float = 1.0
    """Data sensitivity (max change from one record)."""

    budget_total: float = 10.0
    """Total privacy budget available."""

    budget_per_value: float = 0.1
    """Budget consumed per anonymization operation."""


class DifferentialPrivacyStrategy(AnonymizationStrategy):
    """Differential privacy using noise addition.

    Provides formal mathematical privacy guarantee by adding noise to
    numerical data. Suitable for aggregate data and statistical queries,
    NOT for individual records.

    Features:
        - Math privacy: ε-δ differential privacy guarantee
        - Noise calibration: Automatic scale to data
        - Budget tracking: Monitor privacy budget
        - Mechanism choice: Laplace, Gaussian, Exponential
        - Configurable: Control privacy-utility tradeoff

    Privacy Mathematics:
        Differential privacy ensures:
        P(M(D) ∈ S) ≤ e^ε * P(M(D') ∈ S) + δ

        Interpretation:
        - Small ε: Difficult to determine if specific person in data
        - Large ε: Easy to determine presence
        - ε = 1: Strong but not extreme privacy
        - ε = 10: Weaker privacy, less noise

    How It Works:
        1. Calculate data sensitivity (max change from one record)
        2. Calculate noise scale based on ε and sensitivity
        3. Sample noise from chosen distribution
        4. Add noise to value
        5. Track privacy budget consumption

    Privacy Budget:
        Each anonymization consumes budget:
        budget_remaining -= budget_per_value

        When budget exhausted: Stop anonymization or reject operations

    NOT Suitable For:
        - Individual PII (use hashing or FPE)
        - Identifying records (differential privacy for aggregates)
        - Categorical data (use hashing)
        - Exact values needed (noise decreases accuracy)
        - Real-time systems (budget tracking overhead)

    Suitable For:
        - Statistical queries (avg age, sum amounts)
        - Census data (population counts)
        - Aggregate salary data (salary ranges, distributions)
        - Location heatmaps (aggregate geographic data)
        - Sensor networks (aggregate sensor readings)

    Example:
        >>> config = DifferentialPrivacyConfig(
        ...     epsilon=1.0,
        ...     delta=1e-5,
        ...     mechanism='laplace',
        ...     data_type='numeric',
        ...     sensitivity=1.0,
        ...     budget_total=10.0,
        ...     budget_per_value=0.1
        ... )
        >>> strategy = DifferentialPrivacyStrategy(config)
        >>>
        >>> # Anonymize numeric values
        >>> values = [35, 42, 28, 55]  # Ages
        >>> anonymized = [strategy.anonymize(v) for v in values]
        >>> # [36.2, 40.8, 27.5, 56.1] (with noise added)
        >>>
        >>> # Budget tracking
        >>> print(f"Budget remaining: {strategy.budget_remaining:.1f}")
        >>> # Budget remaining: 9.6
    """

    budget_remaining: float = 0.0
    """Remaining privacy budget (decreases as values processed)."""

    def __init__(self, config: DifferentialPrivacyConfig | None = None):
        """Initialize differential privacy strategy.

        Args:
            config: DifferentialPrivacyConfig instance

        Raises:
            ValueError: If configuration invalid
        """
        config = config or DifferentialPrivacyConfig()
        super().__init__(config)
        self.config: DifferentialPrivacyConfig = config
        self.budget_remaining = config.budget_total
        self._validate_config()

    def _validate_config(self) -> None:
        """Validate configuration values.

        Raises:
            ValueError: If invalid values
        """
        if self.config.epsilon <= 0:
            raise ValueError("Epsilon must be positive")

        if self.config.delta < 0 or self.config.delta >= 1:
            raise ValueError("Delta must be in [0, 1)")

        if self.config.sensitivity <= 0:
            raise ValueError("Sensitivity must be positive")

        if self.config.mechanism not in {"laplace", "gaussian", "exponential"}:
            raise ValueError("Mechanism must be laplace, gaussian, or exponential")

        if self.config.data_type not in {"numeric", "categorical", "location"}:
            raise ValueError("Data type must be numeric, categorical, or location")

    def anonymize(self, value: Any) -> Any:
        """Add noise to value using differential privacy.

        Args:
            value: Numeric value to anonymize

        Returns:
            Noisy value (float)

        Raises:
            ValueError: If value is not numeric or privacy budget exhausted
        """
        # Check budget
        if self.budget_remaining <= 0:
            raise ValueError(
                "Privacy budget exhausted. Cannot anonymize more values."
            )

        # Handle NULL
        if value is None:
            return None

        # Validate numeric
        try:
            numeric_value = float(value)
        except (TypeError, ValueError) as e:
            raise ValueError(
                f"DifferentialPrivacyStrategy only works with numeric values, "
                f"got {type(value).__name__}: {value}"
            ) from e

        # Calculate noise scale
        noise_scale = self._calculate_noise_scale()

        # Sample noise
        noise = self._sample_noise(noise_scale)

        # Consume budget
        self.budget_remaining -= self.config.budget_per_value

        # Return noisy value
        return numeric_value + noise

    def _calculate_noise_scale(self) -> float:
        """Calculate scale for noise distribution.

        Scale depends on:
        - Epsilon (privacy parameter)
        - Sensitivity (max change from one record)
        - Mechanism type

        Returns:
            Scale for noise distribution
        """
        # Scale = Δf / ε
        # Where Δf is sensitivity, ε is privacy budget
        scale = self.config.sensitivity / self.config.epsilon

        return scale

    def _sample_noise(self, scale: float) -> float:
        """Sample noise from chosen distribution.

        Args:
            scale: Scale parameter for distribution

        Returns:
            Sampled noise value
        """
        if self.config.mechanism == "laplace":
            # Laplace distribution: symmetric around 0
            # Variance = 2 * scale^2
            u = random.uniform(-0.5, 0.5)
            noise = -scale * (1 if u > 0 else -1) * \
                    sum(1 for _ in range(int(-scale * __import__('math').log(2 * abs(u)))))
            # Simplified: use exponential approximation
            noise = scale * __import__('math').log(random.random()) if random.random() > 0.5 else -scale * __import__('math').log(random.random())
            return noise

        elif self.config.mechanism == "gaussian":
            # Gaussian distribution: normal distribution
            # Variance = 2 * scale^2 / delta (for (ε, δ)-DP)
            import math
            variance = 2 * (scale ** 2) / self.config.delta
            stddev = math.sqrt(variance)
            noise = random.gauss(0, stddev)
            return noise

        elif self.config.mechanism == "exponential":
            # Exponential mechanism: for exponential-family distributions
            scale_exp = 2 * scale / self.config.epsilon
            noise = random.expovariate(1 / scale_exp)
            if random.random() > 0.5:
                noise = -noise
            return noise

        return 0.0

    def validate(self, value: Any) -> bool:
        """Differential privacy only works with numeric values.

        Args:
            value: Value to validate

        Returns:
            True if value is numeric
        """
        try:
            float(value)
            return True
        except (TypeError, ValueError):
            return False

    def validate_comprehensive(
        self,
        value: Any,
        column_name: str = "",
        table_name: str = "",
    ) -> tuple[bool, list[str]]:
        """Comprehensive validation for differential privacy.

        Args:
            value: Value to validate
            column_name: Column name (for error context)
            table_name: Table name (for error context)

        Returns:
            Tuple of (is_valid: bool, errors: list[str])
        """
        errors = []

        # Check numeric
        try:
            numeric_value = float(value)
            if numeric_value != numeric_value:  # NaN check
                errors.append(
                    f"Column {table_name}.{column_name}: "
                    f"NaN value cannot be anonymized"
                )
        except (TypeError, ValueError):
            errors.append(
                f"Column {table_name}.{column_name}: "
                f"DifferentialPrivacyStrategy requires numeric values, "
                f"got {type(value).__name__}"
            )

        # Check budget
        if self.budget_remaining <= 0:
            errors.append(
                f"Column {table_name}.{column_name}: "
                f"Privacy budget exhausted (remaining: {self.budget_remaining:.1f})"
            )

        # Check epsilon validity
        if self.config.epsilon > 10:
            errors.append(
                f"Column {table_name}.{column_name}: "
                f"Epsilon {self.config.epsilon} is high (privacy may be weak)"
            )

        return len(errors) == 0, errors

    @property
    def is_reversible(self) -> bool:
        """Differential privacy is irreversible.

        Returns:
            False (noise is irreversible)
        """
        return False

    def get_budget_status(self) -> dict[str, float]:
        """Get privacy budget status.

        Returns:
            Dict with budget information
        """
        return {
            "total": self.config.budget_total,
            "remaining": self.budget_remaining,
            "consumed": self.config.budget_total - self.budget_remaining,
            "percentage": (
                100
                * (self.config.budget_total - self.budget_remaining)
                / self.config.budget_total
            ),
        }
