"""Contract test pinning the command lines confiture's consumers spell.

fraisier and printoptim_backend drive confiture over a subprocess, from Python,
Makefiles, CI job definitions and shell scripts. None of it runs in confiture's CI,
so a renamed command or a dropped flag surfaces as a failed deploy or a red ship
gate in someone else's repository. Each row below is one invocation as the
consumer writes it, with the consumer's own ``file:line``: removing a command or a
flag is then a deliberate edit to this table that names who it breaks.

Resolution goes through the live Typer tree, the same walk the docs guards use
(``tests/unit/docs/command_truth.py``), never through a list of names kept here.

The ``--format`` vocabularies are **not** one vocabulary, and a consumer depends on
that: ``lint`` accepts ``table`` and ``seed validate`` rejects it with
``VALID_001``, which is why printoptim runs ``seed validate --format text``.
"""

from __future__ import annotations

import re
from typing import NamedTuple

import pytest
from tests.unit.docs.command_truth import resolve
from typer.testing import CliRunner

from confiture.cli.main import app


class Invocation(NamedTuple):
    """One command line a consumer runs."""

    consumer: str
    command: tuple[str, ...]
    flags: tuple[str, ...]
    source: str
    """The consumer's own ``file:line`` that spells it."""


_FRAISIER_DBOPS = "fraisier:fraisier/dbops/confiture.py"
_FRAISIER_DRIFT = "fraisier:fraisier/dbops/drift.py"
_FRAISES = "printoptim:fraises.yaml"
_MAKEFILE = "printoptim:Makefile"
_DEFINITION_DRIFT = "printoptim:scripts/ops/check_definition_drift.py"

INVOCATIONS: tuple[Invocation, ...] = (
    # fraisier
    Invocation(
        "fraisier",
        ("migrate", "up"),
        ("-c", "--auto-detect-baseline"),
        f"{_FRAISIER_DBOPS}:669",
    ),
    Invocation("fraisier", ("migrate", "down"), ("-c",), f"{_FRAISIER_DBOPS}:669"),
    Invocation(
        "fraisier",
        ("migrate", "rebuild"),
        ("-c", "-y", "--drop-schemas"),
        f"{_FRAISIER_DBOPS}:702",
    ),
    Invocation(
        "fraisier",
        ("migrate", "status"),
        ("-c", "--format"),
        f"{_FRAISIER_DBOPS}:731",
    ),
    Invocation(
        "fraisier",
        ("build",),
        ("--project-dir", "--env", "--schema-only", "--warn-duplicates", "--output", "--format"),
        f"{_FRAISIER_DRIFT}:571",
    ),
    Invocation(
        "fraisier",
        ("migrate", "validate"),
        (
            "--check-live-drift",
            "--check-signatures",
            "--schemas",
            "-c",
            "--schema",
            "--format",
        ),
        f"{_FRAISIER_DRIFT}:646",
    ),
    Invocation(
        "fraisier",
        ("migrate", "preflight"),
        ("--against", "--migrations-dir", "--format", "--config", "--since"),
        "fraisier:fraisier/dbops/preflight.py:771",
    ),
    # printoptim_backend
    Invocation(
        "printoptim",
        ("build",),
        ("--env", "--show-hash", "--project-dir"),
        f"{_MAKEFILE}:367",
    ),
    Invocation(
        "printoptim",
        ("build",),
        ("--env", "--schema-only", "--output"),
        f"{_DEFINITION_DRIFT}:223",
    ),
    Invocation(
        "printoptim",
        ("lint",),
        ("--env", "--select", "--format", "--fail-on", "--baseline"),
        f"{_FRAISES}:214",
    ),
    Invocation(
        "printoptim",
        ("migrate", "validate"),
        ("--require-migration", "--base-ref", "--env"),
        f"{_FRAISES}:365",
    ),
    Invocation(
        "printoptim",
        ("migrate", "validate"),
        ("--idempotent", "--base-ref"),
        f"{_FRAISES}:312",
    ),
    Invocation(
        "printoptim",
        ("migrate", "validate"),
        ("--require-grant-migration", "--base-ref"),
        f"{_FRAISES}:376",
    ),
    Invocation(
        "printoptim",
        ("migrate", "validate"),
        ("--check-ownership-coverage",),
        f"{_FRAISES}:346",
    ),
    Invocation(
        "printoptim",
        ("migrate", "validate"),
        ("--check-signatures", "--check-body", "--env", "--schemas", "--format"),
        f"{_DEFINITION_DRIFT}:158",
    ),
    Invocation(
        "printoptim",
        ("migrate", "validate"),
        ("--check-live-drift", "--env", "--schema", "--format"),
        f"{_DEFINITION_DRIFT}:253",
    ),
    Invocation(
        "printoptim",
        ("seed", "validate"),
        ("--prep-seed", "--static-only", "--level", "--format", "--output"),
        f"{_MAKEFILE}:369",
    ),
    Invocation(
        "printoptim",
        ("seed", "validate"),
        ("--prep-seed", "--full-execution", "--level", "--database-url", "--format"),
        f"{_FRAISES}:223",
    ),
    Invocation(
        "printoptim",
        ("test-db", "ram-setup"),
        ("--tablespace", "--location"),
        f"{_MAKEFILE}:151",
    ),
    Invocation(
        "printoptim",
        ("verify-checksums",),
        ("--migrations-dir", "--allow-uninitialized"),
        f"{_FRAISES}:305",
    ),
    Invocation(
        "printoptim",
        ("migrate", "status"),
        ("--config", "-c"),
        f"{_MAKEFILE}:413",
    ),
    Invocation(
        "printoptim",
        ("migrate", "up"),
        ("-c", "--config", "--dry-run"),
        f"{_MAKEFILE}:588",
    ),
    Invocation("printoptim", ("migrate", "down"), ("-c",), f"{_MAKEFILE}:596"),
    Invocation(
        "printoptim",
        ("migrate", "baseline"),
        ("--through", "--config"),
        "printoptim:scripts/etl/setup_prod_local_db.sh:119",
    ),
    Invocation(
        "printoptim",
        ("install-helpers",),
        ("--config",),
        "printoptim:scripts/etl/setup_prod_local_db.sh:116",
    ),
)


def _declared(command) -> set[str]:
    """Every option string *command* declares, long and short, negations included."""
    declared: set[str] = set()
    for param in command.params:
        declared.update(getattr(param, "opts", ()))
        declared.update(getattr(param, "secondary_opts", ()))
    return declared


@pytest.mark.parametrize(
    "row",
    INVOCATIONS,
    ids=lambda r: f"{r.consumer}:{' '.join(r.command)}:{r.source.rsplit(':', 1)[-1]}",
)
def test_consumer_invocation_still_resolves(row: Invocation) -> None:
    """The command exists and declares every flag the consumer passes it."""
    path, command, unconsumed = resolve(row.command)
    assert command is not None and path == list(row.command) and not unconsumed, (
        f"`confiture {' '.join(row.command)}` no longer exists — "
        f"{row.consumer} runs it at {row.source}"
    )
    missing = [flag for flag in row.flags if flag not in _declared(command)]
    assert not missing, (
        f"`confiture {' '.join(row.command)}` lost {missing} — "
        f"{row.consumer} passes them at {row.source}"
    )


runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def test_lint_still_accepts_format_table() -> None:
    """printoptim's lint gate prints a table (``fraises.yaml:214``)."""
    result = runner.invoke(app, ["lint", "--format", "table", "--list-rules"])
    output = _ANSI.sub("", result.output)
    assert "VALID_001" not in output, output
    assert result.exit_code == 0, output


def test_seed_validate_still_rejects_format_table() -> None:
    """``seed validate`` speaks text/json/csv and says so (``fraises.yaml:218``).

    printoptim chose ``--format text`` *because* ``table`` is refused with
    ``VALID_001``. An option factory that unified the two vocabularies would make
    that comment false in a way no consumer test notices.
    """
    result = runner.invoke(
        app, ["seed", "validate", "--prep-seed", "--static-only", "--format", "table"]
    )
    output = _ANSI.sub("", result.output)
    assert "VALID_001" in output, output
    assert result.exit_code == 5, output
