"""``emit`` stamps the envelope; a command never spells its own ``command``.

``emit`` sets ``command`` to the path as typed after ``confiture`` (``migrate
schema-to-schema setup``). ``migrate schema-to-schema`` passed its own bare name
(``"setup"``), which won — so its payloads said one thing and its error envelope,
written by the boundary, another. A payload dict passed to ``emit`` must not carry
``command`` (nor ``ok``, which ``emit`` also owns).
"""

from __future__ import annotations

import ast
from pathlib import Path

CLI = Path(__file__).resolve().parents[2] / "python" / "confiture" / "cli"
_OWNED = {"command", "ok"}


def _spelled_envelope_keys() -> list[str]:
    found = []
    for path in sorted(CLI.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "emit"):
                continue
            payload = node.args[0] if node.args else None
            if isinstance(payload, ast.Dict):
                keys = {k.value for k in payload.keys if isinstance(k, ast.Constant)}
                found.extend(
                    f"{path.relative_to(CLI)}:{node.lineno} {key}" for key in sorted(keys & _OWNED)
                )
    return found


def test_no_command_spells_an_envelope_key_emit_owns() -> None:
    assert _spelled_envelope_keys() == []
