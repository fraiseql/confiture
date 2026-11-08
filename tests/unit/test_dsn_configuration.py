"""``cli.dsn.configuration``: a URL replaces a named config's connection, nothing else (#825)."""

from pathlib import Path

import pytest

from confiture.cli.dsn import configuration
from confiture.exceptions import ConfigurationError

URL = "postgresql://localhost/test"


@pytest.fixture
def config(tmp_path: Path) -> Path:
    path = tmp_path / "env.yaml"
    path.write_text(
        "name: production\n"
        "database_url: postgresql://localhost/nonexistent\n"
        "database:\n  host: elsewhere\n"
        "ssh_tunnel:\n  host: bastion\n  user: ops\n"
        "migration:\n  tracking_table: public.ledger\n"
    )
    return path


def test_no_url_reads_the_file(config: Path) -> None:
    data = configuration(None, config, config_explicit=True)
    assert data["database_url"].endswith("/nonexistent")


def test_a_url_with_a_named_config_replaces_its_connection_only(config: Path) -> None:
    data = configuration(URL, config, config_explicit=True)
    assert data["database_url"] == URL
    assert "database" not in data
    assert "ssh_tunnel" not in data
    assert data["migration"] == {"tracking_table": "public.ledger"}


def test_a_url_with_a_default_config_is_the_url_alone(config: Path) -> None:
    assert configuration(URL, config, config_explicit=False) == {"database_url": URL}


def test_a_url_with_no_config_is_the_url_alone() -> None:
    assert configuration(URL, None, config_explicit=True) == {"database_url": URL}


def test_no_url_and_no_config_is_refused() -> None:
    with pytest.raises(ConfigurationError) as raised:
        configuration(None, None, config_explicit=False)
    assert raised.value.error_code == "CONFIG_010"


def test_a_named_config_that_is_missing_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError) as raised:
        configuration(URL, tmp_path / "absent.yaml", config_explicit=True)
    assert raised.value.error_code == "CONFIG_004"
