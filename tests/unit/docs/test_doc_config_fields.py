"""`docs/reference/configuration.md` documents exactly the fields on the models.

Every key in the reference's YAML blocks must be a field the `Environment`
model (or one of its nested models) actually reads, and every such field must
appear in at least one YAML block — so a deleted field cannot linger in the
docs and a
new field cannot ship undocumented.
"""

from __future__ import annotations

import re
import typing

import yaml
from doc_snippets import read_doc
from pydantic import BaseModel

from confiture.config.environment import Environment

CONFIG_DOC = "docs/reference/configuration.md"
_YAML_BLOCK = re.compile(r"```ya?ml\n(.*?)```", re.S)


DICT_FIELDS: set[str] = set()


def _model_paths(model: type[BaseModel], prefix: str = "") -> set[str]:
    paths: set[str] = set()
    for name, field in model.model_fields.items():
        key = field.alias or name
        path = f"{prefix}{key}"
        paths.add(path)
        if typing.get_origin(field.annotation) is dict:
            DICT_FIELDS.add(path)  # the next YAML segment is an arbitrary key, not a field
        for candidate in (*getattr(field.annotation, "__args__", ()), field.annotation):
            inner = candidate
            for arg in getattr(candidate, "__args__", ()):  # list[Model] / dict[str, Model]
                if isinstance(arg, type) and issubclass(arg, BaseModel):
                    inner = arg
            if isinstance(inner, type) and issubclass(inner, BaseModel):
                paths |= _model_paths(inner, f"{path}.")
    return paths


MODEL_PATHS = _model_paths(Environment)


def _yaml_paths(text: str) -> dict[str, list[int]]:
    """Dotted key paths in every YAML block, mapped to the block numbers they appear in."""
    found: dict[str, list[int]] = {}

    def walk(node: object, prefix: str, block: int, keys_are_names: bool = False) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if keys_are_names:  # a profile / generator / rule name under a dict field
                    walk(value, prefix, block)
                    continue
                path = f"{prefix}{key}"
                found.setdefault(path, []).append(block)
                walk(value, f"{path}.", block, keys_are_names=path in DICT_FIELDS)
        elif isinstance(node, list):
            for item in node:
                walk(item, prefix, block)

    top_level = {p for p in MODEL_PATHS if "." not in p}
    for number, match in enumerate(_YAML_BLOCK.finditer(text), 1):
        try:
            data = yaml.safe_load(match.group(1))
        except yaml.YAMLError:
            continue
        # a block is configuration when it sets at least one top-level field;
        # CI snippets and other YAML in the reference are left alone
        if not isinstance(data, dict) or not (set(data) & top_level):
            continue
        walk(data, "", number)
    return found


def test_the_generated_field_reference_is_current() -> None:
    """`scripts/gen_config_reference.py --check`: tables and skeleton rendered from the models."""
    import importlib.util
    from pathlib import Path

    script = Path(__file__).resolve().parents[3] / "scripts" / "gen_config_reference.py"
    spec = importlib.util.spec_from_file_location("gen_config_reference", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    text = read_doc(CONFIG_DOC)
    assert module.BEGIN in text and module.END in text, (
        "configuration.md has no generated field reference"
    )
    current = module.BEGIN + text.split(module.BEGIN, 1)[1].split(module.END, 1)[0] + module.END
    assert current == module.render(), (
        "configuration.md field reference is stale; run scripts/gen_config_reference.py --write"
    )
    assert module.undocumented() == [], (
        f"model fields without a description: {module.undocumented()}"
    )


def test_every_documented_key_is_a_model_field() -> None:
    documented = _yaml_paths(read_doc(CONFIG_DOC))
    fiction = sorted(
        f"{path} (yaml block {blocks[0]})"
        for path, blocks in documented.items()
        if path not in MODEL_PATHS
    )
    assert fiction == [], "configuration.md documents keys no model reads:\n  " + "\n  ".join(
        fiction
    )


def test_every_model_field_is_documented() -> None:
    documented = set(_yaml_paths(read_doc(CONFIG_DOC)))
    missing = sorted(MODEL_PATHS - documented)
    assert missing == [], (
        "model fields missing from configuration.md's YAML blocks:\n  " + "\n  ".join(missing)
    )
