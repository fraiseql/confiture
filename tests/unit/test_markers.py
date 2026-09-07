"""Markers mean what they say (TST-04, Cycle 4).

Every collected test carries exactly one *layer* marker — ``unit``,
``integration``, ``e2e``, ``performance`` or ``contract`` — assigned from its
directory by ``tests/conftest.py``, so ``-m integration`` selects the whole
layer and nothing else. And every assertion that puts an upper bound on a
measured duration lives in a test marked ``benchmark``: such a test passes or
fails with the load on the machine, so it runs only when asked for
(``-m benchmark``), never inside the default gate.
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

import pytest

TESTS_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = TESTS_ROOT.parent
LAYERS = frozenset({"unit", "integration", "e2e", "performance", "contract"})

# Lower-case on purpose: `Duration.SECONDS` is an enum, not a measurement.
_TIMING_NAME = re.compile(r"(elapsed|duration|took|_time\b|_time_|time_ms|seconds|_ms\b|speedup)")


def layer_for(path: Path) -> str:
    """The layer a test file belongs to, from its directory under ``tests/``."""
    return path.relative_to(TESTS_ROOT).parts[0]


# ---------------------------------------------------------------------------
# Layer markers — checked on the items of the running session
# ---------------------------------------------------------------------------


def test_every_collected_item_has_exactly_one_layer_marker(request: pytest.FixtureRequest) -> None:
    offenders = []
    for item in request.session.items:
        layers = {m.name for m in item.iter_markers()} & LAYERS
        if len(layers) != 1:
            offenders.append(f"{item.nodeid}: {sorted(layers) or 'none'}")
    assert offenders == [], (
        f"{len(offenders)} items without exactly one layer marker:\n  "
        + "\n  ".join(offenders[:15])
    )


def test_layer_marker_matches_the_directory(request: pytest.FixtureRequest) -> None:
    mismatched = []
    for item in request.session.items:
        layers = {m.name for m in item.iter_markers()} & LAYERS
        expected = layer_for(Path(str(item.path)))
        if layers and layers != {expected}:
            mismatched.append(f"{item.nodeid}: {sorted(layers)} (directory says {expected})")
    assert mismatched == [], "\n  ".join(mismatched[:15])


def test_layer_and_benchmark_markers_are_registered() -> None:
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    registered = {
        m.split(":")[0].strip() for m in config["tool"]["pytest"]["ini_options"]["markers"]
    }
    assert LAYERS | {"benchmark"} <= registered, sorted((LAYERS | {"benchmark"}) - registered)


def test_benchmarks_are_excluded_by_default() -> None:
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    addopts = config["tool"]["pytest"]["ini_options"]["addopts"]
    joined = " ".join(addopts)
    assert (
        "-m not benchmark" in joined
        or '-m "not benchmark"' in joined
        or "-m=not benchmark" in joined
    ), addopts


# ---------------------------------------------------------------------------
# Wall-clock upper bounds live under `benchmark`
# ---------------------------------------------------------------------------


def _mentions_timing(node: ast.AST) -> bool:
    return bool(_TIMING_NAME.search(ast.unparse(node)))


def _is_upper_bound_on_timing(test: ast.expr) -> bool:
    """``elapsed < x`` / ``x > elapsed`` shapes; a lower bound is not load-sensitive."""
    if not isinstance(test, ast.Compare):
        return False
    operands = [test.left, *test.comparators]
    for left, op, right in zip(operands, test.ops, operands[1:], strict=False):
        if isinstance(op, (ast.Lt, ast.LtE)) and _mentions_timing(left):
            return True
        if isinstance(op, (ast.Gt, ast.GtE)) and _mentions_timing(right):
            return True
    return False


def _has_benchmark_mark(decorators: list[ast.expr]) -> bool:
    return any("benchmark" in ast.unparse(d) for d in decorators)


def _module_marked(tree: ast.Module) -> bool:
    for node in tree.body:
        is_pytestmark = isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets
        )
        if is_pytestmark and "benchmark" in ast.unparse(node.value):
            return True
    return False


def _unmarked_in(node: ast.AST, marked: bool, rel: str, findings: list[str]) -> None:
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.ClassDef):
            _unmarked_in(child, marked or _has_benchmark_mark(child.decorator_list), rel, findings)
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if marked or _has_benchmark_mark(child.decorator_list):
                continue
            findings.extend(
                f"tests/{rel}:{sub.lineno}: {ast.unparse(sub.test)}"
                for sub in ast.walk(child)
                if isinstance(sub, ast.Assert) and _is_upper_bound_on_timing(sub.test)
            )
        else:
            _unmarked_in(child, marked, rel, findings)


def find_unmarked_wall_clock_assertions(root: Path) -> list[str]:
    findings: list[str] = []
    for path in sorted(root.rglob("test_*.py")):
        rel = path.relative_to(root)
        if path.name == Path(__file__).name:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        _unmarked_in(tree, _module_marked(tree), rel.as_posix(), findings)
    return findings


def test_wall_clock_upper_bounds_are_benchmarks() -> None:
    findings = find_unmarked_wall_clock_assertions(TESTS_ROOT)
    assert findings == [], (
        f"{len(findings)} duration upper bounds outside `@pytest.mark.benchmark`:\n  "
        + "\n  ".join(findings)
    )


def _scan(source: str) -> int:
    tree = ast.parse(source)
    module_marked = _module_marked(tree)
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            marked = module_marked or _has_benchmark_mark(node.decorator_list)
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.Assert)
                    and _is_upper_bound_on_timing(sub.test)
                    and not marked
                ):
                    count += 1
    return count


def test_detector_flags_upper_bounds_only() -> None:
    assert _scan("def test_a():\n    assert elapsed < 1.0\n") == 1
    assert _scan("def test_a():\n    assert 0.03 < elapsed < 0.5\n") == 1
    assert _scan("def test_a():\n    assert duration_ms <= 200\n") == 1
    assert _scan("def test_a():\n    assert elapsed >= 0.03\n") == 0
    assert _scan("def test_a():\n    assert count < 3\n") == 0


def test_detector_honours_marks() -> None:
    assert _scan("@pytest.mark.benchmark\ndef test_a():\n    assert elapsed < 1.0\n") == 0
    assert (
        _scan("pytestmark = pytest.mark.benchmark\n\ndef test_a():\n    assert elapsed < 1.0\n")
        == 0
    )
    assert (
        _scan(
            "pytestmark = [pytest.mark.slow, pytest.mark.benchmark]\n\ndef test_a():\n    assert elapsed < 1.0\n"
        )
        == 0
    )
