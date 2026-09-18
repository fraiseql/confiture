"""`verify-checksums` is reachable from `migrate`, where users look (#311).

It is `confiture verify-checksums`, registered top-level beside
`install-helpers`, `restore`, `bootstrap` and `sync` — not
`confiture migrate verify-checksums`. The reporter searched `migrate --help`
and `cli/commands/migrate/`, "because every other migration concern lives
there", concluded no read-only ledger-vs-files check existed, and filed an
issue asking for one. Their CI had been invoking the command on every ship for
months.

Both names stay. The top-level one is named on the fraisier adapter's
exit-code table (`docs/reference/fraisier-adapter-contract.md`), so this is an
alias, not a move and not a deprecation.
"""

from __future__ import annotations

from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


class TestBothNamesWork:
    def test_the_alias_under_migrate_exists(self) -> None:
        result = runner.invoke(app, ["migrate", "verify-checksums", "--help"])

        assert result.exit_code == 0, result.output

    def test_the_top_level_name_still_works(self) -> None:
        """Named on the adapter's exit-code table — removing it breaks a contract."""
        result = runner.invoke(app, ["verify-checksums", "--help"])

        assert result.exit_code == 0, result.output

    def test_migrate_help_lists_it(self) -> None:
        """The listing is the whole point: `migrate --help` is where they looked."""
        result = runner.invoke(app, ["migrate", "--help"])

        assert result.exit_code == 0
        assert "verify-checksums" in result.output


class TestTheTwoCannotDrift:
    """One callable, two registrations — so there is no second option list."""

    def test_the_same_flags_are_offered_under_both_names(self) -> None:
        top = runner.invoke(app, ["verify-checksums", "--help"]).output
        under_migrate = runner.invoke(app, ["migrate", "verify-checksums", "--help"]).output

        for flag in ("--migrations-dir", "--config", "--fix", "--allow-uninitialized", "--format"):
            assert flag in top, f"{flag} missing from `verify-checksums --help`"
            assert flag in under_migrate, f"{flag} missing from `migrate verify-checksums --help`"

    def test_the_alias_behaves_identically_on_a_real_invocation(self, tmp_path) -> None:
        """Not just help text: a missing config must fail the same way under both."""
        argv = ["-c", str(tmp_path / "nope.yaml")]
        top = runner.invoke(app, ["verify-checksums", *argv])
        under_migrate = runner.invoke(app, ["migrate", "verify-checksums", *argv])

        assert top.exit_code == under_migrate.exit_code
