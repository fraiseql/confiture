#!/usr/bin/env python3
"""Keep ``docs/reference/configuration.md`` in step with the configuration models (Phase 10, ARC-03).

Renders, from the Pydantic models under ``confiture.config.environment``, one
table per model (field, type, default, description) and one complete YAML
skeleton with every field at its default, between named markers in the
reference. Descriptions come from the model class docstring's ``Attributes:``
section or the inline ``# comment`` on the field — the models are the one place
a field is explained.

    python scripts/gen_config_reference.py --check   # exit 1 when the block is stale
    python scripts/gen_config_reference.py --write   # regenerate the block
    python scripts/gen_config_reference.py --undocumented   # fields with no description

``tests/unit/docs/test_doc_config_fields.py`` runs the check.
"""

from __future__ import annotations

import argparse
import inspect
import re
import sys
import types
import typing
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel
from pydantic_core import PydanticUndefined

from confiture.config.environment import Environment

DOC = Path(__file__).resolve().parents[1] / "docs" / "reference" / "configuration.md"
BEGIN = "<!-- BEGIN GENERATED: config-fields -->"
END = "<!-- END GENERATED: config-fields -->"


def _nested_model(annotation: Any) -> type[BaseModel] | None:
    for candidate in (*getattr(annotation, "__args__", ()), annotation):
        inner = candidate
        for arg in getattr(candidate, "__args__", ()):
            if isinstance(arg, type) and issubclass(arg, BaseModel):
                inner = arg
        if isinstance(inner, type) and issubclass(inner, BaseModel):
            return inner
    return None


def _type_text(annotation: Any) -> str:
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin in (typing.Union, types.UnionType):
        return " \\| ".join(_type_text(a) for a in args)
    if origin is typing.Literal:
        return " \\| ".join(f"`{a}`" for a in args)
    if origin in (list, dict, tuple, set):
        inner = ", ".join(_type_text(a) for a in args) if args else ""
        return f"{origin.__name__}[{inner}]"
    if isinstance(annotation, type):
        if issubclass(annotation, BaseModel):
            return f"[{annotation.__name__}](#{annotation.__name__.lower()})"
        return annotation.__name__
    return str(annotation).replace("typing.", "")


def _descriptions(model: type[BaseModel]) -> dict[str, str]:
    """``Attributes:`` entries of the class docstring, then inline field comments."""
    found: dict[str, str] = {}
    doc = inspect.getdoc(model) or ""
    if "Attributes:" in doc:
        block = doc.split("Attributes:", 1)[1]
        current = None
        for line in block.splitlines():
            m = re.match(r"^\s{0,4}([a-z_][a-z0-9_]*):\s*(.*)$", line)
            if m and not line.startswith(" " * 8):
                current = m.group(1)
                found[current] = m.group(2).strip()
            elif current and line.strip() and line.startswith("    "):
                found[current] = (found[current] + " " + line.strip()).strip()
            elif not line.strip():
                current = None
    try:
        source = inspect.getsource(model)
    except OSError:
        source = ""
    for name in model.model_fields:
        if found.get(name):
            continue
        m = re.search(rf"^\s+{name}\s*:.*?#\s*(.+)$", source, re.M)
        if m:
            found[name] = m.group(1).strip()
    return found


def _default_text(field: Any) -> str:
    if field.default_factory is not None:
        produced = field.default_factory()
        if isinstance(produced, BaseModel):
            return "(nested)"
        return (
            f"`{produced!r}`"
            if produced not in ([], {}, None)
            else "`[]`"
            if produced == []
            else "`{}`"
            if produced == {}
            else "-"
        )
    if field.default is PydanticUndefined:
        return "**required**"
    if field.default is None:
        return "-"
    if isinstance(field.default, bool):
        return "`true`" if field.default else "`false`"
    if isinstance(field.default, list | tuple):
        return f"`{list(field.default)!r}`" if field.default else "`[]`"
    return f"`{field.default}`"


def _models(root: type[BaseModel]) -> list[type[BaseModel]]:
    ordered: list[type[BaseModel]] = []

    def visit(model: type[BaseModel]) -> None:
        if model in ordered:
            return
        ordered.append(model)
        for field in model.model_fields.values():
            nested = _nested_model(field.annotation)
            if nested is not None:
                visit(nested)

    visit(root)
    return ordered


def _scalar(value: Any) -> str:
    """One YAML scalar, quoted by PyYAML when it has to be (``**/*.sql`` would read as an alias)."""
    if isinstance(value, Path):
        value = value.as_posix()
    return (
        yaml.safe_dump(value, default_flow_style=True, width=10_000)
        .strip()
        .removesuffix("\n...")
        .strip()
    )


def _yaml_default(field: Any, model: type[BaseModel] | None, indent: int) -> list[str]:
    pad = "  " * indent
    if model is not None:
        return [*_yaml_model(model, indent)]
    if field.default_factory is not None:
        value = field.default_factory()
    elif field.default is PydanticUndefined:
        value = None
    else:
        value = field.default
    if isinstance(value, list | tuple):
        return [" []"] if not value else [""] + [f"{pad}  - {_scalar(v)}" for v in value]
    if isinstance(value, dict):
        return (
            [" {}"] if not value else [""] + [f"{pad}  {k}: {_scalar(v)}" for k, v in value.items()]
        )
    return [f" {_scalar(value)}"]


def _yaml_model(model: type[BaseModel], indent: int) -> list[str]:
    lines: list[str] = []
    pad = "  " * indent
    for name, field in model.model_fields.items():
        key = field.alias or name
        nested = _nested_model(field.annotation)
        origin = typing.get_origin(field.annotation)
        if nested is not None and origin in (list, tuple):
            lines.append(f"{pad}{key}:")
            body = _yaml_model(nested, indent + 2)
            if body:
                first, *rest = body
                lines.append(f"{pad}  - {first.strip()}")
                lines.extend(rest)
            continue
        if nested is not None and origin is dict:
            lines.append(f"{pad}{key}:")
            lines.append(f"{pad}  <name>:")
            lines.extend(_yaml_model(nested, indent + 2))
            continue
        if nested is not None:
            lines.append(f"{pad}{key}:")
            lines.extend(_yaml_model(nested, indent + 1))
            continue
        value_lines = _yaml_default(field, None, indent)
        lines.append(f"{pad}{key}:{value_lines[0]}")
        lines.extend(value_lines[1:])
    return lines


def render() -> str:
    lines = [
        BEGIN,
        "",
        "### Every field, from the models",
        "",
        "Generated from `confiture.config.environment`; the description is the model's own.",
        "",
    ]
    for model in _models(Environment):
        descriptions = _descriptions(model)
        lines += [
            f"#### `{model.__name__}`",
            "",
            "| Field | Type | Default | Description |",
            "|---|---|---|---|",
        ]
        for name, field in model.model_fields.items():
            key = field.alias or name
            desc = " ".join(descriptions.get(name, "").split()).replace("|", "\\|")
            lines.append(
                f"| `{key}` | {_type_text(field.annotation)} | {_default_text(field)} | {desc} |"
            )
        lines.append("")
    lines += [
        "### Complete skeleton (every field at its default)",
        "",
        "```yaml",
        *_yaml_model(Environment, 0),
        "```",
        "",
        END,
    ]
    return "\n".join(lines)


def undocumented() -> list[str]:
    missing: list[str] = []
    for model in _models(Environment):
        descriptions = _descriptions(model)
        missing.extend(
            f"{model.__name__}.{name}" for name in model.model_fields if not descriptions.get(name)
        )
    return missing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--undocumented", action="store_true")
    args = parser.parse_args(argv)
    if args.undocumented:
        for m in undocumented():
            print(m)
        print(f"{len(undocumented())} field(s) without a description")
        return 0
    text = DOC.read_text(encoding="utf-8")
    block = render()
    if args.check:
        if BEGIN not in text or END not in text:
            print("configuration.md has no generated block")
            return 1
        current = BEGIN + text.split(BEGIN, 1)[1].split(END, 1)[0] + END
        if current != block:
            print("configuration.md generated block is stale")
            return 1
        print("configuration.md is in sync")
        return 0
    if BEGIN in text and END in text:
        head, rest = text.split(BEGIN, 1)
        _, tail = rest.split(END, 1)
        text = f"{head}{block}{tail}"
    else:
        anchor = "\n## Environment Examples"
        text = (
            text.replace(anchor, f"\n## Field reference\n\n{block}\n{anchor}", 1)
            if anchor in text
            else text.rstrip("\n") + f"\n\n## Field reference\n\n{block}\n"
        )
    DOC.write_text(text, encoding="utf-8")
    print("configuration.md written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
