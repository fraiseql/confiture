"""A lint baseline: the findings a schema is allowed to have today (#219).

Adopting a rule on a schema that already trips it a hundred times is a flag
day nobody schedules. A baseline file records the *identity* of every
current finding — ``rule_id``, object kind and qualified name, plus the file
for file-scoped rules, never a line number — and a later run fails only on
identities the file does not know. When findings disappear the file is
rewritten without them (D12), so the ratchet only ever tightens;
``--write-baseline`` creates or resets it.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from confiture.core.linting.schema_linter import LintViolation
from confiture.exceptions import ConfigurationError

FORMAT_VERSION = 1
CONVENTIONAL_NAME = ".confiture-lint-baseline.json"
MALFORMED_CODE = "CONFIG_012"


#: The rules that read a *tree of files* rather than the one built schema, so the
#: same object name can legitimately be reported from several of them: a
#: duplicate definition is about the pair of files it is in, an ACL, ownership or
#: replica finding is about one migration, and a file-tree finding's object *is*
#: a path — ``tree_001:file:00001_create.sql`` would collapse every directory in
#: the tree onto one entry. Their identity carries ``@file``.
#:
#: Every other rule reads the build, where an object is defined once, and
#: identifies its finding by the object alone — moving a table from one schema
#: file to another must not retire a baseline entry and add a new one. That is
#: why this is an explicit set and not "whatever violations happen to carry a
#: ``file_path``": since 1.4.0 nearly all of them do. ``func_001`` is deliberately
#: outside it although it walks a tree: it reports one finding per duplicated
#: signature, and the file it names is whichever copy sorted first, so ``@file``
#: would churn the identity when the *other* copy moved.
FILE_SCOPED_RULES = frozenset(
    {
        "build_001",
        "build_002",
        "acl_001",
        "tenant_001",
        "replica_001",
        "own_001",
        "own_002",
        "tree_001",
        "tree_002",
        "tree_003",
        "tree_004",
    }
)


def identity(violation: LintViolation) -> str:
    """``rule:kind:name`` — with ``@file`` when the rule is file-scoped. No line numbers."""
    base = f"{violation.rule_id}:{violation.object_type}:{violation.object_name}"
    if violation.rule_id in FILE_SCOPED_RULES and violation.file_path:
        return f"{base}@{violation.file_path}"
    return base


@dataclass
class BaselineDiff:
    """What a run looks like against a baseline."""

    new: list[LintViolation] = field(default_factory=list)
    fixed: list[str] = field(default_factory=list)
    known: int = 0

    def summary(self) -> dict[str, object]:
        return {
            "new": sorted(identity(v) for v in self.new),
            "fixed": self.fixed,
            "known": self.known,
        }


@dataclass
class Baseline:
    identities: frozenset[str]

    @classmethod
    def from_violations(cls, violations: Iterable[LintViolation]) -> Baseline:
        return cls(frozenset(identity(v) for v in violations))

    @classmethod
    def load(cls, path: Path) -> Baseline:
        """Read a baseline file; a missing or malformed file is a configuration error."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise ConfigurationError(
                f"Lint baseline file not found: {path}",
                error_code=MALFORMED_CODE,
                resolution_hint="Create it with `confiture lint --baseline <file> --write-baseline`.",
            ) from None
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ConfigurationError(
                f"Lint baseline file is not valid JSON: {path} ({exc})",
                error_code=MALFORMED_CODE,
                resolution_hint="Regenerate it with `confiture lint --baseline <file> --write-baseline`.",
            ) from None
        rules = data.get("rules") if isinstance(data, dict) else None
        if data.get("version") != FORMAT_VERSION or not isinstance(rules, dict):
            raise ConfigurationError(
                f"Lint baseline file has an unknown shape: {path}",
                error_code=MALFORMED_CODE,
                resolution_hint=(
                    f'Expected {{"version": {FORMAT_VERSION}, "rules": {{...}}}}; regenerate it '
                    "with `confiture lint --baseline <file> --write-baseline`."
                ),
            )
        identities: set[str] = set()
        for rule, ids in rules.items():
            if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
                raise ConfigurationError(
                    f"Lint baseline file has a malformed entry for {rule!r}: {path}",
                    error_code=MALFORMED_CODE,
                    resolution_hint="Regenerate it with `confiture lint --baseline <file> --write-baseline`.",
                )
            identities.update(ids)
        return cls(frozenset(identities))

    def to_dict(self) -> dict[str, object]:
        rules: dict[str, list[str]] = {}
        for ident in sorted(self.identities):
            rules.setdefault(ident.split(":", 1)[0], []).append(ident)
        return {"version": FORMAT_VERSION, "rules": dict(sorted(rules.items()))}

    def write(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")

    def diff(self, violations: Iterable[LintViolation]) -> BaselineDiff:
        """New findings (not in the file), fixed identities (in the file, gone), known count."""
        current = list(violations)
        seen = {identity(v) for v in current}
        return BaselineDiff(
            new=[v for v in current if identity(v) not in self.identities],
            fixed=sorted(self.identities - seen),
            known=len(self.identities & seen),
        )

    def without(self, identities: Iterable[str]) -> Baseline:
        return Baseline(self.identities - frozenset(identities))
