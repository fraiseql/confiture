"""The oldest pg_tviews confiture supports is one constant, the one CI runs (#541).

``pg_extension.extversion`` is ``0.1.0`` on every 0.1.0 beta (measured on beta.17,
18 and 19), so the build is read from ``pg_tviews_version()``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from confiture.core import live_catalog
from confiture.exceptions import ConfigurationError

DOCKERFILE = Path(__file__).parents[2] / "ci" / "pg-tviews" / "Dockerfile"


def test_the_minimum_is_the_build_ci_runs() -> None:
    pin = re.search(r"^ARG PG_TVIEWS_REF=v(\S+)$", DOCKERFILE.read_text(), re.MULTILINE)

    assert pin is not None
    assert pin.group(1) == live_catalog.MINIMUM_PG_TVIEWS


@pytest.mark.parametrize(
    ("older", "newer"),
    [
        ("0.1.0-beta.9", "0.1.0-beta.19"),
        ("0.1.0-beta.18", "0.1.0-beta.19"),
        ("0.1.0-alpha.3", "0.1.0-beta.1"),
        ("0.1.0-beta.19", "0.1.0-rc.1"),
        ("0.1.0-rc.2", "0.1.0"),
        ("0.1.0", "0.1.1"),
        ("0.9.0", "0.10.0"),
    ],
)
def test_builds_order_as_releases_do(older: str, newer: str) -> None:
    assert live_catalog.pg_tviews_build(older) < live_catalog.pg_tviews_build(newer)


@pytest.mark.parametrize("text", ["", "0.1", "0.1.0-dev", "v0.1.0", "0.1.0-beta"])
def test_a_build_it_cannot_read_is_none(text: str) -> None:
    assert live_catalog.pg_tviews_build(text) is None


def test_the_minimum_itself_is_supported() -> None:
    assert live_catalog.require_supported_pg_tviews(live_catalog.MINIMUM_PG_TVIEWS) is None


@pytest.mark.parametrize("installed", ["0.1.0-beta.18", "0.1.0-beta.11", None, "0.1.0-dev"])
def test_an_older_or_unreadable_build_is_refused_naming_both(installed: str | None) -> None:
    with pytest.raises(ConfigurationError) as refused:
        live_catalog.require_supported_pg_tviews(installed)

    assert refused.value.error_code == "CONFIG_014"
    assert live_catalog.MINIMUM_PG_TVIEWS in str(refused.value)
    assert (installed or "unknown") in str(refused.value)
