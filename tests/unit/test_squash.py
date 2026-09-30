"""The parts of ``migrate squash`` that need no database (#539)."""

from __future__ import annotations

import pytest

from confiture.core.squash import archived_digest, baseline_version, usable_version


@pytest.mark.parametrize(
    ("through", "later", "expected"),
    [
        ("20260102000000", ["20260103000000"], "20260102000001"),
        ("20261231235959", [], "20270101000000"),
        ("007", ["010"], "008"),
        ("099", [], "100"),
    ],
)
def test_the_baseline_takes_the_next_version_after_the_cut(
    through: str, later: list[str], expected: str
) -> None:
    assert baseline_version(through, later) == expected


@pytest.mark.parametrize(
    ("through", "later"),
    [
        ("20260102000000", ["20260102000001"]),
        ("002", ["003"]),
        ("v2", ["v3"]),
    ],
)
def test_no_free_version_is_none(through: str, later: list[str]) -> None:
    assert baseline_version(through, later) is None


def test_a_given_version_must_sort_between_the_cut_and_the_next(tmp_path) -> None:
    assert usable_version("002a", "002", ["003"])
    assert not usable_version("002", "002", ["003"])
    assert not usable_version("003", "002", ["003"])
    assert not usable_version("001", "002", ["003"])
    assert usable_version("20260102000001", "20260102000000", [])


def test_the_digest_is_the_versions_and_checksums_whatever_their_order() -> None:
    rows = [("002", "b" * 64), ("001", "a" * 64)]

    assert archived_digest(rows) == archived_digest(list(reversed(rows)))
    assert archived_digest(rows) != archived_digest([("001", "a" * 64), ("002", "c" * 64)])
    assert archived_digest(rows) != archived_digest([("001", "a" * 64)])


def test_a_missing_checksum_is_part_of_the_digest() -> None:
    assert archived_digest([("001", None)]) != archived_digest([("001", "")])
