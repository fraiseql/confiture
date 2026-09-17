"""Every ``from confiture… import …`` the documentation shows resolves (issue #287).

``tests/unit/docs/`` holds twenty guards, two of them about fictional API
surface — and **1940 lines documenting two Python APIs that never existed**
passed both. ``docs/api/wizard.md`` imported ``confiture.wizard``;
``docs/api/linting.md`` imported ``confiture.linting`` and subclassed a ``Rule``
with a ``register_rule`` decorator. Neither module has ever been in the package.

Why the existing guards missed them:

- ``test_doc_api_symbols.py`` checks a **hand-listed** set of documents and
  symbols, so a document nobody adds is not checked — the same rot one level up,
  needing an update from exactly the person who forgot to update the docs.
- ``test_doc_no_fictional_names.py`` is a **blocklist** of five known-bad
  strings, so it can only catch fiction someone has already found.

Neither asks the general question. The ``confiture lint --rules
db/linting/rules.py`` sitting in the same file *was* caught, by
``test_docs_reference_real_commands.py``, because that guard resolves against
the live Typer app rather than a list. The API beside it was invisible.

This is that guard applied to imports: extract every ``from confiture… import
…`` and ``import confiture…`` from the **code regions** of the corpus — prose is
excluded because the repair for a fiction often has to *name* it — and resolve
the module with ``importlib`` and each symbol with ``getattr``. No snippet body
is executed; importing confiture's own modules is not executing the document.

``CHANGELOG.md`` and ``docs/release-notes/`` are out, as they are for the
command guard: they record what was announced at a version, and
``release-notes/v0.5.0.md`` is the *origin* of both fictions above. It got an
erratum rather than a rewrite, because a release note is a record.
"""

from __future__ import annotations

import importlib
import importlib.util
import re

import pytest
from command_truth import REPO_ROOT, code_regions, tracked

#: ``from confiture.x import a, b`` or ``import confiture.x``. Anchored at the
#: start of a line so a sentence that happens to contain the words does not
#: match, and confined to code regions besides.
IMPORT = re.compile(
    r"^[ \t]*(?:from[ \t]+(confiture[\w.]*)[ \t]+import[ \t]+([^\n#]+)"
    r"|import[ \t]+(confiture[\w.]*))",
    re.MULTILINE,
)

ROOT_DOCUMENTS = ("README.md", "PRD.md", "ARCHITECTURE.md", "CLAUDE.md")

MIN_IMPORT_SITES = 120

#: Imports that are correct to show and impossible to resolve, with the reason.
#: Shrink-only, in the idiom of ``test_one_sql_lexer.py``: an entry matching
#: nothing fails, so a reason cannot outlive the thing it explains.
KNOWN_UNRESOLVABLE: dict[tuple[str, str], str] = {}


def corpus():
    """The documents that tell a reader what to import *today*."""
    files = [
        path
        for path in tracked("docs/**/*.md")
        if "release-notes" not in path.relative_to(REPO_ROOT).as_posix()
    ]
    files += tracked(*ROOT_DOCUMENTS)
    return sorted(set(files))


def import_sites():
    """``(file, module, symbol | None)`` for every documented confiture import."""
    sites = []
    for path in corpus():
        rel = path.relative_to(REPO_ROOT).as_posix()
        for region in code_regions(path):
            for match in IMPORT.finditer(region):
                module = match.group(1) or match.group(3)
                names = match.group(2) or ""
                if not names.strip():
                    sites.append((rel, module, None))
                    continue
                for raw in names.replace("(", "").replace(")", "").split(","):
                    name = raw.strip().split(" as ")[0].strip()
                    if name and name != "*":
                        sites.append((rel, module, name))
    return sites


SITES = import_sites()


def _resolve(module: str, symbol: str | None) -> str | None:
    """``None`` when the import would work, else what is wrong with it."""
    try:
        if importlib.util.find_spec(module) is None:
            return f"no module named {module!r}"
    except (ImportError, ValueError, ModuleNotFoundError):
        return f"no module named {module!r}"
    try:
        imported = importlib.import_module(module)
    except (
        Exception
    ) as exc:  # Reason: a module that cannot import is as broken as one that is absent
        return f"{module!r} does not import: {type(exc).__name__}: {exc}"
    if symbol is not None and not hasattr(imported, symbol):
        return f"{module!r} has no {symbol!r}"
    return None


def test_the_corpus_was_found():
    """A floor: an empty corpus would make every assertion below vacuous."""
    assert len(corpus()) > 80
    assert len(SITES) >= MIN_IMPORT_SITES, (
        f"only {len(SITES)} import sites found; the extractor has probably stopped matching"
    )


def test_the_extractor_reads_code_not_prose():
    """A sentence naming a fictional import must not be a finding.

    The command guard learned this the hard way: its own corrective prose —
    "There is no `confiture benchmark`" — parsed as an invocation.
    """
    assert IMPORT.search("The docs used to say from confiture.wizard import X.") is None
    assert IMPORT.search("from confiture.core.migrator import Migrator") is not None


@pytest.mark.parametrize("site", SITES, ids=lambda s: f"{s[0]}::{s[1]}{'.' + s[2] if s[2] else ''}")
def test_every_documented_import_resolves(site):
    rel, module, symbol = site
    problem = _resolve(module, symbol)
    if problem is None:
        return
    reason = KNOWN_UNRESOLVABLE.get((rel, f"{module}.{symbol}" if symbol else module))
    assert reason is not None, (
        f"{rel} documents an import that does not work: {problem}. "
        f"Fix the document, or record it in KNOWN_UNRESOLVABLE with the reason."
    )


def test_no_allow_list_entry_is_stale():
    """A reason cannot outlive the thing it explains."""
    live = {
        (rel, f"{module}.{symbol}" if symbol else module)
        for rel, module, symbol in SITES
        if _resolve(module, symbol) is not None
    }
    stale = sorted(set(KNOWN_UNRESOLVABLE) - live)
    assert stale == [], f"allow-list entries that no longer match a broken import: {stale}"
