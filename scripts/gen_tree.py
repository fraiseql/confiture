#!/usr/bin/env python3
"""Render the project tree in CLAUDE.md from the repository itself.

The block between ``<!-- BEGIN GENERATED: tree -->`` and ``<!-- END GENERATED: tree -->``
is what this script prints: the ``python/confiture`` package two levels deep (a module's
comment is the first line of its docstring), the top-level directories that matter to a
contributor, the workflows, and the root files. ``--check`` exits 1 when CLAUDE.md is
stale; ``--write`` refreshes the block in place.

Usage:
    uv run python scripts/gen_tree.py            # print the tree
    uv run python scripts/gen_tree.py --check    # exit 1 if CLAUDE.md is stale
    uv run python scripts/gen_tree.py --write    # refresh CLAUDE.md
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

BEGIN = "<!-- BEGIN GENERATED: tree -->"
END = "<!-- END GENERATED: tree -->"
PACKAGE = Path("python/confiture")
COMMENT_COLUMN = 34
COMMENT_WIDTH = 72
SKIP_DIRS = frozenset({"__pycache__", ".venv", "node_modules", "htmlcov", "target", "site"})

# Directories rendered below the package, with a one-line note each. A directory that
# disappears is dropped from the tree by the generator; a note for a missing directory
# is an error, so the notes cannot outlive what they describe.
TOP_LEVEL: dict[str, str] = {
    "tests": "unit (no database), integration, e2e, contract, performance",
    "db": "the repo's own schema, migrations and snapshots",
    "docs": "the mkdocs site: guides, reference, api, features",
    "examples": "runnable example projects (examples.yml runs them in CI)",
    "scripts": "generators (--check in CI) and developer helpers",
    "src": "the confiture._core extension (file hashing)",
    "ci": "local Dagger pipeline mirroring quality-gate.yml",
}
ROOT_FILES = (
    "pyproject.toml",
    "uv.lock",
    "Cargo.toml",
    "Cargo.lock",
    "mkdocs.yml",
    "docker-compose.yml",
    "ARCHITECTURE.md",
    "PRD.md",
    "CLAUDE.md",
    "CHANGELOG.md",
    "README.md",
)


def _docstring_line(path: Path) -> str:
    try:
        doc = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8")))
    except (SyntaxError, UnicodeDecodeError):
        return ""
    if not doc:
        return ""
    first = doc.strip().splitlines()[0].strip().rstrip(".")
    if len(first) > COMMENT_WIDTH:
        first = first[: COMMENT_WIDTH - 1].rstrip() + "…"
    return first


def _count_modules(directory: Path) -> int:
    return sum(
        1
        for p in directory.rglob("*.py")
        if not any(part in SKIP_DIRS for part in p.relative_to(directory).parts)
    )


def _line(prefix: str, name: str, comment: str) -> str:
    entry = f"{prefix}{name}"
    if not comment:
        return entry
    pad = max(COMMENT_COLUMN - len(entry), 1)
    return f"{entry}{' ' * pad}# {comment}"


def _children(directory: Path) -> tuple[list[Path], list[Path]]:
    dirs = sorted(p for p in directory.iterdir() if p.is_dir() and p.name not in SKIP_DIRS)
    files = sorted(p for p in directory.iterdir() if p.is_file() and p.suffix == ".py")
    return dirs, files


def _render_package(root: Path, out: list[str], paths: list[str]) -> None:
    package = root / PACKAGE
    out.append(_line("├── ", f"{PACKAGE.as_posix()}/", ""))
    subpackages, modules = _children(package)
    entries: list[tuple[str, Path, bool]] = [(m.name, m, False) for m in modules]
    entries += [(f"{d.name}/", d, True) for d in subpackages]
    for index, (name, path, is_dir) in enumerate(entries):
        last = index == len(entries) - 1
        branch = "└── " if last else "├── "
        paths.append(path.relative_to(root).as_posix())
        if not is_dir:
            out.append(_line(f"│   {branch}", name, _docstring_line(path)))
            continue
        init = path / "__init__.py"
        out.append(_line(f"│   {branch}", name, _docstring_line(init) if init.exists() else ""))
        inner_prefix = "│       " if last else "│   │   "
        inner_dirs, inner_files = _children(path)
        inner: list[tuple[str, Path, bool]] = [(f.name, f, False) for f in inner_files]
        inner += [(f"{d.name}/", d, True) for d in inner_dirs]
        for j, (iname, ipath, idir) in enumerate(inner):
            ibranch = "└── " if j == len(inner) - 1 else "├── "
            paths.append(ipath.relative_to(root).as_posix())
            if idir:
                count = _count_modules(ipath)
                iinit = ipath / "__init__.py"
                note = _docstring_line(iinit) if iinit.exists() else ""
                suffix = f"{count} modules" if count != 1 else "1 module"
                comment = f"{note} ({suffix})" if note else f"({suffix})"
                out.append(_line(f"{inner_prefix}{ibranch}", iname, comment))
            else:
                out.append(_line(f"{inner_prefix}{ibranch}", iname, _docstring_line(ipath)))
    out.append("│")


def _render_top_level(root: Path, out: list[str], paths: list[str]) -> None:
    for name, note in TOP_LEVEL.items():
        directory = root / name
        if not directory.exists():
            raise SystemExit(f"gen_tree: TOP_LEVEL names {name}/, which does not exist")
        paths.append(name)
        out.append(_line("├── ", f"{name}/", note))
        subdirs = [p for p in sorted(directory.iterdir()) if p.is_dir() and p.name not in SKIP_DIRS]
        if name in {"examples", "scripts", "src"}:
            continue
        for k, sub in enumerate(subdirs):
            branch = "└── " if k == len(subdirs) - 1 else "├── "
            paths.append(sub.relative_to(root).as_posix())
            out.append(_line(f"│   {branch}", f"{sub.name}/", ""))
        out.append("│")
    workflows = sorted((root / ".github" / "workflows").glob("*.yml"))
    out.append(_line("├── ", ".github/workflows/", ""))
    for k, wf in enumerate(workflows):
        branch = "└── " if k == len(workflows) - 1 else "├── "
        paths.append(wf.relative_to(root).as_posix())
        out.append(_line(f"│   {branch}", wf.name, ""))
    out.append("│")


def _render_root_files(root: Path, out: list[str], paths: list[str]) -> None:
    present = [f for f in ROOT_FILES if (root / f).exists()]
    for k, name in enumerate(present):
        branch = "└── " if k == len(present) - 1 else "├── "
        paths.append(name)
        out.append(_line(branch, name, ""))


def _render(root: Path) -> tuple[str, list[str]]:
    out: list[str] = ["```", "confiture/"]
    paths: list[str] = []
    _render_package(root, out, paths)
    _render_top_level(root, out, paths)
    _render_root_files(root, out, paths)
    out.append("```")
    return "\n".join(out) + "\n", paths


def render_tree(root: Path) -> str:
    """The fenced tree block, exactly as CLAUDE.md must carry it."""
    return _render(root)[0]


def listed_paths(root: Path) -> list[str]:
    """Every repository path the rendered tree names (relative to ``root``)."""
    return _render(root)[1]


def _split(text: str) -> tuple[str, str, str]:
    start = text.index(BEGIN) + len(BEGIN)
    end = text.index(END)
    return text[: start + 1], text[start + 1 : end], text[end:]


def main(argv: list[str]) -> int:
    root = Path(__file__).resolve().parents[1]
    claude_md = root / "CLAUDE.md"
    rendered = render_tree(root)
    if "--check" not in argv and "--write" not in argv:
        sys.stdout.write(rendered)
        return 0
    text = claude_md.read_text(encoding="utf-8")
    if BEGIN not in text or END not in text:
        print("CLAUDE.md has no generated tree markers", file=sys.stderr)
        return 1
    head, current, tail = _split(text)
    if "--write" in argv:
        claude_md.write_text(head + rendered + tail, encoding="utf-8")
        print("CLAUDE.md tree written")
        return 0
    if current == rendered:
        print("CLAUDE.md tree is in sync")
        return 0
    print("CLAUDE.md tree is stale; run scripts/gen_tree.py --write", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
