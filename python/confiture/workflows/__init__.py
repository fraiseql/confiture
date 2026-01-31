"""Confiture workflow orchestration and agent decision support.

This package provides retry logic, recovery strategies, self-healing,
workflow orchestration, and decision trees for automated error handling
in agent-driven operations.
"""

from confiture.workflows.retry import (
    RetryExhausted,
    RetryPolicy,
    with_retry,
)

__all__ = [
    "RetryPolicy",
    "RetryExhausted",
    "with_retry",
]
