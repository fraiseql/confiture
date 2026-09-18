"""`migrate generate` writes a `.verify.sql` beside the migration (#311).

`confiture migrate preflight` executes real `up()` bodies against a
**schema-only** database — its own help recommends that topology twice. It
follows that `up()` must survive empty tables, and any assertion on data
belongs somewhere that the preflight does not run.

`core/migration_verifier.py` is that somewhere, and has been all along: a
single SELECT, enforced, executed in a SAVEPOINT by the separate
`migrate verify`, never during `migrate up`. The reporter had **zero**
sidecars across 268 migrations — "not by choice; we never knew the mechanism
existed" — and lost two nights of nightly staging restore to one
`RAISE EXCEPTION` guarded on a row count inside `up()`.

So the sidecar is written by default and `--no-verify-sidecar` opts out, rather
than the reverse. An opt-in flag would reproduce the defect being fixed: a
correct mechanism behind a name the user has to already know.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


def _generate(tmp_path: Path, *extra: str):
    return runner.invoke(
        app,
        ["migrate", "generate", "add_widget", "--migrations-dir", str(tmp_path), *extra],
    )


def _sidecars(tmp_path: Path) -> list[Path]:
    return sorted(tmp_path.glob("*.verify.sql"))


class TestItIsWrittenByDefault:
    def test_a_sidecar_appears_next_to_the_migration(self, tmp_path: Path) -> None:
        result = _generate(tmp_path)

        assert result.exit_code == 0, result.output
        migrations = sorted(tmp_path.glob("*_add_widget.py"))
        assert len(migrations) == 1
        assert len(_sidecars(tmp_path)) == 1
        # Same version prefix, so `discover_verify_files` pairs them.
        assert _sidecars(tmp_path)[0].name.startswith(migrations[0].name[: -len("_add_widget.py")])

    def test_the_sidecar_has_no_assertion_in_it(self, tmp_path: Path) -> None:
        """A placeholder, not a guess at what the migration should assert."""
        _generate(tmp_path)

        from confiture.core.sql_lexer import split_statements

        assert split_statements(_sidecars(tmp_path)[0].read_text()) == []

    def test_the_sidecar_states_the_contract(self, tmp_path: Path) -> None:
        """It is read by whoever fills it in, so it carries the rules."""
        _generate(tmp_path)
        body = _sidecars(tmp_path)[0].read_text()

        assert "SELECT" in body
        assert "migrate verify" in body
        # The two facts that make this file the right home for an assertion.
        assert "SAVEPOINT" in body
        assert "preflight" in body

    def test_the_output_names_both_files(self, tmp_path: Path) -> None:
        result = _generate(tmp_path)

        assert ".verify.sql" in result.output

    def test_json_output_names_the_sidecar(self, tmp_path: Path) -> None:
        result = _generate(tmp_path, "--format", "json")

        payload = json.loads(result.stdout)
        assert payload["verify_file"] is not None
        assert payload["verify_file"].endswith(".verify.sql")


class TestOptOut:
    def test_no_verify_sidecar_suppresses_it(self, tmp_path: Path) -> None:
        result = _generate(tmp_path, "--no-verify-sidecar")

        assert result.exit_code == 0, result.output
        assert sorted(tmp_path.glob("*_add_widget.py"))
        assert _sidecars(tmp_path) == []

    def test_json_says_so(self, tmp_path: Path) -> None:
        result = _generate(tmp_path, "--no-verify-sidecar", "--format", "json")

        assert json.loads(result.stdout)["verify_file"] is None


class TestItDoesNotClobber:
    def test_dry_run_writes_nothing(self, tmp_path: Path) -> None:
        result = _generate(tmp_path, "--dry-run")

        assert result.exit_code == 0, result.output
        assert _sidecars(tmp_path) == []

    def test_an_existing_sidecar_survives_a_forced_regenerate(self, tmp_path: Path) -> None:
        """Someone's assertions are not development artefacts to overwrite.

        `--force` is about the migration file. A sidecar that already has
        content in it is the only copy of a human's work in this directory.
        """
        _generate(tmp_path)
        sidecar = _sidecars(tmp_path)[0]
        sidecar.write_text("SELECT count(*) > 0 FROM tb_widget;\n")

        result = _generate(tmp_path, "--force")

        assert result.exit_code == 0, result.output
        assert sidecar.read_text() == "SELECT count(*) > 0 FROM tb_widget;\n"


class TestTheGeneratedSidecarVerifiesCleanly:
    """The trap this cycle depends on Phase 04 Cycle 1 having closed.

    Under 1.11.0 a comment-only sidecar reported `failed`, so emitting one from
    `generate` would have turned every newly created migration red.
    """

    def test_migrate_verify_reports_it_skipped(self, tmp_path: Path) -> None:
        from unittest.mock import MagicMock

        from confiture.core.migration_verifier import MigrationVerifier

        _generate(tmp_path)
        sidecar = _sidecars(tmp_path)[0]
        version = sidecar.name[: -len(".verify.sql")].split("_", 1)[0]

        result = MigrationVerifier(connection=MagicMock(), migrations_dir=tmp_path).run_verify(
            version, "add_widget", sidecar
        )

        assert result.status == "skipped"
        assert result.error is None


class TestTheMigrationItselfStatesTheObligation:
    """The sidecar can be deleted; the docstring cannot.

    `--no-verify-sidecar`, `rm`, or a migration written by hand all leave the
    `.py` as the only place the author will read. The obligation belongs there
    too — it is the one fact about `up()` that confiture recommends a topology
    for and never wrote down: not in `_MIGRATION_TEMPLATE`, not in
    `migrate validate`'s ~35 check flags, not in any guide.
    """

    @staticmethod
    def _migration_body(tmp_path: Path) -> str:
        return sorted(tmp_path.glob("*_add_widget.py"))[0].read_text()

    def test_the_docstring_names_the_sidecar(self, tmp_path: Path) -> None:
        _generate(tmp_path, "--no-verify-sidecar")

        assert ".verify.sql" in self._migration_body(tmp_path)

    def test_the_docstring_states_the_empty_table_obligation(self, tmp_path: Path) -> None:
        body = (_generate(tmp_path), self._migration_body(tmp_path))[1]

        assert "preflight" in body
        assert "schema-only" in body

    def test_it_still_generates_valid_python(self, tmp_path: Path) -> None:
        """Prose in a template is prose in a file that has to import.

        The docstring gained an indented filename line, which is exactly the
        kind of edit that turns a template into a syntax error.
        """
        import ast

        _generate(tmp_path)
        tree = ast.parse(self._migration_body(tmp_path))

        classes = [n.name for n in tree.body if isinstance(n, ast.ClassDef)]
        assert classes == ["AddWidget"], classes
        assert ast.get_docstring(tree), "module docstring lost"
