"""``--fix`` reports the operation it performed (#311).

Through 1.11.0, ``--fix`` printed the mismatch count it found and then a
*different*, larger count of rows it had rewritten — because it called
``update_all_checksums`` and threw away the mismatch list it was holding. On a
268-migration ledger with one bad checksum that reads:

    ❌ Found 1 checksum mismatch(es):
    ⚠️  Updating stored checksums...
    ✅ Updated 268 checksum(s)

This pins the two counts together, in text and in JSON, so a refactor that
reintroduces the wide update fails here rather than in someone's ledger.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.checksum import ChecksumMismatch
from confiture.core.ledger import LedgerProbe

runner = CliRunner()


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
    (d / "20260101000000_init.up.sql").write_text("SELECT 1;\n")
    return d


def _one_mismatch() -> ChecksumMismatch:
    return ChecksumMismatch(
        version="20260102000000",
        name="add_email",
        file_path=Path("db/migrations/20260102000000_add_email.up.sql"),
        expected="a" * 64,
        actual="b" * 64,
    )


def _invoke(cfg: Path, migrations_dir: Path, *extra: str):
    """One mismatch found in a ledger of 268 applied migrations."""
    verifier = MagicMock()
    verifier.verify_all.return_value = [_one_mismatch()]
    verifier.count_applied.return_value = 268
    # The real method, so a caller that still reaches for the wide re-stamp is
    # visible as a wrong count rather than as a silent MagicMock.
    verifier.update_all_checksums.return_value = 268
    verifier.update_checksums_for.side_effect = len

    with (
        patch("confiture.cli.helpers.create_connection", return_value=MagicMock()),
        patch(
            "confiture.core.ledger.probe_ledger",
            return_value=LedgerProbe(exists=True, resolved_name="public.tb_confiture"),
        ),
        patch("confiture.core.checksum.MigrationChecksumVerifier", return_value=verifier),
    ):
        result = runner.invoke(
            app,
            ["verify-checksums", "-c", str(cfg), "--migrations-dir", str(migrations_dir), *extra],
        )
    return result, verifier


class TestFixIsScoped:
    def test_json_fixed_equals_mismatched(self, cfg: Path, migrations_dir: Path) -> None:
        result, _ = _invoke(cfg, migrations_dir, "--fix", "--format", "json")

        payload = json.loads(result.stdout)
        assert payload["summary"]["mismatched"] == 1
        assert payload["fixed"] == 1, "reported re-stamping more rows than it reported mismatched"

    def test_text_reports_the_count_it_found(self, cfg: Path, migrations_dir: Path) -> None:
        result, _ = _invoke(cfg, migrations_dir, "--fix")

        assert "Found 1 checksum mismatch(es)" in result.output
        assert "Updated 1 checksum(s)" in result.output

    def test_the_wide_restamp_is_not_called(self, cfg: Path, migrations_dir: Path) -> None:
        """`update_all_checksums` still exists; `--fix` must not be its caller."""
        _, verifier = _invoke(cfg, migrations_dir, "--fix")

        verifier.update_all_checksums.assert_not_called()
        verifier.update_checksums_for.assert_called_once()
        assert [m.version for m in verifier.update_checksums_for.call_args[0][0]] == [
            "20260102000000"
        ]
