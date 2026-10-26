"""confiture reads pg_tviews through one versioned contract, and refuses any other.

pg_tviews publishes ``tviews.registry`` and ``tviews.pg_tviews_create_or_replace()``
under ``tviews.contract_version()``; confiture reads contract 2 (pg_tviews
0.1.0-beta.30). A database whose pg_tviews answers another number, or has no such
function (0.1.0-beta.19 and earlier), is refused before anything is read from it or
applied to it.
"""

import pytest

from confiture.core import live_catalog
from confiture.exceptions import ConfigurationError


def test_the_contract_confiture_reads_is_accepted() -> None:
    assert live_catalog.CONTRACT_VERSION == 2
    assert (
        live_catalog.require_supported_pg_tviews("0.1.0-beta.30", live_catalog.CONTRACT_VERSION)
        is None
    )


def test_contract_1_is_refused_with_the_upgrade_that_offers_2() -> None:
    """pg_tviews 0.1.0-beta.27 and earlier offer contract 1: upgrade, then re-register."""
    with pytest.raises(ConfigurationError) as refused:
        live_catalog.require_supported_pg_tviews("0.1.0-beta.27", 1)

    assert refused.value.error_code == "CONFIG_014"
    assert "offers read contract 1; confiture reads contract 2" in str(refused.value)
    hint = refused.value.resolution_hint or ""
    assert "0.1.0-beta.30 or later" in hint
    assert "ALTER EXTENSION pg_tviews UPDATE" in hint
    assert "pg_tviews_reregister_all()" in hint


@pytest.mark.parametrize("contract", [0, 3])
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
    ("installed", "missing"),
    [
        ("0.1.0-beta.30", ("managed_indexes",)),
        ("0.1.0-beta.30", ("options", "view")),
    ],
)
def test_a_registry_without_the_columns_confiture_reads_is_refused(
    installed: str, missing: tuple[str, ...]
) -> None:
    """A contract grows by appended columns: a build lacking one confiture reads is refused."""
    with pytest.raises(ConfigurationError) as refused:
        live_catalog.require_supported_pg_tviews(installed, live_catalog.CONTRACT_VERSION, missing)

    assert refused.value.error_code == "CONFIG_014"
    assert installed in str(refused.value)
    assert ", ".join(missing) in str(refused.value)
    assert live_catalog.MINIMUM_PG_TVIEWS == "0.1.0-beta.30"
    assert live_catalog.MINIMUM_PG_TVIEWS in str(refused.value)


def test_the_column_is_the_gate_not_the_version() -> None:
    """A build that reports 0.1.0-beta.30 without ``managed_indexes`` is refused all the same."""
    assert "managed_indexes" in live_catalog.REGISTRY_COLUMNS
    with pytest.raises(ConfigurationError):
        live_catalog.require_supported_pg_tviews(
            "0.1.0-beta.30", live_catalog.CONTRACT_VERSION, ("managed_indexes",)
        )


def test_the_registry_columns_are_contract_2s() -> None:
    """Contract 2 moved every policy column into ``options``: confiture reads none of them."""
    assert set(live_catalog.REGISTRY_COLUMNS) == {
        "schema",
        "name",
        "query",
        "options",
        "view",
        "managed_indexes",
    }


def test_the_seam_names_the_minimum_and_the_check() -> None:
    """A deploy tool's doctor asks the question the drift gate asks, by public names."""
    from confiture import platform

    assert platform.MINIMUM_PG_TVIEWS == live_catalog.MINIMUM_PG_TVIEWS
    assert callable(platform.require_supported_pg_tviews_on)
