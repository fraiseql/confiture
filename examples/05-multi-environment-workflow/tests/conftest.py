"""Pytest configuration and shared fixtures

Provides test fixtures for database testing.
"""

import os
import pytest


@pytest.fixture
def test_db():
    """Provide test database connection string.

    This fixture provides the PostgreSQL connection string for tests.
    It reads from environment variables to support different environments.

    Environment variables:
        PGHOST: Database host (default: localhost)
        PGPORT: Database port (default: 5432)
        PGDATABASE: Database name (default: confiture_ci)
        PGUSER: Database user (default: postgres)
        PGPASSWORD: Database password (default: postgres)

    Returns:
        str: PostgreSQL connection string
    """
    host = os.getenv('PGHOST', 'localhost')
    port = os.getenv('PGPORT', '5432')
    database = os.getenv('PGDATABASE', 'confiture_ci')
    user = os.getenv('PGUSER', 'postgres')
    password = os.getenv('PGPASSWORD', 'postgres')

    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


@pytest.fixture
def test_env():
    """Provide test environment name.

    Returns:
        str: Environment name (default: ci)
    """
    return os.getenv('TEST_ENV', 'ci')


# Pytest configuration
def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests (deselect with '-m \"not integration\"')"
    )
    config.addinivalue_line(
        "markers", "unit: marks tests as unit tests"
    )
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
