"""Contract test pinning the confiture surface the fraisier adapter depends on.

`fraisier-core/crates/fraisier-adapter-confiture` is the FraiseQL stack's native,
in-process migration adapter (PRD §6.3). It drives confiture by spawning
``confiture migrate <subcommand>`` for exactly five subcommands —
``current`` / ``up`` / ``down-to`` / ``verify`` / ``preflight`` — always with
``--no-config`` + ``--format json`` + ``--output <file>`` and the DSN injected via
the ``CONFITURE_DATABASE_URL`` environment variable (never argv). It reads the
clean JSON back from the ``--output`` file and branches on confiture's process
exit codes.

This test is that contract, enforced inside *confiture's own* CI — the adapter is
a downstream consumer confiture cannot otherwise see. It mirrors the adapter's
``plan()`` (argv construction + the ``current``-rejects-``--migrations-dir`` rule)
and ``read_report_json`` (file-first) so a drift in any subcommand's flags, JSON
shape, or exit code fails here. See ``docs/reference/fraisier-adapter-contract.md``.

The surface assertions need no database. The end-to-end JSON/exit-code assertions
are DB-gated and skip when no PostgreSQL is reachable.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import psycopg
import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.error_codes import CANONICAL_EXIT_CODES, EXIT_CODE_MEANINGS

runner = CliRunner()
# Strip ANSI: CI (FORCE_COLOR) renders colored help that splits flag tokens.
_ANSI = re.compile(r"\x1b\[[0-9;]*m")

# The five subcommands the adapter's CAPABILITIES advertise + drive.
ADAPTER_SUBCOMMANDS = ["current", "up", "down-to", "verify", "preflight"]

# Adapter constants (fraisier-adapter-confiture/src/lib.rs): the codes it branches on.
UNINITIALISED_ERROR_CODE = "PRECON_1001"  # current → "no current revision"
NO_DSN_ERROR_CODE = "CONFIG_010"  # InvalidConfig
LOCK_EXIT_CODE = 6  # LOCK_1300, retriable

# The PFLIGHT_REPLICA_* namespace fraisier's blue-green window-safety gate keys on
# (fraisier-core/src/window_safety.rs blocks the deploy on the presence of ANY of
# these in preflight's issues[]). Pinned here as a cross-repo stability commitment:
# renames/removals are breaking (major bump); additions are allowed by extending
# this literal. See docs/reference/fraisier-adapter-contract.md.
EXPECTED_REPLICA_CODES = frozenset(
    {
        "PFLIGHT_REPLICA_ADD_COLUMN",
        "PFLIGHT_REPLICA_ADD_CONSTRAINT",
        "PFLIGHT_REPLICA_CHANGE_TYPE",
        "PFLIGHT_REPLICA_CREATE_INDEX",
        "PFLIGHT_REPLICA_DROP_COLUMN",
        "PFLIGHT_REPLICA_RENAME_COLUMN",
        "PFLIGHT_REPLICA_UNCLASSIFIED",
    }
)

_SCHEMAS_DIR = Path(__file__).resolve().parents[2] / "docs" / "reference" / "json-schemas"

# Two real migrations so `down-to` rolls something back.
_VERSIONS = [("20260101000001", "a"), ("20260101000002", "b")]


def _registry() -> Registry:
    """A registry mapping every sibling schema's filename to its resource, so the
    relative ``$ref``s (issue-object, _common, _preflight_defs) resolve.
    """
    registry = Registry()
    for path in _SCHEMAS_DIR.glob("*.schema.json"):
        resource = Resource.from_contents(
            json.loads(path.read_text()), default_specification=DRAFT202012
        )
        registry = registry.with_resource(uri=path.name, resource=resource)
    return registry


def _schema(name: str) -> Draft202012Validator:
    return Draft202012Validator(json.loads((_SCHEMAS_DIR / name).read_text()), registry=_registry())


# ---------------------------------------------------------------------------
# Layer A — surface / flag / exit-code contract (no database).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("subcommand", ADAPTER_SUBCOMMANDS)
def test_subcommand_exists_and_advertises_adapter_flags(subcommand: str) -> None:
    """Each adapter subcommand exists and accepts --no-config, --format, --output."""
    result = runner.invoke(app, ["migrate", subcommand, "--help"])
    assert result.exit_code == 0, result.output
    help_text = _ANSI.sub("", result.output)
    for flag in ("--no-config", "--format", "--output"):
        assert flag in help_text, f"`migrate {subcommand}` is missing {flag}"


def test_migrations_dir_gating_matches_adapter() -> None:
    """`current` rejects --migrations-dir; the other four accept it.

    Mirrors the adapter's ``subcommand_takes_migrations_dir`` (current reads only
    the tracking table, so it has no migration-file inputs and is invoked without
    the flag).
    """
    current_help = _ANSI.sub("", runner.invoke(app, ["migrate", "current", "--help"]).output)
    assert "--migrations-dir" not in current_help

    for subcommand in ("up", "down-to", "verify", "preflight"):
        other_help = _ANSI.sub("", runner.invoke(app, ["migrate", subcommand, "--help"]).output)
        assert "--migrations-dir" in other_help, f"`migrate {subcommand}` lost --migrations-dir"


def test_documented_exit_code_set_is_frozen() -> None:
    """The documented exit-code universe is exactly 0..8 (exit-codes.md contract)."""
    assert set(EXIT_CODE_MEANINGS) == set(range(9))


def test_adapter_pinned_error_codes_keep_their_exit_numbers() -> None:
    """The symbolic codes the adapter hardcodes still map to the numbers it expects."""
    assert CANONICAL_EXIT_CODES[UNINITIALISED_ERROR_CODE] == 2
    assert CANONICAL_EXIT_CODES[NO_DSN_ERROR_CODE] == 5
    assert CANONICAL_EXIT_CODES["LOCK_1300"] == LOCK_EXIT_CODE


def test_replica_code_namespace_is_a_stability_commitment() -> None:
    """The exact set fraisier's blue-green window-safety gate keys on (#154).

    fraisier blocks a deploy on the *presence* of any ``PFLIGHT_REPLICA_*`` issue
    in preflight's ``issues[]``. A rename of one of these codes would silently make
    that gate match nothing — blue-green would proceed on an uncertified migration
    with confiture CI still green. Pin the set so a rename fails here instead.
    """
    from confiture.core.linting.libraries.replica import replica_lint_codes

    assert replica_lint_codes() == EXPECTED_REPLICA_CODES


def test_replica_codes_keep_the_pflight_replica_prefix() -> None:
    """Every emittable replica code carries the prefix fraisier string-matches on."""
    from confiture.core.linting.libraries.replica import replica_lint_codes

    assert replica_lint_codes(), "the replica lint must emit at least one code"
    assert all(code.startswith("PFLIGHT_REPLICA_") for code in replica_lint_codes())


def test_preflight_summary_carries_window_safe_verdict(tmp_path: Path) -> None:
    """The default preflight summary exposes the typed `window_safe` verdict (#154).

    The fraisier window-safety gate can read one typed boolean instead of
    prefix-matching ``PFLIGHT_REPLICA_*`` codes. Filesystem-only — no DB needed —
    and validated against the published schema so the field is a pinned contract.
    """
    md = tmp_path / "migrations"
    md.mkdir()
    (md / "20260101000001_a.up.sql").write_text("ALTER TABLE t DROP COLUMN c;")
    (md / "20260101000001_a.down.sql").write_text("ALTER TABLE t ADD COLUMN c int;")
    report = tmp_path / "report.json"

    result = runner.invoke(
        app,
        [
            "migrate",
            "preflight",
            "--no-config",
            "--format",
            "json",
            "--output",
            str(report),
            "--migrations-dir",
            str(md),
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(report.read_text())
    _schema("migrate-preflight.schema.json").validate(payload)
    # DROP COLUMN is not forward-compatible for the shared-DB read window.
    assert payload["summary"]["window_safe"] is False


def test_version_output_shape_matches_adapter_parser() -> None:
    """`confiture --version` ends in the version token (adapter parse_version)."""
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0, result.output
    # The adapter takes the last whitespace-separated token as the version.
    tokens = _ANSI.sub("", result.output).split()
    assert tokens[0] == "confiture"
    assert tokens[-1][0].isdigit(), f"version token not numeric: {tokens[-1]!r}"


# ---------------------------------------------------------------------------
# Layer B — JSON shape + exit-code contract under the adapter's exact
# invocation (DB-gated). Mirrors the adapter's plan() + read_report_json().
# ---------------------------------------------------------------------------


def _connect(url: str) -> psycopg.Connection:
    try:
        return psycopg.connect(url)
    except psycopg.OperationalError as e:
        pytest.skip(f"PostgreSQL not available: {e}")


@pytest.fixture
def adapter_db(test_db_url: str):
    """A clean tracking DB. The adapter never sets a custom tracking table, so
    under --no-config it uses the default ``tb_confiture`` — clean it before/after.
    """
    conn = _connect(test_db_url)

    def _clean() -> None:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS tb_confiture CASCADE")
            for _v, name in _VERSIONS:
                cur.execute(f"DROP TABLE IF EXISTS eco_contract_{name} CASCADE")
        conn.commit()

    _clean()
    try:
        yield test_db_url
    finally:
        _clean()
        conn.close()


@pytest.fixture
def migrations_dir(tmp_path: Path) -> Path:
    md = tmp_path / "migrations"
    md.mkdir()
    for version, name in _VERSIONS:
        tbl = f"eco_contract_{name}"
        (md / f"{version}_{name}.up.sql").write_text(f"CREATE TABLE {tbl} (id int);")
        (md / f"{version}_{name}.down.sql").write_text(f"DROP TABLE {tbl};")
    return md


def _adapter_invoke(
    subcommand: str,
    *extra: str,
    dsn: str,
    report: Path,
    migrations_dir: Path,
):
    """Invoke a migrate subcommand exactly as the adapter's plan() builds it."""
    args = [
        "migrate",
        subcommand,
        *extra,
        "--no-config",
        "--format",
        "json",
        "--output",
        str(report),
    ]
    # The adapter gates --migrations-dir on subcommand_takes_migrations_dir.
    if subcommand != "current":
        args += ["--migrations-dir", str(migrations_dir)]
    return runner.invoke(app, args, env={"CONFITURE_DATABASE_URL": dsn})


def _read_report(result, report: Path) -> dict:
    """Read the JSON report file-first, then stdout — mirrors read_report_json."""
    if report.exists() and report.read_text().strip():
        return json.loads(report.read_text())
    return json.loads(result.output)


def test_adapter_full_flow_against_real_db(adapter_db, migrations_dir, tmp_path) -> None:
    """The whole adapter wire: current → up → current → verify → preflight → down-to.

    Every call uses --no-config + CONFITURE_DATABASE_URL + --output (the adapter's
    exact mode), each report validates against its published schema, the
    adapter-consumed fields are present, and every exit code is in the documented
    set. This is the regression guard for ECO-rec1.
    """
    dsn = adapter_db
    report = tmp_path / "report.json"

    def invoke(subcommand: str, *extra: str):
        report.unlink(missing_ok=True)
        result = _adapter_invoke(
            subcommand, *extra, dsn=dsn, report=report, migrations_dir=migrations_dir
        )
        assert result.exit_code in EXIT_CODE_MEANINGS, (
            f"`migrate {subcommand}` exited {result.exit_code}, "
            f"outside the documented set {sorted(EXIT_CODE_MEANINGS)}"
        )
        return result

    # 1. current on a fresh DB → exit 2 + PRECON_1001 envelope (adapter maps to "no revision").
    result = invoke("current")
    assert result.exit_code == 2
    envelope = _read_report(result, report)
    _schema("error-envelope.schema.json").validate(envelope)
    assert envelope["error"]["code"] == UNINITIALISED_ERROR_CODE

    # 2. up → exit 0; adapter reads applied[].version as the new head.
    result = invoke("up")
    assert result.exit_code == 0, result.output
    up_payload = _read_report(result, report)
    _schema("migrate-up.schema.json").validate(up_payload)
    applied_versions = [m["version"] for m in up_payload["applied"]]
    assert applied_versions == [v for v, _ in _VERSIONS]

    # 3. current after up → exit 0; revision is the latest head.
    result = invoke("current")
    assert result.exit_code == 0, result.output
    current_payload = _read_report(result, report)
    _schema("migrate-current.schema.json").validate(current_payload)
    assert current_payload["revision"] == _VERSIONS[-1][0]

    # 4. verify → adapter reads failed_count + results[].{version,name,status,error}.
    result = invoke("verify")
    assert result.exit_code in EXIT_CODE_MEANINGS, result.output
    verify_payload = _read_report(result, report)
    _schema("migrate-verify.schema.json").validate(verify_payload)
    assert verify_payload["failed_count"] == 0
    for entry in verify_payload["results"]:
        assert {"version", "name", "status", "error"} <= set(entry)

    # 5. preflight → {ok, summary, issues[]}; the --output path the adapter relies on.
    result = invoke("preflight")
    assert result.exit_code in (0, 7), result.output
    preflight_payload = _read_report(result, report)
    _schema("migrate-preflight.schema.json").validate(preflight_payload)
    assert isinstance(preflight_payload["ok"], bool)

    # 6. down-to the first version → exit 0; rolled_back lists the newer migration.
    result = invoke("down-to", _VERSIONS[0][0])
    assert result.exit_code == 0, result.output
    down_payload = _read_report(result, report)
    _schema("migrate-down-to.schema.json").validate(down_payload)
    assert down_payload["to"] == _VERSIONS[0][0]
    assert _VERSIONS[1][0] in down_payload["rolled_back"]


def test_adapter_dsn_handoff_is_env_only_under_no_config(
    adapter_db, migrations_dir, tmp_path
) -> None:
    """Under --no-config the env DSN is the sole source — proving the adapter handoff.

    A successful `migrate up` driven purely by CONFITURE_DATABASE_URL (no --config,
    no DSN in argv) is end-to-end proof that confiture honours the adapter's
    secrets-via-env contract.
    """
    report = tmp_path / "r.json"
    result = _adapter_invoke("up", dsn=adapter_db, report=report, migrations_dir=migrations_dir)
    assert result.exit_code == 0, result.output
    payload = _read_report(result, report)
    assert payload["success"] is True
    assert [m["version"] for m in payload["applied"]] == [v for v, _ in _VERSIONS]
