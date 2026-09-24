"""One SQL-tree walk: ``builder.files_under`` is how confiture lists a tree of ``.sql`` files.

A directory of schema or seed files is a tree: ``include_dirs: [db/schema]``
builds every ``.sql`` under it, sorted by path. A second walk is a second answer
to "which files are in this directory", and every second answer confiture had
disagreed with the first: level 1 scanned a nested seed that level 5 never
executed, ``apply_seeds`` loaded the top level of a tree ``validate_seeds`` read
whole, and ``migrate diff --to <dir>`` compared against a schema missing its
subdirectories (#386).

A directory of migrations or schema snapshots is not a tree. It is a flat listing
read by name — a version prefix, a ``.up.sql`` suffix — and the migrator never
descends into it, so the modules that list one are named below with the reason.
Each entry is ``module:receiver`` for one walk; an entry that matches nothing
fails, so the table is an edit, never an escape.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
# The source tree, not the imported package: the Publish workflow runs this suite
# against the built wheel, where ``confiture.__file__`` lives in the virtualenv.
PACKAGE = REPO / "python" / "confiture"
WALKER = PACKAGE / "core" / "builder.py"

_MIGRATIONS = (
    "a migrations directory is a flat listing the migrator reads by version and "
    "suffix; it never descends into a subdirectory, so neither does this"
)
_MIGRATIONS_RECURSIVE = (
    "a lint over migration files, recursive since it was written; the migrator lists "
    "the directory flat — a migrations listing, not an SQL tree"
)
_SNAPSHOTS = (
    "`db/schema_history/` is a flat listing of schema snapshots named by version, "
    "one file per migration; there is no tree to walk"
)

# ``module:receiver`` → why that walk is not a walk of an SQL tree.
ALLOWED: dict[str, str] = {
    "cli/commands/apply_as.py:migrations_dir": _MIGRATIONS,
    "cli/commands/migrate/introspect.py:snapshots_dir": _SNAPSHOTS,
    "cli/helpers.py:migrations_dir": _MIGRATIONS,
    "cli/idempotency.py:migrations_dir": _MIGRATIONS,
    "cli/commands/migrate/preflight.py:migrations_dir": _MIGRATIONS,
    "core/_migrator/discovery.py:migrations_dir": _MIGRATIONS,
    "core/_migrator/policy.py:snapshots_dir": _SNAPSHOTS,
    "core/baseline_detector.py:self.snapshots_dir": _SNAPSHOTS,
    "core/change_set/__init__.py:migrations_dir": _MIGRATIONS,
    "core/checksum.py:migrations_dir": _MIGRATIONS,
    "core/import_checker.py:self.migrations_dir": _MIGRATIONS,
    "core/migration_verifier.py:self.migrations_dir": (
        "`.verify.sql` sidecars sit beside the migrations they verify, in the same flat listing"
    ),
    "core/preflight.py:migrations_dir": _MIGRATIONS,
    "core/strategy.py:migrations_dir": _MIGRATIONS,
    "core/validation/config_validator.py:migrations_dir": _MIGRATIONS,
    "core/validation/data_assertions.py:migrations_dir": _MIGRATIONS,
    "core/linting/libraries/replica.py:migrations_dir": _MIGRATIONS,
    "core/linting/libraries/acl.py:migrations_dir": _MIGRATIONS_RECURSIVE,
    "core/linting/libraries/ownership.py:migrations_dir": _MIGRATIONS_RECURSIVE,
    "core/ownership_fixer.py:migrations_dir": _MIGRATIONS_RECURSIVE,
    "core/idempotency/validator.py:directory": (
        "`migrate validate --idempotent` over a migrations directory, with the caller's "
        "own pattern (`*.up.sql`) and its own choice of depth"
    ),
    "models/sql_file_migration.py:migrations_dir": _MIGRATIONS,
    "testing/fixtures/migration_runner.py:self.migrations_dir": _MIGRATIONS,
    "testing/loader.py:migrations_dir": _MIGRATIONS,
    "core/hooks/builtin/backup_hook.py:backup_dir": (
        "the backup hook rotates the dumps it wrote, by suffix and age; a backup is "
        "not DDL a command reads"
    ),
    "core/tree_renumber.py:old_dir": (
        "renumbering allocates prefixes within one directory; a subdirectory is numbered "
        "on its own, so the files beside each other are the ones renumbered together"
    ),
}


def _names_sql(pattern: ast.expr) -> bool:
    """Whether a glob pattern selects ``.sql`` files — or cannot be read to say."""
    if isinstance(pattern, ast.Constant):
        return isinstance(pattern.value, str) and pattern.value.endswith(".sql")
    if isinstance(pattern, ast.JoinedStr) and pattern.values:
        last = pattern.values[-1]
        return not isinstance(last, ast.Constant) or str(last.value).endswith(".sql")
    return True


def _filters_sql(node: ast.comprehension) -> bool:
    """A comprehension over ``iterdir()`` that keeps the ``.sql`` files."""
    call = node.iter
    if not (
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "iterdir"
    ):
        return False
    return any(
        isinstance(const, ast.Constant) and const.value == ".sql"
        for condition in node.ifs
        for const in ast.walk(condition)
    )


def _walks(path: Path) -> list[tuple[str, int]]:
    """``(receiver, line)`` for every hand-written walk of ``.sql`` files in *path*."""
    found: list[tuple[str, int]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.comprehension) and _filters_sql(node):
            call = node.iter
            assert isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
            found.append((ast.unparse(call.func.value), call.lineno))
            continue
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        receiver = ast.unparse(node.func.value)
        globs_sql = node.func.attr in ("glob", "rglob") and node.args and _names_sql(node.args[0])
        walks = node.func.attr == "walk" and receiver != "ast"
        if globs_sql or walks:
            found.append((receiver, node.lineno))
    return found


def _by_key() -> dict[str, list[int]]:
    result: dict[str, list[int]] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        if path == WALKER:
            continue
        module = path.relative_to(PACKAGE).as_posix()
        for receiver, line in _walks(path):
            result.setdefault(f"{module}:{receiver}", []).append(line)
    return result


def test_no_module_walks_an_sql_tree_by_hand() -> None:
    offenders = [
        f"{key} (line {line})"
        for key, lines in _by_key().items()
        if key not in ALLOWED
        for line in lines
    ]
    assert offenders == [], (
        "a second walk of an SQL tree — read it through builder.files_under:\n  "
        + "\n  ".join(offenders)
    )


def test_allow_list_is_current() -> None:
    present = set(_by_key())
    stale = sorted(key for key in ALLOWED if key not in present)
    assert stale == [], f"allow-list entries with nothing left to allow: {stale}"


def test_every_allow_list_entry_states_a_reason() -> None:
    vague = [key for key, reason in ALLOWED.items() if len(reason) < 40]
    assert vague == [], f"entries that explain nothing: {vague}"


def test_the_guard_sees_each_shape_of_walk(tmp_path: Path) -> None:
    source = (
        "a = d.glob('*.sql')\n"
        "b = d.rglob(f'{v}_*.up.sql')\n"
        "c = d.glob(pattern)\n"
        "e = [f for f in d.iterdir() if f.suffix == '.sql']\n"
        "g = os.walk(d)\n"
        "h = d.glob('*.py')\n"
        "i = ast.walk(tree)\n"
    )
    probe = tmp_path / "probe.py"
    probe.write_text(source, encoding="utf-8")
    assert sorted(line for _, line in _walks(probe)) == [1, 2, 3, 4, 5]
