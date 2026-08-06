"""The producer half of the risk-tier pact with fraisier-core#44 (#197).

`tests/fixtures/preflight-contract/` holds the same bytes as fraisier-core's
`crates/fraisier-adapter-confiture/tests/fixtures/preflight/`. Confiture asserts
it *emits* those shapes; fraisier asserts it *parses* them. Because confiture's
CI cannot see the sibling repository, this is where producer drift is caught.

`detail` is excluded from the comparison — see the fixture directory's README.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.change_set import CONTRACT_VERSION
from confiture.core.risk_tier import RiskTier

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "preflight-contract"

# The scenario the fixtures share, as real migration files.
SCENARIO = {
    "20260804120000": (
        "20260804120000_add_nickname.up.sql",
        "ALTER TABLE tb_user ADD COLUMN nickname text;\n",
    ),
    "20260804120050": (
        "20260804120050_index_placed_at.up.sql",
        "CREATE INDEX idx_placed_at ON tb_order (placed_at);\n",
    ),
    "20260804120100": (
        "20260804120100_drop_legacy_flag.up.sql",
        "ALTER TABLE tb_user DROP COLUMN legacy_flag;\n",
    ),
    "20260804120300": (
        "20260804120300_widen_total.up.sql",
        "ALTER TABLE tb_order ALTER COLUMN total_cents TYPE bigint;\n",
    ),
}


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _emit(tmp_path: Path, versions: list[str]) -> dict:
    """Run the real CLI over the scenario migrations for ``versions``."""
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for version in versions:
        filename, body = SCENARIO[version]
        (migrations / filename).write_text(body)

    result = CliRunner().invoke(
        app,
        ["migrate", "preflight", "--migrations-dir", str(migrations), "--format", "json"],
    )
    assert result.exit_code in (0, 7), result.output
    return json.loads(result.stdout)


def _comparable(change_set: dict) -> dict:
    """The contract-bearing fields. `detail` is free-form by specification."""
    return {
        "contract_version": change_set["contract_version"],
        "changes": [
            {key: value for key, value in change.items() if key != "detail"}
            for change in change_set["changes"]
        ],
    }


@pytest.mark.parametrize(
    ("fixture_name", "versions"),
    [
        ("v1-empty.json", []),
        ("v1-additive.json", ["20260804120000"]),
        ("v1-mixed.json", ["20260804120000", "20260804120050", "20260804120100"]),
        ("v1-missing-tier.json", ["20260804120000", "20260804120300"]),
    ],
)
def test_confiture_emits_the_fixture_shape(fixture_name: str, versions: list[str], tmp_path):
    payload = _emit(tmp_path, versions)
    assert _comparable(payload["change_set"]) == _comparable(_fixture(fixture_name)["change_set"])


def test_every_emitted_change_has_a_detail_line(tmp_path):
    """`detail` is not byte-pinned, but it must be there and it must say something."""
    payload = _emit(tmp_path, list(SCENARIO))
    for change in payload["change_set"]["changes"]:
        assert isinstance(change["detail"], str)
        assert change["detail"].strip()


def test_the_emitted_envelope_is_an_object_never_a_bare_array(tmp_path):
    """`malformed.json` is the shape confiture must never produce."""
    payload = _emit(tmp_path, ["20260804120000"])
    assert isinstance(payload["change_set"], dict)
    assert set(payload["change_set"]) == {"contract_version", "changes"}
    assert isinstance(payload["change_set"]["changes"], list)


def test_confiture_never_emits_a_future_contract_version(tmp_path):
    """`v2-future.json` exists to pin the consumer's refusal, not the producer's output."""
    assert CONTRACT_VERSION == 1
    payload = _emit(tmp_path, ["20260804120100"])
    assert payload["change_set"]["contract_version"] == 1
    assert _fixture("v2-future.json")["change_set"]["contract_version"] > CONTRACT_VERSION


def test_confiture_never_emits_a_tier_outside_the_five(tmp_path):
    """`v1-unknown-tier.json`'s `quantum` must be unreachable from this producer."""
    known = {tier.value for tier in RiskTier}
    assert known == {"additive", "reversible", "lock_risky", "destructive", "irreversible"}

    unknown = _fixture("v1-unknown-tier.json")["change_set"]["changes"][1]["tier"]
    assert unknown not in known

    payload = _emit(tmp_path, list(SCENARIO))
    for change in payload["change_set"]["changes"]:
        if "tier" in change:
            assert change["tier"] in known


def test_the_pre_contract_payload_still_describes_this_command(tmp_path):
    """`v0-no-change-set.json` is the back-compat baseline: everything else is unchanged."""
    baseline = _fixture("v0-no-change-set.json")
    payload = _emit(tmp_path, ["20260804120000"])
    assert set(baseline) <= set(payload)
    assert set(baseline["summary"]) == set(payload["summary"])
