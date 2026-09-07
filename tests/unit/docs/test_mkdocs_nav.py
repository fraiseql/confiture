"""`mkdocs.yml` navigates every page that exists and no page that does not.

The nav listed ten pages that were never written or have since moved
(`guides/medium-1-build-from-ddl.md`, `LICENSE.md`, …) and left ninety real
pages unreachable. Every local nav entry must exist under `docs/`, and every
`docs/**/*.md` must be in the nav or in the explicit exclusion list below —
so a page cannot be orphaned or invented without this failing.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
MKDOCS = REPO_ROOT / "mkdocs.yml"
DOCS = REPO_ROOT / "docs"

#: Pages deliberately kept out of the navigation, with the reason.
NAV_EXCLUDE: dict[str, str] = {}


class _Loader(yaml.SafeLoader):
    """mkdocs.yml carries `!!python/name:` tags for pymdownx; they are irrelevant here."""


_Loader.add_multi_constructor("tag:yaml.org,2002:python/", lambda loader, suffix, node: None)
_Loader.add_multi_constructor("!", lambda loader, suffix, node: None)


def _nav_pages(nav: object) -> list[str]:
    pages: list[str] = []
    if isinstance(nav, str):
        if re.match(r"^[\w./-]+\.md$", nav):
            pages.append(nav)
    elif isinstance(nav, dict):
        for value in nav.values():
            pages.extend(_nav_pages(value))
    elif isinstance(nav, list):
        for item in nav:
            pages.extend(_nav_pages(item))
    return pages


def _nav() -> list[str]:
    config = yaml.load(MKDOCS.read_text(encoding="utf-8"), Loader=_Loader)
    return _nav_pages(config.get("nav", []))


def _docs() -> set[str]:
    return {p.relative_to(DOCS).as_posix() for p in DOCS.rglob("*.md")}


def test_the_nav_is_generated_from_the_tree() -> None:
    """`scripts/gen_mkdocs_nav.py --check`: the nav block equals the generator's rendering."""
    import importlib.util

    script = REPO_ROOT / "scripts" / "gen_mkdocs_nav.py"
    spec = importlib.util.spec_from_file_location("gen_mkdocs_nav", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    _head, current, _tail = module._split(MKDOCS.read_text(encoding="utf-8"))
    assert current.rstrip("\n") == module.render_nav().rstrip("\n"), (
        "mkdocs.yml nav is stale; run scripts/gen_mkdocs_nav.py --write"
    )


def test_every_nav_entry_exists() -> None:
    missing = sorted(page for page in _nav() if page not in _docs())
    assert missing == [], "mkdocs.yml nav names pages that do not exist:\n  " + "\n  ".join(missing)


def test_every_page_is_navigable_or_explicitly_excluded() -> None:
    orphans = sorted(_docs() - set(_nav()) - set(NAV_EXCLUDE))
    assert orphans == [], (
        f"{len(orphans)} page(s) are neither in the nav nor in NAV_EXCLUDE:\n  "
        + "\n  ".join(orphans)
    )


def test_the_exclusion_list_is_current() -> None:
    stale = sorted(page for page in NAV_EXCLUDE if page not in _docs() or page in _nav())
    assert stale == [], f"NAV_EXCLUDE entries that no longer apply: {stale}"
