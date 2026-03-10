"""Integration tests for StubGenerator - requires PostgreSQL."""

from __future__ import annotations

import pytest


@pytest.mark.integration
def test_stub_generator_integration_skip():
    """Placeholder — integration tests require a live database."""
    pytest.skip("Integration tests require a live PostgreSQL database.")
