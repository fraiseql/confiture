"""Executable guard: docs/api/migrator.md references only real symbols.

DOCS-C2 / DOCS-L3 anti-drift guard. The API doc historically described a
``Migrator`` surface that does not exist (``apply_all``, ``rollback_to``,
``connect_async``, ``MigrationAlreadyApplied`` …). This guard pins the doc to
the real public API three ways:

1. every ``confiture`` import in a python fence resolves (kills fictional
   classes / exceptions);
2. the methods the doc teaches actually exist on the live objects;
3. the specific fictional names can never reappear in the doc text.

Only *import* statements are resolved — fence bodies are never executed.
"""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

from doc_snippets import all_fenced, assert_doc_imports_resolve, read_doc

import confiture
from confiture import Migrator, MigratorSession

API_DOC = "docs/api/migrator.md"

# The real public MigratorSession surface a user drives.
DOCUMENTED_SESSION_METHODS = [
    "status",
    "current_revision",
    "up",
    "down",
    "down_to",
    "reinit",
    "rebuild",
    "preflight",
    "run_against",
]

# Names from the old fictional API that must never re-enter the doc.
FORBIDDEN_TOKENS = [
    "apply_all",
    "rollback_to",
    "connect_async",
    "get_applied_versions",
    "find_pending",
    "table_name=",
    "MigrationAlreadyApplied",
    "MigrationNotApplied",
    "MigrationResult",
    "AppliedMigration",
    "MigrationStatus",
    "confiture_migrations",
]


def test_every_confiture_import_in_the_doc_resolves() -> None:
    """Each `from confiture... import X` in the doc imports a real symbol."""
    checked = assert_doc_imports_resolve(API_DOC)
    assert checked, "expected at least one confiture import in the API doc"


def test_documented_session_methods_exist() -> None:
    """Every MigratorSession method the doc teaches is real and callable."""
    for method in DOCUMENTED_SESSION_METHODS:
        attr = getattr(MigratorSession, method, None)
        assert callable(attr), f"MigratorSession.{method} (documented) is missing"


def test_from_config_is_the_documented_entrypoint() -> None:
    """Migrator.from_config exists and the ctor uses migration_table, not table_name."""
    assert hasattr(Migrator, "from_config"), "Migrator.from_config (documented) is missing"
    params = inspect.signature(Migrator.__init__).parameters
    assert "migration_table" in params, "ctor should accept migration_table"
    assert "table_name" not in params, "ctor uses migration_table, not the fictional table_name"


def test_no_fictional_api_names_in_the_doc() -> None:
    """The old fictional API names never reappear in the doc."""
    text = read_doc(API_DOC)
    leaked = [tok for tok in FORBIDDEN_TOKENS if tok in text]
    assert not leaked, f"fictional API names present in {API_DOC}: {leaked}"


# ---------------------------------------------------------------------- #
# The signature fences                                                    #
# ---------------------------------------------------------------------- #
#
# The doc hand-copies each verb's signature into a ```python fence. That is the
# third echo of a signature written once in the source (the other two — the
# `Args:` block and the forwarding call — are pinned by
# `tests/unit/test_one_session_signature.py`), and it is the echo that drifted
# furthest: `up()` was shown with thirteen of its seventeen parameters, and all
# four lock-taking verbs claimed `lock_timeout: int = 30000` years after the
# default became `None`, meaning "read `migration.locking` from the environment".
#
# Parameter *names*, their order, and their *defaults* are compared. Annotations
# are deliberately not: the doc expands aliases for a reader who has not met them
# (`Callable[[UpEvent], None]` for `UpObserver`, quoted forward references), and
# pinning those would force the doc to be less clear than prose allows.

# Every `def` fence in the doc, and the source the real signature lives in.
SIGNATURE_FENCES: dict[str, tuple[str, str]] = {
    "from_config": ("core/_migrator/engine.py", "Migrator"),
    "status": ("core/_migrator/session.py", "MigratorSession"),
    "current_revision": ("core/_migrator/session.py", "MigratorSession"),
    "up": ("core/_migrator/session.py", "MigratorSession"),
    "down": ("core/_migrator/session.py", "MigratorSession"),
    "down_to": ("core/_migrator/session.py", "MigratorSession"),
    "apply_one": ("core/_migrator/session.py", "MigratorSession"),
}

PACKAGE = Path(confiture.__file__).resolve().parent


def _signature(fn: ast.FunctionDef) -> tuple[list[str], dict[str, str]]:
    """Parameter names in call order, and each default as source text."""
    args = fn.args
    positional = [a for a in args.posonlyargs + args.args if a.arg not in {"self", "cls"}]
    names = [a.arg for a in positional] + [a.arg for a in args.kwonlyargs]

    defaults: dict[str, str] = {}
    tail = positional[len(positional) - len(args.defaults) :]
    for arg, default in zip(tail, args.defaults, strict=True):
        defaults[arg.arg] = ast.unparse(default)
    for arg, default in zip(args.kwonlyargs, args.kw_defaults, strict=True):
        if default is not None:
            defaults[arg.arg] = ast.unparse(default)
    return names, defaults


def _doc_fence_signatures() -> dict[str, tuple[list[str], dict[str, str]]]:
    """Every ``def`` a python fence in the API doc declares."""
    found: dict[str, tuple[list[str], dict[str, str]]] = {}
    for fence in all_fenced(read_doc(API_DOC), "python"):
        if not re.search(r"^\s*def \w+\(", fence, re.M):
            continue
        for node in ast.walk(ast.parse(fence)):
            if isinstance(node, ast.FunctionDef):
                found[node.name] = _signature(node)
    return found


def _real_signature(
    module_rel: str, class_name: str, fn_name: str
) -> tuple[list[str], dict[str, str]]:
    """The signature as the source declares it, read the same way as the fence."""
    tree = ast.parse((PACKAGE / module_rel).read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == fn_name)
    return _signature(fn)


def test_signature_fence_table_is_exhaustive() -> None:
    """Every `def` fence in the doc is covered, and every entry is really there."""
    fences = set(_doc_fence_signatures())
    assert fences == set(SIGNATURE_FENCES), (
        f"fences in {API_DOC}: {sorted(fences)}; "
        f"SIGNATURE_FENCES: {sorted(SIGNATURE_FENCES)}. A fence with no entry is an "
        f"unchecked copy of a signature — add it."
    )


def test_doc_signatures_match_the_source() -> None:
    """Agreement: the copied fence names the same parameters, in order, with the same defaults."""
    fences = _doc_fence_signatures()
    assert fences, "no signature fences found — this guard is inspecting nothing"
    for name, (module_rel, class_name) in SIGNATURE_FENCES.items():
        doc_names, doc_defaults = fences[name]
        real_names, real_defaults = _real_signature(module_rel, class_name, name)
        assert doc_names == real_names, (
            f"{API_DOC} shows {class_name}.{name}({', '.join(doc_names)}); the real "
            f"signature is ({', '.join(real_names)})"
        )
        wrong = {
            param: (shown, real_defaults.get(param))
            for param, shown in doc_defaults.items()
            if shown != real_defaults.get(param)
        }
        assert not wrong, (
            f"{API_DOC} gives {class_name}.{name} defaults the code does not have "
            f"(shown, real): {wrong}"
        )
