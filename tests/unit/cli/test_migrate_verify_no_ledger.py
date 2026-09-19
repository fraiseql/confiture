"""`migrate verify` against a database with no migration ledger (#182b).

The reporter hit this via `verify-checksums`; `migrate verify` is an
independent crash site — it calls `migrator.get_applied_versions()`, which is
unguarded on an absent tracking table.

⚠️ BREAKING: exit 2 from `migrate verify` previously fell into the adapter
contract's `InvalidConfig` row.  The contract row was widened in the same
commit as this change.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()

RAW_PSYCOPG_MARKERS = ('relation "', "LINE 1:")


@pytest.fixture
def cfg(tmp_path: Path) -> Path:
    p = tmp_path / "env.yaml"
    p.write_text(
        yaml.safe_dump(
            {
                "name": "test",
                "database_url": "postgresql://localhost/nonexistent_for_test",
                "include_dirs": ["db/schema"],
            }
        )
    )
    return p


@pytest.fixture
def migrations_dir(tmp_path: Path) -> Path:
    d = tmp_path / "migrations"
    d.mkdir()
    (d / "20260101000000_init.up.sql").write_text("CREATE TABLE t (id int);")
    return d


def _invoke(
    cfg: Path,
    migrations_dir: Path,
    *extra: str,
    ledger: bool,
    applied: list[str] | None = None,
):
    """Invoke `migrate verify` with the ledger probe forced to `ledger`."""
    with (
        patch("confiture.cli.helpers.create_connection", return_value=MagicMock()),
        patch(
            "confiture.core.migrator.Migrator.tracking_table_exists",
            return_value=ledger,
        ),
        patch(
            "confiture.core.migrator.Migrator.get_applied_versions",
            return_value=applied or [],
        ),
    ):
        return runner.invoke(
            app,
            [
                "migrate",
                "verify",
                "-c",
                str(cfg),
                "--migrations-dir",
                str(migrations_dir),
                *extra,
            ],
        )


class TestAbsentLedgerText:
    def test_absent_ledger_text_exits_2(self, cfg: Path, migrations_dir: Path) -> None:
        result = _invoke(cfg, migrations_dir, ledger=False)

        assert result.exit_code == 2
        assert "is not present in this database" in result.output
        for marker in RAW_PSYCOPG_MARKERS:
            assert marker not in result.output

    def test_absent_ledger_message_is_actionable(self, cfg: Path, migrations_dir: Path) -> None:
        result = _invoke(cfg, migrations_dir, ledger=False)

        assert "migrate up" in result.output
        assert "baseline" in result.output
        assert "--allow-uninitialized" in result.output


class TestAllowUninitialized:
    def test_allow_uninitialized_text_exits_0(self, cfg: Path, migrations_dir: Path) -> None:
        result = _invoke(cfg, migrations_dir, "--allow-uninitialized", ledger=False)

        assert result.exit_code == 0
        assert "no migration ledger" in result.output.lower()

    def test_allow_uninitialized_json_is_valid_verify_payload(
        self, cfg: Path, migrations_dir: Path
    ) -> None:
        result = _invoke(
            cfg, migrations_dir, "--allow-uninitialized", "--format", "json", ledger=False
        )

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["failed_count"] == 0
        assert payload["total_applied"] == 0
        assert payload["results"] == []
        assert payload["ledger_present"] is False


class TestLedgerPresentField:
    def test_ledger_present_true_on_normal_path(self, cfg: Path, migrations_dir: Path) -> None:
        with patch(
            "confiture.core.migration_verifier.MigrationVerifier.verify_all",
            return_value=[],
        ):
            result = _invoke(
                cfg,
                migrations_dir,
                "--format",
                "json",
                ledger=True,
                applied=["20260101000000"],
            )

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ledger_present"] is True
        assert payload["total_applied"] == 1


class TestAbsentIsNotEmpty:
    """A present-but-empty ledger is a different state — it must not degrade."""

    def test_present_but_empty_ledger_unchanged(self, cfg: Path, migrations_dir: Path) -> None:
        with patch(
            "confiture.core.migration_verifier.MigrationVerifier.verify_all",
            return_value=[],
        ):
            result = _invoke(cfg, migrations_dir, "--format", "json", ledger=True, applied=[])

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["total_applied"] == 0
        assert payload["ledger_present"] is True
        # The guard branch was not taken.
        assert "no migration ledger" not in result.output.lower()


class TestSkippedIsNotSuccess:
    """`migrate verify` must not read as a pass when it verified nothing (#311).

    This is phase 01's defect under another name. `verify-checksums` computed
    `ok` as `not mismatches`, so a ledger-less run reported green; it now
    reports `ok: false` with `was_skipped: true`. `migrate verify` has the same
    hole in a different shape: it carries no `ok` field at all, and the
    published adapter contract says *ok ⇔ `failed_count == 0`* — which is `0`
    on a ledger-less run, because nothing ran.

    The reporter asked for this directly, and their reasoning is the decisive
    part: they are adopting `.verify.sql` sidecars now, so they would be
    adopting a verifier that lies exactly where the ledger is most likely to be
    absent. Two neighbouring commands answering "I could not verify anything"
    differently is a trap of its own.

    `ok` is added rather than only `was_skipped` so the two commands answer in
    the same shape. Note what cannot be done honestly: `failed_count` stays
    `0`, because nothing did fail — which is why the documented success test
    has to move to `ok`.

    Exit codes are unchanged. `--allow-uninitialized` is pinned by
    `docs/reference/fraisier-adapter-contract.md` as the way to turn
    `PRECON_1001`'s exit 2 into exit 0, and the adapter branches on that
    integer.
    """

    def test_a_ledger_less_run_is_not_ok(self, cfg: Path, migrations_dir: Path) -> None:
        result = _invoke(
            cfg, migrations_dir, "--allow-uninitialized", "--format", "json", ledger=False
        )

        payload = json.loads(result.stdout)
        assert result.exit_code == 0
        assert payload["ok"] is False
        assert payload["was_skipped"] is True

    def test_failed_count_stays_zero(self, cfg: Path, migrations_dir: Path) -> None:
        """Nothing failed. The lie was in the *inference*, not in this number."""
        result = _invoke(
            cfg, migrations_dir, "--allow-uninitialized", "--format", "json", ledger=False
        )

        assert json.loads(result.stdout)["failed_count"] == 0

    def test_a_real_run_is_ok_and_not_skipped(self, cfg: Path, migrations_dir: Path) -> None:
        with patch(
            "confiture.core.migration_verifier.MigrationVerifier.verify_all",
            return_value=[],
        ):
            result = _invoke(
                cfg, migrations_dir, "--format", "json", ledger=True, applied=["20260101000000"]
            )

        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["was_skipped"] is False

    def test_a_present_but_empty_ledger_is_ok(self, cfg: Path, migrations_dir: Path) -> None:
        """ "Nothing applied yet" is a real answer about a real ledger."""
        with patch(
            "confiture.core.migration_verifier.MigrationVerifier.verify_all",
            return_value=[],
        ):
            result = _invoke(cfg, migrations_dir, "--format", "json", ledger=True, applied=[])

        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["was_skipped"] is False

    def test_the_two_commands_answer_in_the_same_shape(
        self, cfg: Path, migrations_dir: Path
    ) -> None:
        """The trap the reporter named: neighbours that disagree about "skipped"."""
        result = _invoke(
            cfg, migrations_dir, "--allow-uninitialized", "--format", "json", ledger=False
        )

        payload = json.loads(result.stdout)
        assert {"ok", "was_skipped", "ledger_present"} <= set(payload)

    def test_text_mode_does_not_imply_a_pass(self, cfg: Path, migrations_dir: Path) -> None:
        result = _invoke(cfg, migrations_dir, "--allow-uninitialized", ledger=False)

        assert result.exit_code == 0
        assert "nothing was verified" in result.output.lower()
        assert "--allow-uninitialized" in result.output
