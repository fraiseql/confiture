"""A command's machine output has one writer, and so one envelope.

The error path has been one system since #145: ``cli/error_json.fail`` builds
``{"ok": false, "error": …}`` and nothing else does. The success path was 33
``json.dumps(`` sites in 18 modules, each choosing its own indentation, its own
stream and whether to say which parser read the SQL. ``helpers.emit`` is the one
writer now: it adds ``ok``, ``command`` and ``parser`` after whatever the payload
carries, and writes to ``--output`` or stdout. A call to ``json.dump``,
``json.dumps`` or a ``print_json`` anywhere else under ``cli/`` is a second
writer, and its payload leaves the envelope behind.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from rich.console import Console

from confiture.cli.helpers import emit

CLI_ROOT = Path(__file__).resolve().parents[2] / "python" / "confiture" / "cli"

#: The one writer.
WRITER = "helpers.py"

#: Modules that keep a writer of their own, and why.
EXEMPT: dict[str, str] = {}

WRITER_CALLS = {"dump", "dumps", "print_json"}


def _writers(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name in WRITER_CALLS:
            found.append(f"{path.relative_to(CLI_ROOT).as_posix()}:{node.lineno} {name}()")
    return found


def _modules() -> list[Path]:
    return [
        path
        for path in sorted(CLI_ROOT.rglob("*.py"))
        if path.name != WRITER and path.relative_to(CLI_ROOT).as_posix() not in EXEMPT
    ]


def test_only_the_emitter_writes_machine_output() -> None:
    found = [hit for path in _modules() for hit in _writers(path)]
    assert found == [], "machine output written outside helpers.emit:\n  " + "\n  ".join(found)


@pytest.mark.parametrize("module", sorted(EXEMPT))
def test_every_exemption_still_has_a_writer(module: str) -> None:
    path = CLI_ROOT / module
    assert path.exists() and _writers(path), f"{module} is exempt but writes nothing: delete it"


def test_the_emitter_adds_the_envelope_after_the_payload(
    capsys: pytest.CaptureFixture[str],
) -> None:
    import json

    from confiture.cli.helpers import emit

    emit({"success": True, "ok": False})
    payload = json.loads(capsys.readouterr().out)
    assert list(payload)[:2] == ["success", "ok"]
    assert payload["ok"] is False
    assert "parser" in payload


def test_the_emitter_writes_a_report_into_a_new_directory(tmp_path: Path) -> None:
    target = tmp_path / "reports" / "out.json"
    emit({"success": True}, target, Console(file=(tmp_path / "log").open("w")))
    assert json.loads(target.read_text())["ok"] is True
