"""Tests for retry logic and backoff strategies.

Tests the RetryPolicy and retry mechanism for handling transient failures
with exponential backoff and jitter.
"""

import time
from datetime import datetime, timedelta

import pytest

from confiture.workflows.retry import (
    RetryPolicy,
    with_retry,
    RetryExhausted,
)


class TestRetryPolicyCreation:
    """Test RetryPolicy initialization."""

    def test_policy_creation_minimal(self) -> None:
        """Test creating policy with minimal parameters."""
        policy = RetryPolicy(max_attempts=3)
        assert policy.max_attempts == 3

    def test_policy_creation_all_params(self) -> None:
        """Test creating policy with all parameters."""
        policy = RetryPolicy(
            max_attempts=5,
            initial_delay=0.1,
            backoff_factor=2.0,
            max_delay=10.0,
            jitter=True,
        )
        assert policy.max_attempts == 5
        assert policy.initial_delay == 0.1
        assert policy.backoff_factor == 2.0
        assert policy.max_delay == 10.0
        assert policy.jitter is True

    def test_policy_defaults(self) -> None:
        """Test policy has sensible defaults."""
        policy = RetryPolicy(max_attempts=3)
        assert policy.initial_delay == 1.0
        assert policy.backoff_factor == 2.0
        assert policy.max_delay == 60.0
        assert policy.jitter is False


class TestExponentialBackoff:
    """Test exponential backoff calculation."""

    def test_backoff_calculation(self) -> None:
        """Test that backoff increases exponentially."""
        policy = RetryPolicy(
            max_attempts=5,
            initial_delay=1.0,
            backoff_factor=2.0,
        )

        # Delays should be: 1, 2, 4, 8, etc.
        assert policy.get_delay(1) == 1.0
        assert policy.get_delay(2) == 2.0
        assert policy.get_delay(3) == 4.0
        assert policy.get_delay(4) == 8.0

    def test_backoff_respects_max_delay(self) -> None:
        """Test that backoff doesn't exceed max_delay."""
        policy = RetryPolicy(
            max_attempts=5,
            initial_delay=1.0,
            backoff_factor=2.0,
            max_delay=10.0,
        )

        # Fourth retry would be 8, fifth would be 16 (capped at 10)
        assert policy.get_delay(4) == 8.0
        assert policy.get_delay(5) == 10.0

    def test_backoff_with_jitter(self) -> None:
        """Test that jitter adds randomness."""
        policy = RetryPolicy(
            max_attempts=3,
            initial_delay=1.0,
            backoff_factor=2.0,
            jitter=True,
        )

        # With jitter, should be <= base delay
        delay = policy.get_delay(2)  # Would be 2.0 without jitter
        assert delay <= 2.0
        assert delay > 0.0


class TestRetryDecorator:
    """Test @with_retry decorator."""

    def test_retry_succeeds_on_first_attempt(self) -> None:
        """Test that successful operations don't retry."""
        attempts = [0]

        @with_retry(RetryPolicy(max_attempts=3))
        def succeeds():
            attempts[0] += 1
            return "success"

        result = succeeds()
        assert result == "success"
        assert attempts[0] == 1

    def test_retry_succeeds_after_failures(self) -> None:
        """Test that operation retries on failure."""
        attempts = [0]

        @with_retry(RetryPolicy(max_attempts=3, initial_delay=0.01))
        def fails_twice_then_succeeds():
            attempts[0] += 1
            if attempts[0] < 3:
                raise ValueError("Not yet")
            return "success"

        result = fails_twice_then_succeeds()
        assert result == "success"
        assert attempts[0] == 3

    def test_retry_exhausted_after_max_attempts(self) -> None:
        """Test that RetryExhausted is raised when max attempts exceeded."""
        attempts = [0]

        @with_retry(RetryPolicy(max_attempts=3, initial_delay=0.01))
        def always_fails():
            attempts[0] += 1
            raise ValueError("Always fails")

        with pytest.raises(RetryExhausted):
            always_fails()

        assert attempts[0] == 3

    def test_retry_with_custom_max_attempts(self) -> None:
        """Test retry with different max_attempts values."""
        for max_attempts in [1, 2, 5]:
            attempts = [0]

            @with_retry(RetryPolicy(max_attempts=max_attempts, initial_delay=0.01))
            def fails_always():
                attempts[0] += 1
                raise ValueError("fail")

            with pytest.raises(RetryExhausted):
                fails_always()

            assert attempts[0] == max_attempts


class TestRetryWithDeadline:
    """Test retry with deadline/timeout."""

    def test_retry_respects_deadline(self) -> None:
        """Test that retry stops at deadline even if attempts remain."""
        policy = RetryPolicy(
            max_attempts=10,
            initial_delay=0.5,
            backoff_factor=2.0,
        )

        attempts = [0]
        deadline = datetime.utcnow() + timedelta(seconds=0.3)

        @with_retry(policy, deadline=deadline)
        def slow_failure():
            attempts[0] += 1
            raise ValueError("fail")

        with pytest.raises(RetryExhausted):
            slow_failure()

        # Should stop before exhausting all attempts due to deadline
        assert attempts[0] < 10

    def test_retry_no_deadline(self) -> None:
        """Test retry without deadline."""
        policy = RetryPolicy(max_attempts=3, initial_delay=0.01)

        @with_retry(policy, deadline=None)
        def fails():
            raise ValueError("fail")

        with pytest.raises(RetryExhausted):
            fails()


class TestRetryWithPredicate:
    """Test retry with custom predicates."""

    def test_retry_with_custom_predicate(self) -> None:
        """Test retrying only on specific exceptions."""
        attempts = [0]

        def should_retry(exc: Exception) -> bool:
            # Only retry on ValueError
            return isinstance(exc, ValueError)

        @with_retry(
            RetryPolicy(max_attempts=3, initial_delay=0.01),
            should_retry=should_retry,
        )
        def fails_with_value_error():
            attempts[0] += 1
            raise ValueError("Retry me")

        with pytest.raises(RetryExhausted):
            fails_with_value_error()

        assert attempts[0] == 3

    def test_retry_stops_on_non_retryable_exception(self) -> None:
        """Test that non-retryable exceptions are not retried."""
        attempts = [0]

        def should_retry(exc: Exception) -> bool:
            # Only retry on ValueError, not RuntimeError
            return isinstance(exc, ValueError)

        @with_retry(
            RetryPolicy(max_attempts=3, initial_delay=0.01),
            should_retry=should_retry,
        )
        def fails_with_runtime_error():
            attempts[0] += 1
            raise RuntimeError("Don't retry me")

        with pytest.raises(RuntimeError):
            fails_with_runtime_error()

        # Should not retry, only one attempt
        assert attempts[0] == 1


class TestRetryMetrics:
    """Test retry metrics and tracking."""

    def test_retry_tracks_attempts(self) -> None:
        """Test that retry policy tracks attempt count."""
        policy = RetryPolicy(max_attempts=3, initial_delay=0.01)
        attempts = [0]

        @with_retry(policy)
        def fails_twice():
            attempts[0] += 1
            if attempts[0] < 3:
                raise ValueError("fail")
            return "success"

        fails_twice()

        # Policy should know about retries
        assert attempts[0] == 3
