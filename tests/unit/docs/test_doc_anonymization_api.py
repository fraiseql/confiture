"""Executable guard: the anonymization API doc describes the real framework.

``docs/api/anonymization.md`` historically taught a **fictional** API — a
non-existent ``confiture.anonymization`` module, a ``@register_strategy('email')``
decorator over plain *functions*, and an ``AnonymizationContext`` with
``row_context``/``field_name`` arguments. The real API is class-based: subclass
``AnonymizationStrategy``, register the class with ``StrategyRegistry`` (or the
``@register_strategy`` *class* decorator), and drive rules from an
``AnonymizationProfile``.

This guard pins reality: every ``confiture`` import in the doc resolves, the
documented symbols are real, the profile-YAML example validates against the
Pydantic model, and the old fictional API can never reappear in this doc.
"""

from __future__ import annotations

import yaml
from doc_snippets import assert_doc_imports_resolve, fenced_after_anchor, read_doc

from confiture import (
    AnonymizationProfile,
    AnonymizationStrategy,
    StrategyConfig,
    StrategyRegistry,
    register_strategy,
)

DOC = "docs/api/anonymization.md"

# The fictional API the rewrite removed.
FORBIDDEN = [
    "confiture.anonymization import",  # real module is confiture / confiture.core.anonymization
    "AnonymizationContext",  # fictional context object
    "row_context",  # fictional function-signature argument
    "field_name",  # fictional function-signature argument
]


def test_every_confiture_import_resolves() -> None:
    """Each `from confiture… import X` in a python fence imports a real symbol."""
    checked = assert_doc_imports_resolve(DOC)
    assert checked, f"expected at least one confiture import in {DOC}"


def test_documented_symbols_are_real() -> None:
    """The classes/functions the doc teaches exist with the documented shape."""
    assert hasattr(AnonymizationStrategy, "anonymize")
    assert hasattr(AnonymizationStrategy, "validate")
    assert callable(register_strategy)
    assert hasattr(StrategyRegistry, "register") and hasattr(StrategyRegistry, "get")
    assert hasattr(StrategyConfig, "__dataclass_fields__")
    # The four whitelisted built-ins the doc's table marks must be registered.
    for name in ("email", "phone", "hash", "redact"):
        assert StrategyRegistry.is_registered(name), name


def test_no_fictional_api() -> None:
    """The fictional decorator-over-function / context API never reappears."""
    text = read_doc(DOC)
    leaked = [tok for tok in FORBIDDEN if tok in text]
    assert not leaked, f"fictional anonymization API present in {DOC}: {leaked}"


def test_profile_yaml_example_validates() -> None:
    """The documented profile YAML loads + validates against the real model."""
    block = fenced_after_anchor(read_doc(DOC), "anonymization-profile-yaml")
    profile = AnonymizationProfile.from_dict(yaml.safe_load(block))
    assert profile.name == "production"
    assert "users" in profile.tables
    # Every strategy the profile names is a whitelisted, registered type.
    for definition in profile.strategies.values():
        assert StrategyRegistry.is_registered(definition.type), definition.type
