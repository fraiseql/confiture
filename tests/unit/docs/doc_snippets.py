"""Helpers for executable documentation guards.

These extract fenced code blocks from the project's Markdown docs so the
examples can be validated against the real implementation. The point is
anti-drift: a doc example that stops matching reality fails a test instead
of silently misleading a reader (or an agent).

Doc blocks opt in with an invisible anchor on the line *before* the fence::

    <!-- doctest:my-example -->
    ```yaml
    ...
    ```

The anchor is an HTML comment, so it never renders. ``fenced_after_anchor``
keys on it; ``all_fenced`` scans every fence of a given language.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

# doc_snippets.py lives at <repo>/tests/unit/docs/doc_snippets.py
REPO_ROOT = Path(__file__).resolve().parents[3]

_ANCHOR = "<!-- doctest:{name} -->"
_FENCE_RE = re.compile(r"```([^\n`]*)\n(.*?)```", re.DOTALL)


def read_doc(rel_path: str) -> str:
    """Read a repo-relative doc file as text (e.g. ``docs/reference/x.md``)."""
    return (REPO_ROOT / rel_path).read_text(encoding="utf-8")


def fenced_after_anchor(markdown: str, name: str) -> str:
    """Return the body of the first fenced block following ``<!-- doctest:name -->``.

    Raises AssertionError if the anchor or a following fence is missing — a
    missing anchor is a doc-maintenance bug the guard should surface loudly.
    """
    anchor = _ANCHOR.format(name=name)
    idx = markdown.find(anchor)
    assert idx != -1, f"doctest anchor {anchor!r} not found in doc"
    match = _FENCE_RE.search(markdown, idx + len(anchor))
    assert match is not None, f"no fenced code block follows anchor {anchor!r}"
    return match.group(2)


def all_fenced(markdown: str, lang: str) -> list[str]:
    """Return the bodies of every fenced block whose info string starts with ``lang``."""
    blocks: list[str] = []
    for match in _FENCE_RE.finditer(markdown):
        info = match.group(1).strip().split()
        if info and info[0] == lang:
            blocks.append(match.group(2))
    return blocks


def confiture_imports(py_source: str) -> list[tuple[str, str]]:
    """Return ``(module, name)`` pairs for every ``confiture`` import in a snippet.

    ``name`` is empty for a plain ``import confiture.x``. Snippets that aren't
    valid standalone Python (bare signatures, dataclass stubs) are skipped — they
    carry no import lines to resolve. Only imports are inspected; fence bodies
    are never executed.
    """
    try:
        tree = ast.parse(py_source)
    except SyntaxError:
        return []
    pairs: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("confiture"):
            pairs.extend((node.module, alias.name) for alias in node.names)
        elif isinstance(node, ast.Import):
            pairs.extend(
                (alias.name, "") for alias in node.names if alias.name.startswith("confiture")
            )
    return pairs


def assert_doc_imports_resolve(rel_path: str) -> int:
    """Assert every ``confiture`` import in a doc's python fences resolves.

    Returns the number of import references checked (callers can assert it's > 0).
    """
    import importlib

    fences = all_fenced(read_doc(rel_path), "python")
    pairs = [pair for fence in fences for pair in confiture_imports(fence)]
    for module, name in pairs:
        mod = importlib.import_module(module)
        if name:
            assert hasattr(mod, name), f"{module}.{name} referenced in {rel_path} does not exist"
    return len(pairs)
