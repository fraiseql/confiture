"""`migrate preflight` emits the change set across the adapter seam (#197).

The producer half of the cross-repo pact with fraisier-core#44: confiture emits
the shapes, fraisier parses them. What is pinned here is the *payload* — the
`change_set` envelope, the tier values, and the fact that adding it left
`window_safe` (#154) exactly where it was.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from confiture.models.results import PreflightAgainstMigration, PreflightAgainstResult


@pytest.fixture()
def runner():
    return CliRunner()


def _migrations(tmp_path, files: dict[str, str]):
    migs = tmp_path / "db" / "migrations"
    migs.mkdir(parents=True)
    for name, body in files.items():
        (migs / name).write_text(body)
    return migs


def _preflight_json(runner, migs, *extra: str) -> dict:
    result = runner.invoke(
        runner_app(),
        ["migrate", "preflight", "--migrations-dir", str(migs), "--format", "json", *extra],
    )
    assert result.exit_code in (0, 7), result.output
    return json.loads(result.stdout)


def runner_app():
    from confiture.cli.main import app

    return app


def test_preflight_emits_a_versioned_change_set(runner, tmp_path):
    migs = _migrations(
        tmp_path,
        {
            "20260804120000_add_nickname.up.sql": "ALTER TABLE tb_user ADD COLUMN nickname text;\n",
            "20260804120000_add_nickname.down.sql": "ALTER TABLE tb_user DROP COLUMN nickname;\n",
        },
    )

    payload = _preflight_json(runner, migs)

    assert payload["change_set"] == {
        "contract_version": 1,
        "changes": [
            {
                "kind": "add_column",
                "object": "public.tb_user.nickname",
                "migration": "20260804120000",
                "tier": "additive",
                "detail": "ADD COLUMN nickname NULL",
            }
        ],
    }


def test_an_empty_tree_is_a_classified_empty_set(runner, tmp_path):
    """`changes: []` means "looked, nothing to change" — an absent key would mean "did not look"."""
    migs = _migrations(tmp_path, {})
    payload = _preflight_json(runner, migs)
    assert payload["change_set"] == {"contract_version": 1, "changes": []}


def test_a_destructive_change_carries_its_tier(runner, tmp_path):
    migs = _migrations(
        tmp_path,
        {"20260804120100_drop.up.sql": "ALTER TABLE tb_user DROP COLUMN legacy_flag;\n"},
    )
    payload = _preflight_json(runner, migs)
    (change,) = payload["change_set"]["changes"]
    assert change["tier"] == "irreversible"
    assert change["object"] == "public.tb_user.legacy_flag"


def test_an_unclassifiable_change_omits_the_tier(runner, tmp_path):
    """Absent is the contract's "unclassified"; the consumer denies on it."""
    migs = _migrations(
        tmp_path,
        {"20260804120300_widen.up.sql": "ALTER TABLE tb_order ALTER COLUMN total TYPE bigint;\n"},
    )
    payload = _preflight_json(runner, migs)
    (change,) = payload["change_set"]["changes"]
    assert change["kind"] == "alter_column_type"
    assert "tier" not in change


def test_a_python_migration_appears_as_an_unclassified_entry(runner, tmp_path):
    migs = _migrations(tmp_path, {"20260804120200_backfill.py": "# opaque\n"})
    payload = _preflight_json(runner, migs)
    (change,) = payload["change_set"]["changes"]
    assert change["kind"] == "python_migration"
    assert "tier" not in change
    # …and it still trips the pinned window-safety verdict.
    assert payload["window_safe"] is False


def test_changes_stay_in_migration_order(runner, tmp_path):
    migs = _migrations(
        tmp_path,
        {
            "20260804120000_a.up.sql": "ALTER TABLE tb_user ADD COLUMN nickname text;\n",
            "20260804120050_b.up.sql": "CREATE INDEX idx_placed_at ON tb_order (placed_at);\n",
            "20260804120100_c.up.sql": "ALTER TABLE tb_user DROP COLUMN legacy_flag;\n",
        },
    )
    payload = _preflight_json(runner, migs)
    assert [(c["migration"], c["tier"]) for c in payload["change_set"]["changes"]] == [
        ("20260804120000", "additive"),
        ("20260804120050", "lock_risky"),
        ("20260804120100", "irreversible"),
    ]


def test_change_set_migration_matches_the_issue_migration_format(runner, tmp_path):
    """Two `migration` fields in one payload disagreeing on format would be a nasty bug."""
    migs = _migrations(
        tmp_path,
        {
            "20260804120050_idx.up.sql": (
                "CREATE INDEX CONCURRENTLY idx_placed_at ON tb_order (placed_at);\n"
            )
        },
    )
    payload = _preflight_json(runner, migs)
    (change,) = payload["change_set"]["changes"]
    assert change["migration"] == "20260804120050"


def test_text_mode_renders_the_worst_tier(runner, tmp_path):
    migs = _migrations(
        tmp_path,
        {
            "20260804120000_a.up.sql": (
                "CREATE TABLE tb_new (id int);\nALTER TABLE tb_user DROP COLUMN legacy_flag;\n"
            )
        },
    )
    result = runner.invoke(runner_app(), ["migrate", "preflight", "--migrations-dir", str(migs)])
    assert "risk:" in result.output.lower()
    assert "irreversible" in result.output.lower()


def test_text_mode_counts_classified_changes_honestly(runner, tmp_path):
    """Two of three changes carry a tier — saying "3 classified" would be the lie."""
    migs = _migrations(
        tmp_path,
        {
            "20260804120000_a.up.sql": (
                "CREATE TABLE tb_new (id int);\n"
                "ALTER TABLE tb_user DROP COLUMN legacy_flag;\n"
                "ALTER TABLE tb_order ALTER COLUMN total TYPE bigint;\n"
            )
        },
    )
    result = runner.invoke(runner_app(), ["migrate", "preflight", "--migrations-dir", str(migs)])
    output = " ".join(result.output.split())
    assert "worst of 2 classified change(s) of 3" in output
    assert "1 change(s) could not be classified" in output


def test_the_against_payload_carries_the_change_set_too(runner, tmp_path):
    migs = _migrations(
        tmp_path,
        {"20260804120100_drop.up.sql": "ALTER TABLE tb_user DROP COLUMN legacy_flag;\n"},
    )
    against_result = PreflightAgainstResult(
        migrations=[PreflightAgainstMigration("20260804120100", "drop", True)],
        against_url="postgresql://localhost/preflight",
    )
    session = MagicMock()
    session.__enter__ = lambda s: session
    session.__exit__ = MagicMock(return_value=False)
    session.run_against.return_value = against_result

    with patch(
        "confiture.cli.commands.migrate_analysis.MigratorSession", return_value=session
    ) as patched:
        result = runner.invoke(
            runner_app(),
            [
                "migrate",
                "preflight",
                "--migrations-dir",
                str(migs),
                "--against",
                "postgresql://localhost/preflight",
                "--format",
                "json",
            ],
        )

    # A stale patch target does not announce itself: the real session would have
    # tried a connection and the MagicMock would have read as a clean replay.
    assert patched.called, "the MigratorSession double was never used"
    assert result.exit_code in (0, 7), result.output
    payload = json.loads(result.stdout)
    (change,) = payload["change_set"]["changes"]
    assert change["tier"] == "irreversible"
