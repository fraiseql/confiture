"""Import-check validation for Python migration modules.

Validates that pending Python migration files can be imported, contain
well-formed Migration subclasses, and (at Level 3) don't call nonexistent
methods on ``self``.
"""

from __future__ import annotations

import ast
import inspect
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ImportCheckViolation:
    """A single import-check failure."""

    file_path: str
    level: int
    rule: str
    message: str
    severity: str = "error"  # "error" or "warning"

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "level": self.level,
            "rule": self.rule,
            "message": self.message,
            "severity": self.severity,
        }


@dataclass
class ImportCheckResult:
    """Result of import-checking migration files."""

    checked: int = 0
    passed: int = 0
    failed: int = 0
    violations: list[ImportCheckViolation] = field(default_factory=list)
    skipped_sql: int = 0

    @property
    def success(self) -> bool:
        return self.failed == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked": self.checked,
            "passed": self.passed,
            "failed": self.failed,
            "skipped_sql": self.skipped_sql,
            "success": self.success,
            "violations": [v.to_dict() for v in self.violations],
        }


class ImportChecker:
    """Validates Python migration modules can be imported and are well-formed.

    Runs two levels of checks:

    - **Level 1**: Import the module and extract the Migration subclass.
      Catches syntax errors, missing imports, and missing Migration class.
    - **Level 2**: Verify the class has ``version``, ``name``, ``up()``,
      ``down()`` with correct types. Catches incomplete migrations.

    Args:
        migrations_dir: Directory containing migration files.
    """

    def __init__(self, migrations_dir: Path) -> None:
        self.migrations_dir = migrations_dir

    def check(self) -> ImportCheckResult:
        """Run import checks on all Python migration files.

        Returns:
            Structured result with per-file pass/fail and violations.
        """
        result = ImportCheckResult()

        py_files = self._discover_py_files()
        result.skipped_sql = self._count_sql_migrations()

        for py_file in py_files:
            result.checked += 1
            violations = self._check_file(py_file)
            has_errors = any(v.severity == "error" for v in violations)
            if has_errors:
                result.failed += 1
            else:
                result.passed += 1
            result.violations.extend(violations)

        return result

    def _discover_py_files(self) -> list[Path]:
        """Find Python migration files, excluding __init__.py and _prefixed."""
        files = sorted(self.migrations_dir.glob("*.py"))
        return [f for f in files if not f.name.startswith("__") and not f.name.startswith("_")]

    def _count_sql_migrations(self) -> int:
        """Count .up.sql migration files (skipped by import checker)."""
        return len(list(self.migrations_dir.glob("*.up.sql")))

    def _check_file(self, py_file: Path) -> list[ImportCheckViolation]:
        """Run L1 + L2 checks on a single file."""
        violations: list[ImportCheckViolation] = []
        file_str = str(py_file)

        # Level 1: import module
        module = self._check_level_1_import(py_file, file_str, violations)
        if module is None:
            return violations

        # Level 1: extract class
        cls = self._check_level_1_class(module, file_str, violations)
        if cls is None:
            return violations

        # Level 2: attribute validation
        self._check_level_2(cls, file_str, violations)

        # Level 3 only if L1+L2 passed (ignore warnings for gating)
        if not any(v.severity == "error" for v in violations):
            self._check_level_3(py_file, file_str, violations)
            self._check_execute_file_refs(py_file, file_str, violations)

        return violations

    def _check_level_1_import(
        self,
        py_file: Path,
        file_str: str,
        violations: list[ImportCheckViolation],
    ) -> Any:
        """Try to import the module. Returns module or None on failure."""
        from confiture.core.connection import load_migration_module
        from confiture.exceptions import MigrationError

        try:
            return load_migration_module(py_file)
        except MigrationError as e:
            violations.append(
                ImportCheckViolation(
                    file_path=file_str,
                    level=1,
                    rule="IMP001",
                    message=f"Failed to import: {e}",
                )
            )
            return None

    def _check_level_1_class(
        self,
        module: Any,
        file_str: str,
        violations: list[ImportCheckViolation],
    ) -> type | None:
        """Extract Migration subclass from module. Returns class or None."""
        from confiture.core.connection import get_migration_class
        from confiture.exceptions import MigrationError

        try:
            return get_migration_class(module)
        except MigrationError:
            violations.append(
                ImportCheckViolation(
                    file_path=file_str,
                    level=1,
                    rule="IMP002",
                    message="No Migration subclass found in module",
                )
            )
            return None

    def _check_level_2(
        self,
        cls: type,
        file_str: str,
        violations: list[ImportCheckViolation],
    ) -> None:
        """Validate class attributes: version, name, up(), down()."""
        # IMP003: version attribute
        if not hasattr(cls, "version") or cls.version is None:
            violations.append(
                ImportCheckViolation(
                    file_path=file_str,
                    level=2,
                    rule="IMP003",
                    message=f"{cls.__name__} missing 'version' class attribute",
                )
            )
        # IMP005: version type / empty
        elif not isinstance(cls.version, str) or not cls.version.strip():
            violations.append(
                ImportCheckViolation(
                    file_path=file_str,
                    level=2,
                    rule="IMP005",
                    message=f"{cls.__name__}.version must be a non-empty string, got {cls.version!r}",
                )
            )

        # IMP004: name attribute
        if not hasattr(cls, "name") or cls.name is None:
            violations.append(
                ImportCheckViolation(
                    file_path=file_str,
                    level=2,
                    rule="IMP004",
                    message=f"{cls.__name__} missing 'name' class attribute",
                )
            )
        # IMP005: name type / empty
        elif not isinstance(cls.name, str) or not cls.name.strip():
            violations.append(
                ImportCheckViolation(
                    file_path=file_str,
                    level=2,
                    rule="IMP005",
                    message=f"{cls.__name__}.name must be a non-empty string, got {cls.name!r}",
                )
            )

        # IMP006: up() must be concrete (not abstract)
        if _is_abstract_method(cls, "up"):
            violations.append(
                ImportCheckViolation(
                    file_path=file_str,
                    level=2,
                    rule="IMP006",
                    message=f"{cls.__name__} does not implement up()",
                )
            )

        # IMP007: down() must be concrete (not abstract)
        if _is_abstract_method(cls, "down"):
            violations.append(
                ImportCheckViolation(
                    file_path=file_str,
                    level=2,
                    rule="IMP007",
                    message=f"{cls.__name__} does not implement down()",
                )
            )

    def _check_level_3(
        self,
        py_file: Path,
        file_str: str,
        violations: list[ImportCheckViolation],
    ) -> None:
        """AST-based static analysis of up()/down() for invalid self.* access."""
        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(py_file))
        except SyntaxError:
            return  # Already caught by L1

        allowed = _build_migration_whitelist()

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue

            # Collect methods defined on this class (user helpers)
            class_methods = {
                item.name
                for item in ast.walk(node)
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                and item is not node  # skip the class itself
            }
            # Also collect class-level attribute assignments
            class_attrs = set()
            for item in node.body:
                if isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name):
                            class_attrs.add(target.id)
                elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    class_attrs.add(item.target.id)

            full_allowed = allowed | class_methods | class_attrs

            for method_name in ("up", "down"):
                method_node = _find_method(node, method_name)
                if method_node is None:
                    continue
                self._check_self_access_in_method(
                    method_node, method_name, full_allowed, file_str, violations
                )

    def _check_self_access_in_method(
        self,
        method_node: ast.FunctionDef,
        method_name: str,
        allowed: set[str],
        file_str: str,
        violations: list[ImportCheckViolation],
    ) -> None:
        """Walk a method body for self.x access and self.x() calls."""
        for node in ast.walk(method_node):
            if not isinstance(node, ast.Attribute):
                continue
            if not (isinstance(node.value, ast.Name) and node.value.id == "self"):
                continue

            attr_name = node.attr
            if attr_name in allowed:
                continue

            # Is this a call (self.foo()) or just access (self.foo)?
            # Check parent — but ast.walk doesn't give parents, so check
            # if this Attribute is the func of a Call node.
            is_call = _is_call_func(method_node, node)

            if is_call:
                violations.append(
                    ImportCheckViolation(
                        file_path=file_str,
                        level=3,
                        rule="IMP008",
                        message=(
                            f"self.{attr_name}() in {method_name}() "
                            f"(line {node.lineno}) is not a method on Migration"
                        ),
                    )
                )
            else:
                violations.append(
                    ImportCheckViolation(
                        file_path=file_str,
                        level=3,
                        rule="IMP009",
                        message=(
                            f"self.{attr_name} in {method_name}() "
                            f"(line {node.lineno}) is not an attribute on Migration"
                        ),
                    )
                )

    def _check_execute_file_refs(
        self,
        py_file: Path,
        file_str: str,
        violations: list[ImportCheckViolation],
    ) -> None:
        """Check that self.execute_file() string arguments reference existing files."""
        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(py_file))
        except SyntaxError:
            return

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for method_name in ("up", "down"):
                method_node = _find_method(node, method_name)
                if method_node is None:
                    continue
                for call_node in ast.walk(method_node):
                    if not isinstance(call_node, ast.Call):
                        continue
                    if not (
                        isinstance(call_node.func, ast.Attribute)
                        and isinstance(call_node.func.value, ast.Name)
                        and call_node.func.value.id == "self"
                        and call_node.func.attr == "execute_file"
                    ):
                        continue
                    if not call_node.args:
                        continue

                    arg = call_node.args[0]
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        # String literal — validate file exists
                        ref_path = Path(arg.value)
                        if not ref_path.is_file():
                            violations.append(
                                ImportCheckViolation(
                                    file_path=file_str,
                                    level=3,
                                    rule="IMP010",
                                    message=(
                                        f'self.execute_file("{arg.value}") in {method_name}() '
                                        f"(line {call_node.lineno}) references a file that does not exist"
                                    ),
                                )
                            )
                    else:
                        # Dynamic path — can't validate, warn
                        violations.append(
                            ImportCheckViolation(
                                file_path=file_str,
                                level=3,
                                rule="IMP011",
                                message=(
                                    f"self.execute_file() in {method_name}() "
                                    f"(line {call_node.lineno}) uses a dynamic path — cannot validate"
                                ),
                                severity="warning",
                            )
                        )


def _build_migration_whitelist() -> set[str]:
    """Build the set of allowed self.* names from the Migration base class."""
    from confiture.models.migration import Migration

    allowed: set[str] = set()
    for name in dir(Migration):
        if name.startswith("__"):
            continue
        allowed.add(name)
    # Ensure key attributes are always included
    allowed.update(
        {
            "connection",
            "version",
            "name",
            "transactional",
            "strict_mode",
            "execute",
            "execute_file",
            "up",
            "down",
            "get_up_sql_statements",
            "up_preconditions",
            "down_preconditions",
            "before_validation_hooks",
            "before_ddl_hooks",
            "after_ddl_hooks",
            "after_validation_hooks",
            "cleanup_hooks",
            "error_hooks",
        }
    )
    return allowed


def _find_method(class_node: ast.ClassDef, name: str) -> ast.FunctionDef | None:
    """Find a method definition by name in a class body."""
    for item in class_node.body:
        if isinstance(item, ast.FunctionDef) and item.name == name:
            return item
    return None


def _is_call_func(method_node: ast.FunctionDef, attr_node: ast.Attribute) -> bool:
    """Check if an Attribute node is the func of a Call node in the method."""
    for node in ast.walk(method_node):
        if isinstance(node, ast.Call) and node.func is attr_node:
            return True
    return False


def _is_abstract_method(cls: type, method_name: str) -> bool:
    """Check if a method is still abstract on the class."""
    method = getattr(cls, method_name, None)
    if method is None:
        return True
    return getattr(method, "__isabstractmethod__", False) or (
        inspect.isabstract(cls) and method_name in getattr(cls, "__abstractmethods__", set())
    )
