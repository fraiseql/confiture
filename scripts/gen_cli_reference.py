#!/usr/bin/env python3
"""Keep ``docs/reference/cli.md`` in step with the CLI the package registers (Phase 10, ARC-03).

Every leaf command gets one generated block — usage line, arguments table,
options table — between named markers, rendered from the live Typer app so it
cannot describe a flag that does not exist. The prose around each block is
written by hand and left alone.

    python scripts/gen_cli_reference.py --check   # exit 1 when a block is missing or stale
    python scripts/gen_cli_reference.py --write   # regenerate every block; add sections for
                                                  # new commands; drop sections for commands
                                                  # that no longer exist

``tests/unit/docs/test_doc_sync_cli.py`` runs the check.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

from typer.main import get_command

from confiture.cli.main import app

DOC = Path(__file__).resolve().parents[1] / "docs" / "reference" / "cli.md"
BEGIN = "<!-- BEGIN GENERATED: cli {name} -->"
END = "<!-- END GENERATED: cli {name} -->"
HEADING = re.compile(r"^(#{2,4}) `confiture ([a-z0-9 -]+)`[^\n]*$", re.M)
#: Hand-written sections that are not commands but are worth keeping.
KEEP_SECTIONS = {"build --dump"}
#: Hand sub-blocks the generated block replaces (a heading one level below the command's).
REPLACED_SUBBLOCKS = {"usage", "arguments", "options", "argument", "option"}


def command_tree() -> dict[str, Any]:
    """``{"migrate up": <Command>, ...}`` for every command and group, in registration order."""
    found: dict[str, Any] = {}

    def walk(cmd: Any, prefix: str) -> None:
        subs = getattr(cmd, "commands", None) or {}
        for name, sub in sorted(subs.items()):
            path = f"{prefix} {name}".strip()
            found[path] = sub
            walk(sub, path)

    walk(get_command(app), "")
    return found


def is_group(cmd: Any) -> bool:
    return bool(getattr(cmd, "commands", None))


def _cell(text: object) -> str:
    return " ".join(str(text).split()).replace("|", "\\|")


def _is_option(param: Any) -> bool:
    # typer vendors its own click (typer._click); never isinstance against the
    # standalone `click` package, which may be absent or a different module.
    return getattr(param, "param_type_name", "") == "option"


def _default(param: Any) -> str:
    if _is_option(param) and getattr(param, "is_flag", False) and not param.secondary_opts:
        return "on" if param.default else "off"
    value = param.default
    if value is None or value == () or value == []:
        return "-"
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, Path):
        return f"`{value.as_posix()}`"
    if isinstance(value, (list, tuple)):
        return ", ".join(f"`{v}`" for v in value)
    return f"`{value}`"


def _type(param: Any) -> str:
    if _is_option(param) and getattr(param, "is_flag", False):
        return "Flag"
    return param.type.name.replace("_", " ")


def render_block(path: str, cmd: Any) -> str:
    """The generated block for one leaf command."""
    ctx = cmd.context_class(cmd, info_name=f"confiture {path}")
    usage = cmd.get_usage(ctx).replace("Usage: ", "", 1).strip()
    lines = [BEGIN.format(name=f"confiture {path}"), "", "**Usage**", "", "```bash", usage, "```", ""]
    arguments = [p for p in cmd.params if getattr(p, "param_type_name", "") == "argument"]
    options = [
        p
        for p in cmd.params
        if _is_option(p) and not getattr(p, "hidden", False) and "--help" not in p.opts
    ]
    if arguments:
        lines += ["**Arguments**", "", "| Argument | Type | Required | Description |", "|---|---|---|---|"]
        for p in arguments:
            lines.append(
                f"| `{p.human_readable_name}` | {_type(p)} | {'yes' if p.required else 'no'} | "
                f"{_cell(getattr(p, 'help', '') or '')} |"
            )
        lines.append("")
    if options:
        lines += ["**Options**", "", "| Option | Short | Type | Default | Description |", "|---|---|---|---|---|"]
        for p in options:
            longs = [o for o in p.opts if o.startswith("--")]
            shorts = [o for o in p.opts if not o.startswith("--")]
            name = " / ".join(f"`{o}`" for o in [*longs, *p.secondary_opts])
            short = ", ".join(f"`{o}`" for o in shorts) or "-"
            lines.append(f"| {name} | {short} | {_type(p)} | {_default(p)} | {_cell(p.help or '')} |")
        lines.append("")
    lines.append(END.format(name=f"confiture {path}"))
    return "\n".join(lines)


def _section_spans(text: str) -> list[tuple[int, int, int, str]]:
    """``(start, end, level, name)`` per command heading; a section runs to the next heading of level <= its own."""
    matches = list(HEADING.finditer(text))
    spans = []
    for i, m in enumerate(matches):
        level = len(m.group(1))
        end = len(text)
        for later in matches[i + 1 :]:
            if len(later.group(1)) <= level:
                end = later.start()
                break
        spans.append((m.start(), end, level, m.group(2).strip()))
    return spans


def _strip_replaced_subblocks(section: str, level: int) -> str:
    """Drop hand ``Usage``/``Arguments``/``Options`` sub-blocks; the generated block carries them."""
    sub = "#" * (level + 1)
    pattern = re.compile(rf"^{sub} ([A-Za-z ]+)\n(.*?)(?=^#{{2,{level + 1}}} |\Z)", re.M | re.S)

    def keep(m: re.Match[str]) -> str:
        return "" if m.group(1).strip().lower() in REPLACED_SUBBLOCKS else m.group(0)

    return pattern.sub(keep, section)


def _with_block(section: str, level: int, path: str, cmd: Any) -> str:
    """The section with its generated block current (replaced in place, or inserted after the intro)."""
    block = render_block(path, cmd)
    begin, end = BEGIN.format(name=f"confiture {path}"), END.format(name=f"confiture {path}")
    if begin in section and end in section:
        head, rest = section.split(begin, 1)
        _, tail = rest.split(end, 1)
        return f"{head}{block}{tail}"
    section = _strip_replaced_subblocks(section, level)
    heading_end = section.index("\n") + 1
    body = section[heading_end:]
    # insert after the first paragraph of prose (or straight after the heading)
    m = re.match(r"\s*\n?((?:(?!\n\n)[^#].*\n?)+)\n", body)
    if m and not body.lstrip().startswith("#"):
        intro_end = heading_end + m.end()
        return f"{section[:intro_end]}\n{block}\n\n{section[intro_end:].lstrip(chr(10))}"
    return f"{section[:heading_end]}\n{block}\n\n{body.lstrip(chr(10))}"


def _new_section(path: str, cmd: Any, level: int) -> str:
    summary = (cmd.help or cmd.short_help or "").strip().split("\n\n")[0].strip() or f"`confiture {path}`."
    summary = " ".join(summary.split())
    return f"{'#' * level} `confiture {path}`\n\n{summary}\n\n{render_block(path, cmd)}\n\n"


def apply(text: str) -> tuple[str, list[str]]:
    """The document with every block current, new sections added and fiction removed."""
    tree = command_tree()
    log: list[str] = []
    # 1. drop sections for commands that do not exist
    for start, end, _level, name in reversed(_section_spans(text)):
        if name not in tree and name not in KEEP_SECTIONS:
            text = text[:start] + text[end:]
            log.append(f"removed section `confiture {name}` (no such command)")
    # 2. refresh or insert blocks in existing leaf sections
    spans = _section_spans(text)
    for start, end, level, name in reversed(spans):
        cmd = tree.get(name)
        if cmd is None or is_group(cmd):
            continue
        section = text[start:end]
        updated = _with_block(section, level, name, cmd)
        if updated != section:
            text = text[:start] + updated + text[end:]
            log.append(f"refreshed `confiture {name}`")
    # 3. add sections for commands without one
    documented = {name for *_, name in _section_spans(text)}
    for path, cmd in tree.items():
        if path in documented:
            continue
        parts = path.split(" ")
        if is_group(cmd):
            level = len(parts) + 1
            new = f"{'#' * level} `confiture {path}`\n\n{' '.join((cmd.help or '').strip().split()) or 'Command group.'}\n\n"
        else:
            level = len(parts) + 1
            new = _new_section(path, cmd, level)
        parent = " ".join(parts[:-1])
        if parent and parent in {n for *_, n in _section_spans(text)}:
            pstart, pend, *_ = next(s for s in _section_spans(text) if s[3] == parent)
            text = text[:pend].rstrip("\n") + "\n\n" + new + text[pend:]
        else:
            anchor = text.find("\n## Error Handling")
            if anchor == -1:
                text = text.rstrip("\n") + "\n\n" + new
            else:
                text = text[:anchor].rstrip("\n") + "\n\n" + new + text[anchor:]
        documented.add(path)
        log.append(f"added `confiture {path}`")
    return text, log


def check(text: str) -> list[str]:
    tree = command_tree()
    problems: list[str] = []
    for path, cmd in tree.items():
        if is_group(cmd):
            continue
        begin, end = BEGIN.format(name=f"confiture {path}"), END.format(name=f"confiture {path}")
        if begin not in text or end not in text:
            problems.append(f"`confiture {path}`: no generated block")
            continue
        current = text.split(begin, 1)[1].split(end, 1)[0]
        if f"{begin}{current}{end}" != render_block(path, cmd):
            problems.append(f"`confiture {path}`: generated block is stale")
    for *_, name in _section_spans(text):
        if name not in tree and name not in KEEP_SECTIONS:
            problems.append(f"`confiture {name}`: documented but no such command")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    text = DOC.read_text(encoding="utf-8")
    if args.check:
        problems = check(text)
        for p in problems:
            print(p)
        print("cli.md is in sync" if not problems else f"{len(problems)} problem(s)")
        return 1 if problems else 0
    new_text, log = apply(text)
    if new_text != text:
        DOC.write_text(new_text, encoding="utf-8")
    for line in log:
        print(line)
    print(f"{len(log)} change(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
