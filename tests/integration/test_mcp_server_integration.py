"""Integration tests for MCPServer - requires PostgreSQL."""

from __future__ import annotations

import pytest


@pytest.mark.integration
def test_mcp_server_integration_skip():
    """Placeholder — integration tests require a live database."""
    pytest.skip("Integration tests require a live PostgreSQL database.")
