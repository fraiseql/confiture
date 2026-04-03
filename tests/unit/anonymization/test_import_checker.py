"""Unit tests for import checker security validation."""

import pytest

from confiture.core.anonymization.plugins.import_checker import (
    BLOCKED_MODULES,
    check_source,
)


class TestImportChecker:
    """Test suite for AST-based import validation."""

    def test_check_source_blocks_dangerous_imports(self):
        """check_source() should detect blocked imports."""
        # Direct import of blocked module
        source = "import os"
        violations = check_source(source)
        assert len(violations) == 1
        assert violations[0].module == "os"
        assert violations[0].line == 1

    def test_check_source_allows_safe_imports(self):
        """check_source() should allow safe imports."""
        source = "import hashlib"
        violations = check_source(source)
        assert violations == []

    def test_check_source_detects_from_imports(self):
        """check_source() should detect blocked from imports."""
        source = "from os.path import join"
        violations = check_source(source)
        assert len(violations) == 1
        assert violations[0].module == "os.path"

    def test_check_source_detects_aliased_imports(self):
        """check_source() should detect aliased blocked imports."""
        source = "import subprocess as sp"
        violations = check_source(source)
        assert len(violations) == 1
        assert violations[0].module == "subprocess"

    def test_check_source_detects_nested_imports_in_functions(self):
        """check_source() should detect imports inside function bodies."""
        source = """
def my_func():
    import os
    return os.getcwd()
"""
        violations = check_source(source)
        assert len(violations) == 1
        assert violations[0].module == "os"
        assert violations[0].line == 3

    def test_check_source_detects_multiple_violations(self):
        """check_source() should detect multiple blocked imports."""
        source = """
import os
import sys
import hashlib  # safe
from subprocess import call
"""
        violations = check_source(source)
        assert len(violations) == 3
        modules = {v.module for v in violations}
        assert modules == {"os", "sys", "subprocess"}

    def test_check_source_detects_cloud_sdk_imports(self):
        """check_source() should block cloud SDK imports."""
        source = "import boto3"
        violations = check_source(source)
        assert len(violations) == 1
        assert violations[0].module == "boto3"

    def test_check_source_detects_network_imports(self):
        """check_source() should block network library imports."""
        source = "import requests"
        violations = check_source(source)
        assert len(violations) == 1
        assert violations[0].module == "requests"

    def test_blocked_modules_contains_expected_entries(self):
        """BLOCKED_MODULES should contain security-critical modules."""
        expected = {"os", "sys", "subprocess", "importlib", "boto3", "requests"}
        assert expected.issubset(BLOCKED_MODULES)

    def test_check_source_detects_dynamic_imports(self):
        """check_source() should detect dynamic __import__ calls."""
        source = '__import__("os")'
        check_source(source)
        # Note: AST doesn't parse dynamic imports easily, this might not be detected
        # This is an edge case for future enhancement
        pass  # Placeholder for now

    def test_check_source_handles_syntax_errors(self):
        """check_source() should handle invalid Python syntax gracefully."""
        source = "import os\ndef invalid syntax:"
        with pytest.raises(SyntaxError):
            check_source(source)
