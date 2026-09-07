#!/usr/bin/env python3
"""Keep the ``nav:`` of ``mkdocs.yml`` equal to the docs tree (Phase 10, ARC-03).

Every page under ``docs/`` is listed once, titled by its first ``# `` heading,
in a fixed section order; nothing is listed that does not exist. The rest of
``mkdocs.yml`` (theme, plugins, extensions) is hand-written and left alone.

    python scripts/gen_mkdocs_nav.py --check   # exit 1 when the nav block is stale
    python scripts/gen_mkdocs_nav.py --write   # rewrite the nav block

``tests/unit/docs/test_mkdocs_nav.py`` runs the check.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "docs"
MKDOCS = REPO / "mkdocs.yml"

#: (section title, directory under docs/, pages pinned first in order)
SECTIONS: list[tuple[str, str, list[str]]] = [
    (
        "Getting Started",
        ".",
        ["index.md", "getting-started.md", "getting-started-by-role.md", "quickstart.md"],
    ),
    (
        "Guides",
        "guides",
        [
            "01-build-from-ddl.md",
            "02-incremental-migrations.md",
            "03-production-sync.md",
            "04-schema-to-schema.md",
        ],
    ),
    ("Reference", "reference", ["cli.md", "configuration.md"]),
    ("API", "api", ["index.md"]),
    ("Features", "features", ["overview.md"]),
    ("Architecture", "architecture", []),
    ("Operations", "operations", []),
    ("Performance", "performance", []),
    ("Security", "security", ["security-model.md"]),
    ("Research", "research", ["index.md"]),
    ("Release Notes", "release-notes", ["index.md"]),
]

EXAMPLES = [
    ("Basic Migration", "01-basic-migration"),
    ("FraiseQL Integration", "02-fraiseql-integration"),
    ("Zero-Downtime", "03-zero-downtime-migration"),
    ("Production Sync", "04-production-sync-anonymization"),
    ("Multi-Environment", "05-multi-environment-workflow"),
]


def _title(page: Path) -> str:
    text = page.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"^# (.+)$", text, re.M)
    title = m.group(1).strip() if m else page.stem.replace("-", " ").title()
    title = re.sub(r"[`*_]", "", title)
    return title


def _quote(title: str) -> str:
    return "'" + title.replace("'", "''") + "'"


def render_nav() -> str:
    lines = ["nav:"]
    for section, directory, pinned in SECTIONS:
        folder = DOCS / directory
        if not folder.is_dir():
            continue
        pages = sorted(folder.glob("*.md"))
        ordered = [folder / name for name in pinned if (folder / name).exists()]
        ordered += [p for p in pages if p not in ordered]
        if not ordered:
            continue
        lines.append(f"  - {_quote(section)}:")
        for page in ordered:
            rel = page.relative_to(DOCS).as_posix()
            title = "Home" if rel == "index.md" else _title(page)
            lines.append(f"      - {_quote(title)}: {rel}")
    lines.append("  - 'Examples':")
    for title, folder in EXAMPLES:
        lines.append(
            f"      - {_quote(title)}: 'https://github.com/fraiseql/confiture/tree/main/examples/{folder}'"
        )
    return "\n".join(lines) + "\n"


def _split(text: str) -> tuple[str, str, str]:
    m = re.search(r"^nav:\n(?:[ \t].*\n|\n)*", text, re.M)
    if not m:
        raise SystemExit("mkdocs.yml has no nav: block")
    return text[: m.start()], m.group(0), text[m.end() :]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    text = MKDOCS.read_text(encoding="utf-8")
    head, current, tail = _split(text)
    wanted = render_nav() + ("\n" if not tail.startswith("\n") else "")
    if args.check:
        if current.rstrip("\n") != wanted.rstrip("\n"):
            print("mkdocs.yml nav is stale; run scripts/gen_mkdocs_nav.py --write")
            return 1
        print("mkdocs.yml nav is in sync")
        return 0
    MKDOCS.write_text(head + wanted + tail, encoding="utf-8")
    print("mkdocs.yml nav written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
