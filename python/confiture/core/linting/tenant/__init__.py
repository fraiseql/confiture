"""Tenant isolation linting for multi-tenant PostgreSQL schemas.

This module provides tools to detect INSERT statements in functions
that are missing FK columns required for tenant filtering.
"""

from confiture.core.linting.tenant.formatter import TenantIsolationFormatter
from confiture.core.linting.tenant.function_parser import (
    FunctionInfo,
    FunctionParser,
    InsertStatement,
)
from confiture.core.linting.tenant.insert_analyzer import InsertAnalyzer
from confiture.core.linting.tenant.models import (
    TenantConfig,
    TenantRelationship,
    TenantViolation,
)
from confiture.core.linting.tenant.tenant_detector import TenantDetector
from confiture.core.linting.tenant.tenant_isolation_rule import TenantIsolationRule
from confiture.core.linting.tenant.view_parser import ViewParser

__all__ = [
    "FunctionInfo",
    "FunctionParser",
    "InsertAnalyzer",
    "InsertStatement",
    "TenantConfig",
    "TenantDetector",
    "TenantIsolationFormatter",
    "TenantIsolationRule",
    "TenantRelationship",
    "TenantViolation",
    "ViewParser",
]
