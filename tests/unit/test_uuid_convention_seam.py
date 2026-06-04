"""Convention seam between confiture and fraiseql-uuid (ECO-rec2).

The FraiseQL stack's structured pattern-UUID convention — the v4-compliant
``{table}{type}-{func}-4{scen}-8{...}-{inst}`` encoding — has **one** canonical
home: ``fraiseql-uuid`` (in fraiseql-seed). Confiture's seed-validation only does
generic RFC-4122 *format* checks and deliberately keeps **no** parallel copy of
that convention; the old ``uuid_patterns.py`` / ``uuid_validator.py`` island was
deleted (P04b, commit caf0153).

These guards keep that division honest:

* The regression half (always runs) asserts confiture's check stays a generic
  RFC-4122 matcher and that no parallel structured-pattern definition creeps back
  into confiture's source.
* The alignment half (runs only when the opt-in ``[seed-uuid]`` extra is
  installed) asserts ``fraiseql-uuid`` owns the structured convention and that the
  two libraries occupy *different lanes*: confiture validates format (a superset),
  fraiseql-uuid validates structure (a subset).

End-to-end workflow ("confiture build → fraiseql-data seed → confiture
seed-validate") is documented in ``docs/guides/prep-seed-validation.md``.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest

from confiture.core.seed_validation.prep_seed.level_1_seed_files import Level1SeedValidator

# A canonical structured UUID (fraiseql-uuid Pattern: table=012345, type=21, ...).
STRUCTURED_UUID = "01234521-0000-4000-8000-000000000001"
# Format-valid (RFC-4122) but NOT structured: hex letters in the leading segment.
GENERIC_ONLY_UUID = "abcdef01-0000-4000-8000-000000000001"

# The distinctive fragments of fraiseql-uuid's structured PATTERN_REGEX. If any of
# these reappears in confiture's own source, a parallel copy has crept back in.
_STRUCTURED_SIGNATURES = (r"([0-9]{6})([0-9]{2})", r"4([0-9]{3})-8")

_CONFITURE_SRC = Path(__file__).resolve().parents[2] / "python" / "confiture"
_SEED_VALIDATION = _CONFITURE_SRC / "core" / "seed_validation"


# ---------------------------------------------------------------------------
# Regression guards (no fraiseql-uuid required).
# ---------------------------------------------------------------------------


def test_confiture_uuid_check_is_generic_rfc4122() -> None:
    """Confiture's seed UUID check accepts any RFC-4122 UUID — it is not structured."""
    pattern = Level1SeedValidator.VALID_UUID_PATTERN
    # Accepts a random v4 UUID, a structured one, and a format-valid non-structured one.
    assert pattern.fullmatch(str(uuid.uuid4()))
    assert pattern.fullmatch(STRUCTURED_UUID)
    assert pattern.fullmatch(GENERIC_ONLY_UUID)
    # Rejects a malformed UUID (wrong segment lengths).
    assert pattern.fullmatch("0123-45-6789") is None


def test_deleted_uuid_island_stays_deleted() -> None:
    """The parallel UUID-convention island deleted in P04b is not reintroduced."""
    assert not (_SEED_VALIDATION / "uuid_patterns.py").exists()
    assert not (_SEED_VALIDATION / "uuid_validator.py").exists()


def test_no_parallel_structured_pattern_copy_in_confiture() -> None:
    """No confiture source file redefines fraiseql-uuid's structured pattern."""
    offenders: list[str] = []
    for path in _CONFITURE_SRC.rglob("*.py"):
        text = path.read_text()
        if any(sig in text for sig in _STRUCTURED_SIGNATURES):
            offenders.append(str(path.relative_to(_CONFITURE_SRC)))
    assert not offenders, (
        "confiture must not carry a parallel copy of fraiseql-uuid's structured "
        f"pattern convention; found the signature in: {offenders}"
    )


# ---------------------------------------------------------------------------
# Alignment guards (skip unless the opt-in [seed-uuid] extra is installed).
# ---------------------------------------------------------------------------


def test_fraiseql_uuid_is_the_canonical_structured_source() -> None:
    """fraiseql-uuid.Pattern owns the structured convention."""
    fraiseql_uuid = pytest.importorskip("fraiseql_uuid")
    pattern_regex = fraiseql_uuid.Pattern.PATTERN_REGEX
    assert pattern_regex.match(STRUCTURED_UUID), "canonical structured UUID must match"


def test_confiture_and_fraiseql_uuid_occupy_different_lanes() -> None:
    """Confiture validates *format* (superset); fraiseql-uuid validates *structure*.

    A format-valid-but-non-structured UUID is accepted by confiture's generic check
    yet rejected by fraiseql-uuid's structured pattern — proving the two libraries
    are not parallel copies but complementary lanes.
    """
    fraiseql_uuid = pytest.importorskip("fraiseql_uuid")
    structured = fraiseql_uuid.Pattern.PATTERN_REGEX
    confiture_format = Level1SeedValidator.VALID_UUID_PATTERN

    # Confiture accepts both; fraiseql-uuid accepts only the structured one.
    assert confiture_format.fullmatch(STRUCTURED_UUID)
    assert confiture_format.fullmatch(GENERIC_ONLY_UUID)
    assert structured.match(STRUCTURED_UUID)
    assert structured.match(GENERIC_ONLY_UUID) is None


def test_structured_signatures_are_actually_fraiseql_uuids() -> None:
    """The signatures the regression guard forbids really are fraiseql-uuid's."""
    fraiseql_uuid = pytest.importorskip("fraiseql_uuid")
    source = re.sub(r"\s+", "", fraiseql_uuid.Pattern.PATTERN_REGEX.pattern)
    for sig in _STRUCTURED_SIGNATURES:
        assert re.sub(r"\s+", "", sig) in source
