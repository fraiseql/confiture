"""``--missing-is-drift``: a routine the source declares and the database has not got.

`missing_from_db` answers two questions and the caller knows which it is asking.
Before a deploy, a routine that is not in the database yet is what is about to be
applied. After one, it is the failure the gate exists to catch. The flag is how a
caller says which, and it ships **off** — because the informational reading is
legitimate and a default that failed deploys would be a behaviour change nobody
asked for (README D3).

The verdict itself is always in the payload, flag or no flag, so a consumer never
reconstructs it from an array.

The flag could not be shipped before the channel stopped lying: on a pristine
database, `missing_from_db` listed a trigger function and every routine outside
`public`. That is the same commit's work, not this one's.
"""

from __future__ import annotations

import pytest

from confiture.core.function_signature_drift import FunctionSignatureDriftDetector
from confiture.core.function_signature_parser import FunctionSignature


def sig(name: str, *params: str, schema: str = "core") -> FunctionSignature:
    return FunctionSignature(schema=schema, name=name, param_types=tuple(params))


def compare(source, live, *, missing_is_drift: bool = False):
    return FunctionSignatureDriftDetector().compare(
        source, live, schemas_checked=["core"], missing_is_drift=missing_is_drift
    )


def test_the_verdict_is_in_the_payload_without_the_flag() -> None:
    report = compare([sig("fn_gone", "bigint")], [])
    assert report.has_undeployed is True
    assert report.to_dict()["has_undeployed"] is True
    assert report.to_dict()["missing_is_drift"] is False


def test_without_the_flag_an_undeployed_routine_is_not_critical() -> None:
    report = compare([sig("fn_gone", "bigint")], [])
    assert report.missing_from_db == ["core.fn_gone(bigint)"]
    assert report.has_drift is False
    assert report.has_critical_drift is False


def test_with_the_flag_an_undeployed_routine_is_critical() -> None:
    report = compare([sig("fn_gone", "bigint")], [], missing_is_drift=True)
    assert report.has_critical_drift is True
    # `has_drift` still means what it meant: a stale overload.
    assert report.has_drift is False


def test_the_flag_changes_nothing_when_everything_is_deployed() -> None:
    both = [sig("fn_here", "bigint")]
    assert compare(both, both, missing_is_drift=True).has_critical_drift is False
    assert compare(both, both, missing_is_drift=True).has_undeployed is False


def test_a_stale_overload_is_critical_either_way() -> None:
    source = [sig("fn", "integer")]
    live = [sig("fn", "integer"), sig("fn", "bigint")]
    for flag in (False, True):
        report = compare(source, live, missing_is_drift=flag)
        assert report.has_critical_drift is True


@pytest.mark.parametrize("flag", [False, True])
def test_the_library_and_the_command_cannot_disagree(flag: bool) -> None:
    """The verdict is a field on the report, not a branch in a formatter, so a
    library consumer gets the same answer ``migrate validate`` prints."""
    report = compare([sig("fn_gone", "bigint")], [], missing_is_drift=flag)
    assert report.has_critical_drift is (report.has_drift or (flag and report.has_undeployed))
