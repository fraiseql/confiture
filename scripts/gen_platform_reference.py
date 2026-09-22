#!/usr/bin/env python3
"""Keep ``docs/reference/platform-api.md`` in step with ``confiture.platform``.

Renders every name the seam exports — a function's signature, a dataclass's
fields, an enum's members, a union's variants — with its own docstring, between
named markers in the reference. The package is the one place any of it is
explained; ``tests/contract/test_platform_surface.py`` pins what is rendered.

    python scripts/gen_platform_reference.py --check   # exit 1 when the block is stale
    python scripts/gen_platform_reference.py --write   # regenerate the block

``tests/unit/docs/test_platform_reference.py`` runs the check.
"""

from __future__ import annotations

import argparse
import dataclasses
import enum
import inspect
import re
import sys
import types
import typing
from pathlib import Path
from typing import Any

from confiture import platform

DOC = Path(__file__).resolve().parents[1] / "docs" / "reference" / "platform-api.md"
BEGIN = "<!-- BEGIN GENERATED: platform-api -->"
END = "<!-- END GENERATED: platform-api -->"
WIDTH = 88

#: The reference's sections, in reading order; every exported name is in one.
SECTIONS: list[tuple[str, list[str]]] = [
    ("Reading a schema", ["parse_schema", "introspect", "diff", "SchemaSource", "Connection"]),
    (
        "The model",
        [
            "SchemaModel",
            "ObjectRef",
            "Table",
            "Column",
            "Constraint",
            "Index",
            "EnumType",
            "Sequence",
            "Routine",
            "View",
            "Trigger",
        ],
    ),
    ("Ordering", ["dependency_order", "DependencyCycle"]),
    (
        "What a writer may supply",
        [
            "writable_columns",
            "column_facts",
            "naming_hints",
            "ColumnFacts",
            "ColumnReference",
            "TableHints",
        ],
    ),
    (
        "Seeds",
        [
            "write_copy_seed",
            "write_insert_seed",
            "SeedFile",
            "apply_seeds",
            "SeedProfile",
            "ApplyResult",
            "validate_seeds",
            "PrepSeedReport",
            "PrepSeedViolation",
            "PrepSeedPattern",
            "ViolationSeverity",
        ],
    ),
    (
        "What changed",
        [
            "SchemaDiff",
            "BuildWarning",
            "SchemaChange",
            "tier_of",
            "RiskTier",
            *(variant.__name__ for variant in typing.get_args(platform.SchemaChange)),
            "DDLObject",
        ],
    ),
    (
        "Errors",
        ["ConfiturError", "SchemaError", "NotInModelError", "SeedError", "ConfigurationError"],
    ),
]

_ROLE = re.compile(r":(?:func|class|data|meth|attr|mod|exc):`~?([^`]+)`")
_SECTION = re.compile(r"^(Args|Arguments|Returns|Raises|Yields|Note|Example|Examples):\s*$")
_ITEM = re.compile(r"^(\*{0,2}[\w.]+(?: \([^)]*\))?):\s*(.*)$")


def _markdown(doc: str | None) -> list[str]:
    """A docstring as Markdown: roles as code, Google sections as bold heads and bullets."""
    if not doc:
        return []
    text = _ROLE.sub(lambda m: f"`{m.group(1).rsplit('.', 1)[-1]}`", inspect.cleandoc(doc))
    text = text.replace("``", "`")
    out: list[str] = []
    in_section = False
    for line in text.splitlines():
        head = _SECTION.match(line)
        if head:
            out += ["", f"**{head.group(1)}**", ""]
            in_section = True
            continue
        if in_section and line.startswith("    "):
            stripped = line.strip()
            item = _ITEM.match(stripped) if not line.startswith("        ") else None
            if item:
                out.append(f"- `{item.group(1)}`: {item.group(2)}".rstrip())
            elif out and out[-1].startswith("- "):
                out[-1] += f" {stripped}"
            else:
                out.append(stripped)
            continue
        if line.strip():
            in_section = False
        out.append(line)
    return out


def _parameter(param: inspect.Parameter) -> str:
    text = param.name
    if param.annotation is not inspect.Parameter.empty:
        text += f": {param.annotation}"
    if param.default is not inspect.Parameter.empty:
        text += f" = {param.default!r}"
    return text


def _signature(name: str, fn: Any, prefix: str = "def ") -> list[str]:
    sig = inspect.signature(fn)
    parts: list[str] = []
    seen_keyword = False
    for param in sig.parameters.values():
        if param.kind is inspect.Parameter.KEYWORD_ONLY and not seen_keyword:
            parts.append("*")
            seen_keyword = True
        parts.append(_parameter(param))
    returns = (
        "" if sig.return_annotation is inspect.Signature.empty else f" -> {sig.return_annotation}"
    )
    one_line = f"{prefix}{name}({', '.join(parts)}){returns}"
    if len(one_line) <= WIDTH:
        return ["```python", one_line, "```"]
    return ["```python", f"{prefix}{name}(", *(f"    {p}," for p in parts), f"){returns}", "```"]


def _fields(cls: type) -> list[str]:
    rows = ["| Field | Type | Default |", "|---|---|---|"]
    for field in dataclasses.fields(cls):
        if field.default is not dataclasses.MISSING:
            default = f"`{field.default!r}`"
        elif field.default_factory is not dataclasses.MISSING:
            default = "empty"
        else:
            default = "required"
        annotation = str(field.type).replace("|", "\\|")
        rows.append(f"| `{field.name}` | `{annotation}` | {default} |")
    return rows


def _methods(cls: type) -> list[str]:
    lines: list[str] = []
    for member_name, member in vars(cls).items():
        function = getattr(member, "__func__", member)
        if member_name.startswith("_") or not inspect.isfunction(function):
            continue
        lines += ["", f"#### `{cls.__name__}.{member_name}`", ""]
        lines += _signature(member_name, getattr(cls, member_name))
        lines += ["", *_markdown(function.__doc__)]
    return lines


def _type_name(tp: Any) -> str:
    args = typing.get_args(tp)
    if isinstance(tp, types.UnionType):
        return " | ".join(_type_name(arg) for arg in args)
    name = getattr(typing.get_origin(tp) or tp, "__name__", str(tp))
    return f"{name}[{', '.join(_type_name(arg) for arg in args)}]" if args else name


def _union(name: str, obj: Any) -> list[str]:
    members = [_type_name(arg) for arg in typing.get_args(obj)]
    one_line = f"{name} = {' | '.join(members)}"
    if len(one_line) <= WIDTH:
        return ["```python", one_line, "```"]
    return [
        "```python",
        f"{name} = (",
        f"    {members[0]}",
        *(f"    | {m}" for m in members[1:]),
        ")",
        "```",
    ]


def _entry(name: str) -> list[str]:
    obj = getattr(platform, name)
    lines = ["", f"### `{name}`", ""]
    if inspect.isfunction(obj):
        return [*lines, *_signature(name, obj), "", *_markdown(obj.__doc__)]
    if typing.get_args(obj):
        return [*lines, *_union(name, obj)]
    if isinstance(obj, type) and issubclass(obj, enum.Enum):
        members = ", ".join(f"`{member.value}`" for member in obj)
        return [*lines, *_markdown(obj.__doc__), "", f"Members: {members}."]
    bases = ", ".join(base.__name__ for base in obj.__bases__ if base is not object)
    lines += ["```python", f"class {name}({bases})" if bases else f"class {name}", "```", ""]
    lines += _markdown(obj.__doc__)
    if dataclasses.is_dataclass(obj):
        lines += ["", *_fields(obj)]
    return lines + _methods(obj)


def render() -> str:
    """The generated block, markers included."""
    listed = [name for _, names in SECTIONS for name in names]
    stray = sorted(set(platform.__all__) ^ set(listed))
    if stray or len(listed) != len(set(listed)):
        raise SystemExit(f"SECTIONS and confiture.platform.__all__ disagree: {stray}")
    lines = [BEGIN, "", "Generated from `confiture.platform`; each description is the code's own."]
    for title, names in SECTIONS:
        lines += ["", f"## {title}"]
        for name in names:
            lines += _entry(name)
    lines += ["", END]
    text = "\n".join(line.rstrip() for line in lines)
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    text = DOC.read_text(encoding="utf-8")
    block = render()
    if BEGIN not in text or END not in text:
        print("platform-api.md has no generated block")
        return 1
    head, rest = text.split(BEGIN, 1)
    current, tail = rest.split(END, 1)
    if args.check:
        if BEGIN + current + END != block:
            print("platform-api.md is stale: run scripts/gen_platform_reference.py --write")
            return 1
        print("platform-api.md is in sync")
        return 0
    DOC.write_text(f"{head}{block}{tail}", encoding="utf-8")
    print(f"wrote {DOC}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
