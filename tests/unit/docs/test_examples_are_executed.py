"""Every example directory is executed by CI, or states why it cannot be.

``.github/workflows/examples.yml`` runs ``examples/*/run.sh`` against a real
database, and explains itself in a comment:

    Every example that ships a run.sh is executed against a real database. An
    example that does not run is documentation of something that does not exist.

That was true of four directories out of thirteen. The nine silent ones included
``02-fraiseql-integration``, whose schema could not be applied to a database at
all, and ``04-production-sync-anonymization``, whose entire CLI was invented.

So the rule is inverted here: shipping a ``run.sh`` is the default, and *not*
shipping one requires a stated reason. The allow-list is the same idiom as
``tests/unit/test_one_sql_lexer.py`` and
``tests/unit/test_one_type_canonicaliser.py``, including the part that matters —
an entry that no longer matches anything is itself a failure, so the exemptions
cannot outlive the reason for them.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

# Directories with no run.sh, and why running them is not possible or not
# meaningful. A reason is a sentence about *this* directory, not a category:
# "it is only templates" has to be true of the files that are actually there.
NOT_EXECUTABLE: dict[str, str] = {
    "cicd": (
        "CI/CD templates for GitHub Actions, GitLab, Jenkins and Argo. They are "
        "meant to be copied into someone else's pipeline and cannot run here — "
        "there is no cluster, no runner and no database to deploy to. The "
        "commands they name are checked by "
        "test_examples_reference_real_commands.py instead."
    ),
    "hooks": (
        "Hook handler snippets. A hook runs when confiture invokes it during a "
        "migration; on its own there is nothing to execute."
    ),
    "linting": (
        "Lint rule configuration plus a shell file of example invocations. The "
        "rules apply to a schema this directory does not have; the invocations "
        "are checked by test_examples_reference_real_commands.py."
    ),
    "multi-agent-workflow": (
        "A walkthrough of two agents coordinating through the `coordinate` "
        "commands. Running it needs two agents and a shared coordination "
        "database, which a smoke test cannot stand up."
    ),
    "03-zero-downtime-migration": (
        "Medium 4 over FDW, between two live databases across a cutover. The "
        "scripts under scripts/ are the walkthrough; executing them needs two "
        "servers and a traffic switch."
    ),
    "07-external-emitter": (
        "An emitter plugin registered through an entry point. It is loaded by "
        "confiture at runtime from an installed distribution, and is exercised "
        "by tests/integration/test_external_emitter_example.py."
    ),
}


def _example_directories() -> list[Path]:
    """Tracked directories directly under ``examples/``."""
    out = subprocess.run(
        ["git", "ls-files", "--", "examples/"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    names = {line.split("/")[1] for line in out.splitlines() if line.count("/") >= 2}
    return sorted(REPO_ROOT / "examples" / name for name in names)


def test_every_example_runs_or_says_why_not() -> None:
    """An example ships an executable ``run.sh`` or holds an allow-list entry."""
    directories = _example_directories()
    assert len(directories) >= 10, "the examples lost their directories"

    failures: list[str] = []
    for directory in directories:
        run_sh = directory / "run.sh"
        exempt = directory.name in NOT_EXECUTABLE
        if run_sh.is_file():
            if exempt:
                failures.append(
                    f"examples/{directory.name}: ships run.sh and is also allow-listed; "
                    "remove the allow-list entry"
                )
            elif not os.access(run_sh, os.X_OK):
                failures.append(
                    f"examples/{directory.name}/run.sh is not executable, so "
                    "examples.yml would skip it"
                )
        elif not exempt:
            failures.append(
                f"examples/{directory.name}: no run.sh. Add one, or add an entry to "
                "NOT_EXECUTABLE saying why this example cannot be executed."
            )
    assert failures == [], "\n".join(failures)


def test_no_allow_list_entry_is_stale() -> None:
    """Every exemption names a directory that exists and still has no ``run.sh``.

    Without this the allow-list only ever grows, and an example that has since
    gained a run.sh keeps an exemption that reads as a standing decision.
    """
    present = {d.name for d in _example_directories()}
    failures = [
        f"NOT_EXECUTABLE['{name}']: no such directory under examples/"
        for name in NOT_EXECUTABLE
        if name not in present
    ]
    assert failures == [], "\n".join(failures)


def test_the_workflow_still_runs_every_run_sh() -> None:
    """``examples.yml`` globs ``examples/*/run.sh``, which is what makes adding one the fix.

    If the workflow ever moves to an explicit list, this guard stops meaning
    anything: a run.sh could exist and never be executed.
    """
    workflow = (REPO_ROOT / ".github/workflows/examples.yml").read_text()
    assert "examples/*/run.sh" in workflow, (
        "examples.yml no longer globs examples/*/run.sh; adding a run.sh may no "
        "longer cause it to be executed"
    )
