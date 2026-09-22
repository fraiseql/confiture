"""``docs/reference/platform-api.md`` is generated from ``confiture.platform`` and current.

The seam's contract is its signatures and fields
(``tests/contract/test_platform_surface.py``), so its reference is rendered from
them: every exported name, its signature or its fields, and its docstring —
nothing hand-copied that could drift. ``scripts/gen_platform_reference.py
--check`` runs in the Lint leg beside the other generators.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from confiture import platform

REPO = Path(__file__).resolve().parents[3]
DOC = REPO / "docs" / "reference" / "platform-api.md"


def _generator():
    script = REPO / "scripts" / "gen_platform_reference.py"
    spec = importlib.util.spec_from_file_location("gen_platform_reference", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_reference_is_the_generated_one() -> None:
    gen = _generator()
    text = DOC.read_text(encoding="utf-8")
    assert gen.BEGIN in text and gen.END in text, "platform-api.md has no generated block"
    current = gen.BEGIN + text.split(gen.BEGIN, 1)[1].split(gen.END, 1)[0] + gen.END
    assert current == gen.render(), "stale: run scripts/gen_platform_reference.py --write"


def test_every_exported_name_has_a_heading() -> None:
    rendered = _generator().render()
    missing = [name for name in platform.__all__ if f"### `{name}`" not in rendered]
    assert missing == []


def test_every_exported_callable_and_class_says_what_it_is() -> None:
    undocumented = [
        name
        for name in platform.__all__
        if callable(getattr(platform, name)) and not (getattr(platform, name).__doc__ or "").strip()
    ]
    assert undocumented == []
