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

from tests._helpers import strip_ansi
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


def _command(*path: str):
    """The click command registered at ``path``, through Typer's own conversion.

    Typer vendors click, so the command tree is reached via
    ``typer.main.get_command`` rather than by importing click directly.
    """
    import typer.main

    node = typer.main.get_command(app)
    for name in path:
        node = node.commands[name]
    return node


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
        assert "verify-checksums" in strip_ansi(result.output)


class TestTheTwoCannotDrift:
    """One callable, two registrations — so there is no second option list."""

    def test_the_same_flags_are_offered_under_both_names(self) -> None:
        """Compared on the command objects, not on rendered help.

        Rendered help was the first shape of this test and it was wrong twice
        over. Rich forces colour when `GITHUB_ACTIONS` is set and styles each
        flag *in pieces* — `--format` arrives as
        `\x1b[1;36m-\x1b[0m\x1b[1;36m-format\x1b[0m` — so a substring check
        passed locally and failed in CI. `tests/_helpers.strip_ansi` exists for
        that and would have fixed the symptom.

        The parameters are the better subject anyway: they are what "the two
        cannot drift" actually claims, and they would catch a divergence that
        help rendering happened to hide.
        """
        top = _command("verify-checksums")
        under_migrate = _command("migrate", "verify-checksums")

        assert [p.opts for p in top.params] == [p.opts for p in under_migrate.params]
        # Named explicitly, so deleting a flag from *both* still fails here.
        offered = {opt for p in top.params for opt in p.opts}
        assert {
            "--migrations-dir",
            "--config",
            "--fix",
            "--allow-uninitialized",
            "--format",
        } <= offered

    def test_it_is_literally_the_same_callable(self) -> None:
        """One function, two registrations — the property the rest relies on.

        Asserted through ``__wrapped__``: Typer builds a *fresh* wrapper per
        registration, so the two ``callback`` objects are never identical even
        when they wrap one function. Comparing the callbacks directly fails on
        a correct alias, which is a false alarm rather than a guard.
        """
        top = _command("verify-checksums").callback
        alias = _command("migrate", "verify-checksums").callback

        assert top.__wrapped__ is alias.__wrapped__

    def test_the_alias_behaves_identically_on_a_real_invocation(self, tmp_path) -> None:
        """Not just help text: a missing config must fail the same way under both."""
        argv = ["-c", str(tmp_path / "nope.yaml")]
        top = runner.invoke(app, ["verify-checksums", *argv])
        under_migrate = runner.invoke(app, ["migrate", "verify-checksums", *argv])

        assert top.exit_code == under_migrate.exit_code
