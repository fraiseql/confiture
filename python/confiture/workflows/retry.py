"""Retry logic and exponential backoff strategies.

Provides RetryPolicy for implementing resilient operations with
exponential backoff, jitter, and deadline support.
"""

import random
import time
from collections.abc import Callable
from datetime import datetime
from functools import wraps
from typing import Any


class RetryExhausted(Exception):
    """Raised when all retry attempts are exhausted."""

    pass


class RetryPolicy:
    """Configuration for retry behavior.

    Supports exponential backoff with optional jitter and deadline tracking.

    Example:
        >>> policy = RetryPolicy(
        ...     max_attempts=3,
        ...     initial_delay=1.0,
        ...     backoff_factor=2.0,
        ...     jitter=True,
        ... )
        >>> @with_retry(policy)
        ... def risky_operation():
        ...     pass
    """

    def __init__(
        self,
        max_attempts: int,
        initial_delay: float = 1.0,
        backoff_factor: float = 2.0,
        max_delay: float = 60.0,
        jitter: bool = False,
    ) -> None:
        """Initialize retry policy.

        Args:
            max_attempts: Maximum number of attempts
            initial_delay: Initial delay in seconds (default: 1.0)
            backoff_factor: Multiplier for delay (default: 2.0)
            max_delay: Maximum delay in seconds (default: 60.0)
            jitter: Add randomness to delays (default: False)
        """
        self.max_attempts = max_attempts
        self.initial_delay = initial_delay
        self.backoff_factor = backoff_factor
        self.max_delay = max_delay
        self.jitter = jitter

    def get_delay(self, attempt: int) -> float:
        """Calculate delay for given attempt number.

        Args:
            attempt: Attempt number (1-indexed)

        Returns:
            Delay in seconds
        """
        # Exponential backoff: initial_delay * (backoff_factor ^ (attempt - 1))
        delay = self.initial_delay * (self.backoff_factor ** (attempt - 1))

        # Cap at max_delay
        delay = min(delay, self.max_delay)

        # Apply jitter
        if self.jitter:
            delay = delay * random.uniform(0.5, 1.0)

        return delay

    def should_retry(self, attempt: int, deadline: datetime | None = None) -> bool:
        """Determine if should retry.

        Args:
            attempt: Attempt number
            deadline: Optional deadline for retries

        Returns:
            True if should retry, False otherwise
        """
        # Check max attempts
        if attempt >= self.max_attempts:
            return False

        # Check deadline
        return not (deadline and datetime.utcnow() >= deadline)


def with_retry(
    policy: RetryPolicy,
    deadline: datetime | None = None,
    should_retry: Callable[[Exception], bool] | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator for automatic retry with exponential backoff.

    Args:
        policy: RetryPolicy defining retry behavior
        deadline: Optional deadline for all retry attempts
        should_retry: Optional predicate to determine if exception should be retried

    Returns:
        Decorator function

    Example:
        >>> @with_retry(RetryPolicy(max_attempts=3))
        ... def risky_operation():
        ...     pass
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            attempt = 0

            while True:
                attempt += 1

                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    # Check if should retry this exception
                    if should_retry and not should_retry(e):
                        raise

                    # Check if should retry based on policy
                    if not policy.should_retry(attempt, deadline):
                        raise RetryExhausted(
                            f"Exhausted {policy.max_attempts} retry attempts"
                        ) from e

                    # Calculate and apply delay
                    delay = policy.get_delay(attempt)
                    time.sleep(delay)

        return wrapper

    return decorator
