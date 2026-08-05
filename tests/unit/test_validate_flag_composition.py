"""``migrate validate`` runs every check the operator asked for (#187).

Before 0.40.0 the command was a flat chain of ``if <flag>: … return`` blocks
evaluated in source order, so ``--check-acls --check-imports`` ran *only* the
ACL check and exited 0 — a green gate for a check that never ran. That is the
same silent-false-pass class as the pglast-8 ``window_safe`` bug, and in a
pre-commit or CI gate it is the failure mode that matters most.

The matrix below is generated from :data:`STATIC_CHECKS`, so a new flag joins it
by being registered rather than by anyone remembering to extend a list. Every
flag here is static — no database, no git — so the matrix stays a unit test.

The project fixture is a *real* one, built in ``tmp_path`` and ``chdir``-ed into:
Typer resolves ``db/migrations`` relative to the working directory, so a test
run from the repo root exits with "No migrations directory found" long before
reaching the dispatch under test.
"""

from __future__ import annotations

import itertools
import json
import textwrap
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


# (flag, success marker in text output). The marker must be unique to the check,
# so "both ran" is provable from one invocation's output.
STATIC_CHECKS: list[tuple[str, str]] = [
    ("--check-acls", "All migrations have ACL coverage"),
    ("--check-ownership-coverage", "All migrations have ownership coverage"),
    ("--check-function-uniqueness", "All callables have unique signatures"),
    ("--check-security-definer", "No unpinned SECURITY DEFINER functions found"),
    ("--check-imports", "passed import check"),
    ("--idempotent", "All migrations are idempotent"),
]

STATIC_PAIRS = list(itertools.combinations(STATIC_CHECKS, 2))


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A real, clean confiture project every static check passes on."""
    (tmp_path / "db" / "migrations").mkdir(parents=True)
    (tmp_path / "db" / "schema").mkdir(parents=True)
    # No `ALTER TABLE … OWNER TO`: that statement is a blocking idempotency
    # violation, and --idempotent is in the matrix. The ownership lint stays
    # genuinely enabled instead — scoped to materialized views, which this
    # migration does not create, so own_001 has nothing to flag.
    (tmp_path / "db" / "migrations" / "20260101120000_t.up.sql").write_text(
        "CREATE TABLE IF NOT EXISTS public.foo (id int);\nGRANT SELECT ON public.foo TO my_app;\n"
    )
    (tmp_path / "db" / "schema" / "10_tables.sql").write_text(
        "CREATE TABLE IF NOT EXISTS public.foo (id int);\n"
    )
    # SchemaLinter() instantiates Environment.load("local"), which resolves
    # db/environments/local.yaml from the *working directory* — so the file has
    # to exist inside the fixture project, not just in the repo we ran from.
    (tmp_path / "db" / "environments").mkdir(parents=True)
    (tmp_path / "db" / "environments" / "local.yaml").write_text(
        "database_url: postgresql://localhost/test\ninclude_dirs:\n  - path: db/schema\n"
    )
    (tmp_path / "confiture.yaml").write_text(
        textwrap.dedent(
            """\
            name: test
            database_url: postgresql://localhost/test
            include_dirs:
              - path: db/schema
            acls:
              - schema: public
                apply_to: ALL_TABLES
                grants:
                  - role: my_app
                    privileges: [SELECT]
            ownership:
              expected_owner: migrator
              lint_enabled: true
              apply_to:
                - schema: public
                  relkinds: [m]
            function_coverage:
              enabled: true
            security_lint:
              enabled: true
            """
        )
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _invoke(*flags: str) -> object:
    return runner.invoke(app, ["migrate", "validate", "-c", "confiture.yaml", *flags])


@pytest.mark.parametrize(
    ("first", "second"),
    STATIC_PAIRS,
    ids=[f"{a[0]}+{b[0]}" for a, b in STATIC_PAIRS],
)
def test_static_flag_pairs_run_both_checks(
    project: Path,  # noqa: ARG001 — fixture chdirs; the path itself is unused
    first: tuple[str, str],
    second: tuple[str, str],
) -> None:
    """Both requested checks must execute, whichever order the source lists them."""
    first_flag, first_marker = first
    second_flag, second_marker = second

    result = _invoke(first_flag, second_flag)

    assert result.exit_code == 0, result.output
    assert first_marker in result.output, f"{first_flag} did not run: {result.output!r}"
    assert second_marker in result.output, f"{second_flag} did not run: {result.output!r}"


def test_every_static_flag_runs_alone(project: Path) -> None:  # noqa: ARG001
    """Sanity anchor: each marker is genuinely produced by its own flag.

    Without this the matrix could pass vacuously if a marker leaked from an
    unrelated code path.
    """
    for flag, marker in STATIC_CHECKS:
        result = _invoke(flag)
        assert result.exit_code == 0, f"{flag}: {result.output}"
        assert marker in result.output, f"{flag} did not emit its marker: {result.output!r}"


# ---------------------------------------------------------------------------
# Exit codes: the worst outcome across the checks that ran
# ---------------------------------------------------------------------------


def test_failing_second_check_still_fails_the_run(project: Path) -> None:
    """A passing check must not mask a failing one that ran after it."""
    # own_001: a CREATE TABLE with no matching `ALTER … OWNER TO`.
    (project / "confiture.yaml").write_text(
        (project / "confiture.yaml").read_text().replace("relkinds: [m]", "relkinds: [r]")
    )

    result = _invoke("--check-imports", "--check-ownership-coverage")

    assert "passed import check" in result.output
    assert "Ownership coverage check failed" in result.output
    assert result.exit_code == 1, result.output


def test_failing_first_check_still_runs_the_second(project: Path) -> None:
    """A failing check must not stop the rest of the run."""
    (project / "confiture.yaml").write_text(
        (project / "confiture.yaml").read_text().replace("relkinds: [m]", "relkinds: [r]")
    )

    result = _invoke("--check-ownership-coverage", "--check-imports")

    assert "Ownership coverage check failed" in result.output
    assert "passed import check" in result.output
    assert result.exit_code == 1, result.output


# ---------------------------------------------------------------------------
# JSON: one envelope per run, single-check shapes preserved verbatim
# ---------------------------------------------------------------------------


def test_single_check_json_shape_is_unchanged(project: Path) -> None:  # noqa: ARG001
    """One check still emits its own documented payload, not a wrapper."""
    result = _invoke("--check-acls", "--format", "json")

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["check"] == "acl_coverage"
    assert "checks" not in payload


def test_composed_json_is_one_document_keyed_by_check(project: Path) -> None:  # noqa: ARG001
    """Two checks emit a single parseable envelope holding both payloads."""
    result = _invoke("--check-acls", "--check-imports", "--format", "json")

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)  # two documents would not parse
    assert payload["status"] == "passed"
    assert set(payload["checks"]) == {"acl_coverage", "imports"}
    assert payload["checks"]["acl_coverage"]["check"] == "acl_coverage"


def test_composed_json_reports_failed_status(project: Path) -> None:
    (project / "confiture.yaml").write_text(
        (project / "confiture.yaml").read_text().replace("relkinds: [m]", "relkinds: [r]")
    )

    result = _invoke("--check-imports", "--check-ownership-coverage", "--format", "json")

    assert result.exit_code == 1, result.output
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert payload["checks"]["ownership_coverage"]["violations"]


# ---------------------------------------------------------------------------
# Report modes do not compose (they have no gate semantics to compose with)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("report_flag", ["--list-patterns", "--list-unmigrated-bodies"])
def test_report_modes_reject_composition(project: Path, report_flag: str) -> None:  # noqa: ARG001
    result = _invoke(report_flag, "--check-acls")

    assert result.exit_code == 5, result.output
    assert report_flag in result.output
    assert "--check-acls" in result.output


# ---------------------------------------------------------------------------
# The 0.37.0 --idempotent conflict guard is RETIRED (0.41.0)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "git_flag",
    [
        "--check-drift",
        "--require-migration",
        "--require-migration-bodies",
        "--require-grant-migration",
    ],
)
def test_idempotent_no_longer_rejects_the_git_flags(project: Path, git_flag: str) -> None:  # noqa: ARG001
    """No usage error for a combination that composed since 0.40.0.

    This project is not a git repo, so the git group fails on its own terms
    (GIT_002 → exit 7). That is the point: the run gets far enough to *reach*
    the git check instead of being turned away at the door with exit 5.

    That both checks actually execute is proven in
    ``test_validate_composition_git_and_db.py``, which has a real working tree.
    """
    result = _invoke("--idempotent", git_flag)

    assert result.exit_code != 5, result.output
    assert "cannot be combined with" not in result.output
