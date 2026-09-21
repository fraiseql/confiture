"""Every command confiture ships is run, by its command line, against a real database.

A leaf of the live Click tree counts as covered when a file under ``tests/integration``
or ``tests/e2e`` holds its argv — ``runner.invoke(app, ["migrate", "rebuild", …])`` or a
subprocess's ``["confiture", "migrate", "rebuild", …]`` — or when the golden recorder
``scripts/refresh_model_goldens.py``, which the integration suite executes, does.
Invoking the *library* under a command does not count, and that is the point:
``test_pggit_integration.py`` drives ``PgGitClient`` against a database and would make
``confiture branch`` look covered while no test has ever typed it.

``NOT_RUN`` holds the leaves no such test runs, each with the reason it is allowed to
stay that way. It is empty: every command confiture ships is run by its command line.
"""

from __future__ import annotations

import ast

from tests.unit.docs.command_truth import REPO_ROOT, resolve, root

#: Where a command line counts: the suites that run against a database, and the
#: recorder the golden tests execute.
RUNNERS = (
    *sorted((REPO_ROOT / "tests" / "integration").rglob("*.py")),
    *sorted((REPO_ROOT / "tests" / "e2e").rglob("*.py")),
    REPO_ROOT / "scripts" / "refresh_model_goldens.py",
)

#: A leaf no test runs by argv, and why that is acceptable.
NOT_RUN: dict[tuple[str, ...], str] = {}


def _leaves(node: object, path: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    """Every command path under *node*. Typer vendors click, so a group is what has children."""
    children = getattr(node, "commands", None)
    if not children:
        return [path]
    return [leaf for name, child in children.items() for leaf in _leaves(child, (*path, name))]


def _argv_prefix(node: ast.List | ast.Tuple) -> tuple[str, ...]:
    words: list[str] = []
    for element in node.elts:
        if not (isinstance(element, ast.Constant) and isinstance(element.value, str)):
            break
        words.append(element.value)
    return tuple(words[1:] if words[:1] == ["confiture"] else words)


def _run_leaves(sources: list[str], leaves: set[tuple[str, ...]]) -> set[tuple[str, ...]]:
    """The leaves some literal argv in *sources* names in full."""
    found: set[tuple[str, ...]] = set()
    for source in sources:
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, (ast.List, ast.Tuple)) and (words := _argv_prefix(node)):
                path, _, _ = resolve(words)
                if tuple(path) in leaves:
                    found.add(tuple(path))
    return found


LEAVES = set(_leaves(root()))


def test_the_census_reads_the_live_tree() -> None:
    assert len(LEAVES) > 50, "the tree walk found almost nothing — it would pass vacuously"


def test_the_census_reads_an_argv_and_not_a_library_call() -> None:
    """The guard, seen red: a command line counts, a call into the library does not."""
    sources = [
        'runner.invoke(app, ["migrate", "rebuild", "-c", cfg, "-y"])',
        "PgGitClient(conn).create_branch('x')",
    ]
    assert _run_leaves(sources, LEAVES) == {("migrate", "rebuild")}


def test_not_run_entries_state_a_reason_and_name_a_leaf() -> None:
    assert all(reason.strip() for reason in NOT_RUN.values())
    assert set(NOT_RUN) <= LEAVES, set(NOT_RUN) - LEAVES


def test_every_command_is_run_by_its_command_line() -> None:
    run = _run_leaves([path.read_text(encoding="utf-8") for path in RUNNERS], LEAVES)
    holes = sorted(LEAVES - run - set(NOT_RUN))
    assert holes == [], f"{len(holes)} commands no test runs by argv:\n  " + "\n  ".join(
        " ".join(hole) for hole in holes
    )
