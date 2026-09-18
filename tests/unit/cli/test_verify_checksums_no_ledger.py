"""`verify-checksums` against a database with no migration ledger (#182a).

0.36.0 crashed with a raw psycopg `relation "tb_confiture" does not exist` at
exit 1 — the same code the command uses for "checksum mismatches found", so the
two states were indistinguishable.  It now exits 2 (`PRECON_1001`), or 0 under
`--allow-uninitialized`.

CliRunner merges stdout/stderr, so these assert on exit codes and combined
output substrings only — never on stream identity.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.ledger import LedgerProbe

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
    elsewhere: list[str] | None = None,
    argv0: str = "verify-checksums",
):
    """Invoke the command with the ledger probe forced to `ledger`.

    `verify_checksums` imports the names inside the function body, so the patch
    targets are the source modules, not `commands.admin`.

    ``probe_ledger``, not ``ledger_exists``: 0.41.0 moved the command onto the
    richer probe. Left on the old name the patch binds to nothing, the real
    probe runs against the MagicMock connection, and a mock row reads as
    *present* — so the ledger=True cases would have gone on passing while
    testing nothing. The `assert probe.called` below is what makes that
    impossible to repeat.
    """
    probe = MagicMock(
        return_value=LedgerProbe(
            exists=ledger, resolved_name="public.tb_confiture" if ledger else None
        )
    )
    with (
        patch("confiture.cli.helpers.create_connection", return_value=MagicMock()),
        patch("confiture.core.ledger.probe_ledger", probe),
        patch("confiture.core.ledger.find_ledger_relations", return_value=elsewhere or []),
    ):
        result = runner.invoke(
            app,
            [argv0, "-c", str(cfg), "--migrations-dir", str(migrations_dir), *extra],
        )
    assert probe.called, "the ledger probe double was never used — patch target is stale"
    return result


class TestAbsentLedger:
    def test_absent_ledger_exits_2(self, cfg: Path, migrations_dir: Path) -> None:
        result = _invoke(cfg, migrations_dir, ledger=False)

        assert result.exit_code == 2
        assert "tb_confiture" in result.output
        for marker in RAW_PSYCOPG_MARKERS:
            assert marker not in result.output

    def test_absent_ledger_message_is_actionable(self, cfg: Path, migrations_dir: Path) -> None:
        result = _invoke(cfg, migrations_dir, ledger=False)

        assert "is not present in this database" in result.output
        # The three ways forward, per _NO_LEDGER_HINT.
        assert "migrate up" in result.output
        assert "baseline" in result.output
        assert "--allow-uninitialized" in result.output


class TestAllowUninitialized:
    def test_allow_uninitialized_exits_0(self, cfg: Path, migrations_dir: Path) -> None:
        result = _invoke(cfg, migrations_dir, "--allow-uninitialized", ledger=False)

        assert result.exit_code == 0
        assert "no migration ledger" in result.output.lower()
        for marker in RAW_PSYCOPG_MARKERS:
            assert marker not in result.output

    def test_allow_uninitialized_reports_zero_recorded(
        self, cfg: Path, migrations_dir: Path
    ) -> None:
        result = _invoke(cfg, migrations_dir, "--allow-uninitialized", ledger=False)

        assert "0 migrations recorded" in result.output


class TestAbsentIsNotEmpty:
    """A present-but-empty ledger is a different state and still succeeds.

    If this fails, the probe is in the wrong place — it is conflating "no
    table" with "no rows", which is the bug this phase exists to fix.
    """

    def test_present_but_empty_ledger_still_succeeds(self, cfg: Path, migrations_dir: Path) -> None:
        with patch(
            "confiture.core.checksum.MigrationChecksumVerifier._get_stored_checksums",
            return_value={},
        ):
            result = _invoke(cfg, migrations_dir, ledger=True)

        assert result.exit_code == 0
        assert "All migration checksums verified" in result.output
        assert "no migration ledger" not in result.output.lower()


class TestAbsentButPresentElsewhere:
    """0.41.0 made "absent" mean "does not resolve *here*" (#188).

    A bare `tracking_table` is now resolved through `search_path`, so a ledger
    parked in another schema reports absent where it used to report present.
    "Not present in this database" would then be a lie the operator has no way
    to see through, so the message says where it actually is.
    """

    def test_the_message_names_the_schema_that_holds_it(
        self, cfg: Path, migrations_dir: Path
    ) -> None:
        result = _invoke(cfg, migrations_dir, ledger=False, elsewhere=["staging.tb_confiture"])

        assert result.exit_code == 2
        assert "staging.tb_confiture" in result.output
        assert "search_path" in result.output

    def test_allow_uninitialized_says_it_too(self, cfg: Path, migrations_dir: Path) -> None:
        result = _invoke(
            cfg,
            migrations_dir,
            "--allow-uninitialized",
            ledger=False,
            elsewhere=["staging.tb_confiture"],
        )

        assert result.exit_code == 0
        assert "staging.tb_confiture" in result.output

    def test_a_genuinely_empty_database_gains_no_extra_noise(
        self, cfg: Path, migrations_dir: Path
    ) -> None:
        """Nothing found elsewhere means nothing extra said."""
        result = _invoke(cfg, migrations_dir, ledger=False, elsewhere=[])

        assert "search_path" not in result.output


class TestSkippedIsNotSuccess:
    """A run that compared nothing must not read as a pass (#311).

    `--allow-uninitialized` is the operator saying "a ledger-less database must
    not trip this gate". It is not a claim that verification happened. Until
    1.12.0 the JSON payload conflated the two: `ok` was computed as
    `not mismatches`, and an absent ledger yields no mismatches, so a run that
    compared **zero** files emitted `{"ok": true, "ledger_present": false,
    "summary": {"checked": 0, "mismatched": 0}}` at exit 0.

    The published schema tells consumers to read `ok` and nothing else, so that
    was not a consumer misreading the payload — it was a consumer honouring the
    documented contract and being told green by a run that did no work. The
    reporter's CI ran exactly this, on every ship, for months.

    The exit code stays 0: `docs/reference/fraisier-adapter-contract.md` pins
    `--allow-uninitialized` as the way to turn PRECON_1001's exit 2 into exit 0,
    and the adapter branches on that integer. The correction goes in the
    payload, which that same contract declares it does not read.
    """

    @staticmethod
    def _payload(result) -> dict:
        return json.loads(result.output)

    def test_skipped_run_is_not_ok(self, cfg: Path, migrations_dir: Path) -> None:
        result = _invoke(
            cfg, migrations_dir, "--allow-uninitialized", "--format", "json", ledger=False
        )

        assert result.exit_code == 0
        assert self._payload(result)["ok"] is False

    def test_skipped_run_says_it_was_skipped(self, cfg: Path, migrations_dir: Path) -> None:
        result = _invoke(
            cfg, migrations_dir, "--allow-uninitialized", "--format", "json", ledger=False
        )

        assert self._payload(result)["was_skipped"] is True

    def test_a_clean_run_is_ok_and_not_skipped(self, cfg: Path, migrations_dir: Path) -> None:
        """The other half of the invariant: a real comparison still reads green.

        Without this, `ok: false` everywhere would pass the two tests above.
        """
        with patch(
            "confiture.core.checksum.MigrationChecksumVerifier._get_stored_checksums",
            return_value={},
        ):
            result = _invoke(cfg, migrations_dir, "--format", "json", ledger=True)

        payload = self._payload(result)
        assert result.exit_code == 0
        assert payload["ok"] is True
        assert payload["was_skipped"] is False

    def test_text_mode_does_not_imply_a_pass(self, cfg: Path, migrations_dir: Path) -> None:
        """Text mode was closer to honest than JSON, but still reads as "fine"."""
        result = _invoke(cfg, migrations_dir, "--allow-uninitialized", ledger=False)

        assert result.exit_code == 0
        assert "nothing was verified" in result.output.lower()
        # The success line and its glyph, neither of which this run earned.
        assert "all migration checksums verified" not in result.output.lower()
        assert "✅" not in result.output
        # ...and where the exit 0 actually came from.
        assert "--allow-uninitialized" in result.output
