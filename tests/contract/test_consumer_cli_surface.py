"""Contract test pinning the command lines confiture's consumers spell.

fraisier, fraiseql v2 and a downstream application drive confiture over a subprocess,
from Rust, Python, Makefiles, CI job definitions and shell scripts. None of it runs in confiture's CI,
so a renamed command or a dropped flag surfaces as a failed deploy or a red ship
gate in someone else's repository. Each row below is one invocation as the
consumer writes it, with the consumer's own ``file:line``: removing a command or a
flag is then a deliberate edit to this table that names who it breaks.

fraiseql v2's rows are read from its source: ``ConfitureCommand::argv`` in
``crates/fraiseql-cli/src/commands/migrate.rs`` (``fraiseql/fraiseql``, branch
``dev`` at ``1c6d131c``) builds every command line it runs, and each row cites the
call site that picks the verb. It hands a DSN only to ``up``, ``down`` and
``status``, as ``CONFITURE_DATABASE_URL`` with ``--no-config``; that mechanism is
held end to end in ``test_fraisier_adapter_surface.py``.

Resolution goes through the live Typer tree, the same walk the docs guards use
(``tests/unit/docs/command_truth.py``), never through a list of names kept here.

The ``--format`` vocabularies are **not** one vocabulary, and a consumer depends on
that: ``lint`` accepts ``table`` and ``seed validate`` rejects it with
``VALID_001``, which is why the application runs ``seed validate --format text``.
"""

import re
from typing import NamedTuple

import pytest
import typer
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
    arguments: tuple[str, ...] = ()
    """The positional arguments the consumer passes, by parameter name."""


_FRAISIER_DBOPS = "fraisier:fraisier/dbops/confiture.py"
_FRAISIER_DRIFT = "fraisier:fraisier/dbops/drift.py"
_FRAISES = "app:fraises.yaml"
_MAKEFILE = "app:Makefile"
_DEFINITION_DRIFT = "app:scripts/ops/check_definition_drift.py"
_FRAISEQL_V2 = "fraiseql:crates/fraiseql-cli/src/commands/migrate.rs"

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
    # fraiseql v2
    Invocation(
        "fraiseql",
        ("migrate", "up"),
        ("--migrations-dir", "--no-config", "--format"),
        f"{_FRAISEQL_V2}:88",
    ),
    Invocation(
        "fraiseql",
        ("migrate", "down"),
        ("--migrations-dir", "--steps", "--no-config", "--format"),
        f"{_FRAISEQL_V2}:101",
    ),
    Invocation(
        "fraiseql",
        ("migrate", "status"),
        ("--migrations-dir", "--no-config", "--format"),
        f"{_FRAISEQL_V2}:111",
    ),
    Invocation(
        "fraiseql",
        ("migrate", "generate"),
        ("--migrations-dir", "--format"),
        f"{_FRAISEQL_V2}:121",
        arguments=("name",),
    ),
    Invocation(
        "fraiseql",
        ("migrate", "validate"),
        ("--migrations-dir", "--format"),
        f"{_FRAISEQL_V2}:139",
    ),
    Invocation(
        "fraiseql",
        ("migrate", "preflight"),
        ("--migrations-dir", "--format"),
        f"{_FRAISEQL_V2}:148",
    ),
    # A downstream application
    Invocation(
        "app",
        ("build",),
        ("--env", "--show-hash", "--project-dir"),
        f"{_MAKEFILE}:367",
    ),
    Invocation(
        "app",
        ("build",),
        ("--env", "--schema-only", "--output"),
        f"{_DEFINITION_DRIFT}:223",
    ),
    Invocation(
        "app",
        ("lint",),
        ("--env", "--select", "--format", "--fail-on", "--baseline"),
        f"{_FRAISES}:214",
    ),
    Invocation(
        "app",
        ("migrate", "validate"),
        ("--require-migration", "--base-ref", "--env"),
        f"{_FRAISES}:365",
    ),
    Invocation(
        "app",
        ("migrate", "validate"),
        ("--idempotent", "--base-ref"),
        f"{_FRAISES}:312",
    ),
    Invocation(
        "app",
        ("migrate", "validate"),
        ("--require-grant-migration", "--base-ref"),
        f"{_FRAISES}:376",
    ),
    Invocation(
        "app",
        ("migrate", "validate"),
        ("--check-ownership-coverage",),
        f"{_FRAISES}:346",
    ),
    Invocation(
        "app",
        ("migrate", "validate"),
        ("--check-signatures", "--check-body", "--env", "--schemas", "--format"),
        f"{_DEFINITION_DRIFT}:158",
    ),
    Invocation(
        "app",
        ("migrate", "validate"),
        ("--check-live-drift", "--env", "--schema", "--format"),
        f"{_DEFINITION_DRIFT}:253",
    ),
    Invocation(
        "app",
        ("seed", "validate"),
        ("--prep-seed", "--static-only", "--level", "--format", "--output"),
        f"{_MAKEFILE}:369",
    ),
    Invocation(
        "app",
        ("seed", "validate"),
        ("--prep-seed", "--full-execution", "--level", "--database-url", "--format"),
        f"{_FRAISES}:223",
    ),
    Invocation(
        "app",
        ("test-db", "ram-setup"),
        ("--tablespace", "--location"),
        f"{_MAKEFILE}:151",
    ),
    Invocation(
        "app",
        ("verify-checksums",),
        ("--migrations-dir", "--allow-uninitialized"),
        f"{_FRAISES}:305",
    ),
    Invocation(
        "app",
        ("migrate", "status"),
        ("--config", "-c"),
        f"{_MAKEFILE}:413",
    ),
    Invocation(
        "app",
        ("migrate", "up"),
        ("-c", "--config", "--dry-run"),
        f"{_MAKEFILE}:588",
    ),
    Invocation("app", ("migrate", "down"), ("-c",), f"{_MAKEFILE}:596"),
    Invocation(
        "app",
        ("migrate", "baseline"),
        ("--through", "--config"),
        "app:scripts/etl/setup_prod_local_db.sh:119",
    ),
    Invocation(
        "app",
        ("install-helpers",),
        ("--config",),
        "app:scripts/etl/setup_prod_local_db.sh:116",
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
    arguments = [p.name for p in command.params if p.param_type_name == "argument"]
    assert list(row.arguments) == arguments[: len(row.arguments)], (
        f"`confiture {' '.join(row.command)}` takes {arguments} positionally — "
        f"{row.consumer} passes {list(row.arguments)} at {row.source}"
    )


@pytest.mark.parametrize(
    "row",
    [row for row in INVOCATIONS if row.consumer == "fraiseql"],
    ids=lambda r: " ".join(r.command),
)
def test_fraiseql_format_json_is_accepted(row: Invocation) -> None:
    """Under its global ``--json`` fraiseql v2 passes ``--format json`` to every verb.

    ``--format`` is a string option whose callback holds each command's own
    vocabulary, so the flag resolving says nothing about ``json``: the callback is
    run on the value fraiseql passes.
    """
    _, command, _ = resolve(row.command)
    option = next(p for p in command.params if "--format" in getattr(p, "opts", ()))
    try:
        # Typer vendors its own click, so the context is the command's own class.
        accepted = option.process_value(command.context_class(command), "json")
    except typer.Exit as refused:
        pytest.fail(
            f"`confiture {' '.join(row.command)} --format json` exits {refused.exit_code} — "
            f"fraiseql passes it at {row.source}"
        )
    assert accepted == "json"


runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def test_lint_still_accepts_format_table() -> None:
    """The application's lint gate prints a table (``fraises.yaml:214``)."""
    result = runner.invoke(app, ["lint", "--format", "table", "--list-rules"])
    output = _ANSI.sub("", result.output)
    assert "VALID_001" not in output, output
    assert result.exit_code == 0, output


def test_seed_validate_still_rejects_format_table() -> None:
    """``seed validate`` speaks text/json/csv and says so (``fraises.yaml:218``).

    the application chose ``--format text`` *because* ``table`` is refused with
    ``VALID_001``. An option factory that unified the two vocabularies would make
    that comment false in a way no consumer test notices.
    """
    result = runner.invoke(
        app, ["seed", "validate", "--prep-seed", "--static-only", "--format", "table"]
    )
    output = _ANSI.sub("", result.output)
    assert "VALID_001" in output, output
    assert result.exit_code == 5, output
