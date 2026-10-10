"""confiture reads pg_tviews through one versioned contract, and refuses any other.

pg_tviews 0.1.0-beta.20 publishes ``tviews.registry`` and
``tviews.pg_tviews_create_or_replace()`` under ``tviews.contract_version()``. A
database whose pg_tviews answers another number, or has no such function (0.1.0-beta.19
and earlier), is refused before anything is read from it or applied to it.
"""

import pytest

from confiture.core import live_catalog
from confiture.exceptions import ConfigurationError


def test_the_contract_confiture_reads_is_accepted() -> None:
    assert (
        live_catalog.require_supported_pg_tviews("0.1.0-beta.26", live_catalog.CONTRACT_VERSION)
        is None
    )


@pytest.mark.parametrize("contract", [0, 2])
def test_another_contract_is_refused_naming_both(contract: int) -> None:
    with pytest.raises(ConfigurationError) as refused:
        live_catalog.require_supported_pg_tviews("0.2.0", contract)

    assert refused.value.error_code == "CONFIG_014"
    assert f"read contract {contract}" in str(refused.value)
    assert f"reads contract {live_catalog.CONTRACT_VERSION}" in str(refused.value)
    assert "0.2.0" in str(refused.value)


@pytest.mark.parametrize("installed", ["0.1.0", None])
def test_a_pg_tviews_without_a_contract_is_refused_with_its_migration(
    installed: str | None,
) -> None:
    """Before 0.1.0-beta.20 ``extversion`` said ``0.1.0`` and there was no contract."""
    with pytest.raises(ConfigurationError) as refused:
        live_catalog.require_supported_pg_tviews(installed, None)

    assert refused.value.error_code == "CONFIG_014"
    assert "has no read contract" in str(refused.value)
    assert "migrate-from-0.1.0.sql" in (refused.value.resolution_hint or "")
    assert (installed or "unknown") in str(refused.value)


@pytest.mark.parametrize(
    "missing",
    [
        ("function_reads", "time_refresh", "uncascaded_table_policies"),
        ("view", "uncascaded_policy", "function_reads"),
    ],
)
def test_a_registry_without_the_columns_confiture_reads_is_refused(
    missing: tuple[str, ...],
) -> None:
    """Contract 1 grows by appended columns: 0.1.0-beta.26 is the first with every one read."""
    with pytest.raises(ConfigurationError) as refused:
        live_catalog.require_supported_pg_tviews(
            "0.1.0-beta.25", live_catalog.CONTRACT_VERSION, missing
        )

    assert refused.value.error_code == "CONFIG_014"
    assert "0.1.0-beta.25" in str(refused.value)
    assert ", ".join(missing) in str(refused.value)
    assert live_catalog.MINIMUM_PG_TVIEWS == "0.1.0-beta.26"
    assert live_catalog.MINIMUM_PG_TVIEWS in str(refused.value)


def test_the_seam_names_the_minimum_and_the_check() -> None:
    """A deploy tool's doctor asks the question the drift gate asks, by public names."""
    from confiture import platform

    assert platform.MINIMUM_PG_TVIEWS == live_catalog.MINIMUM_PG_TVIEWS
    assert callable(platform.require_supported_pg_tviews_on)
