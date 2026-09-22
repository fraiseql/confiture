"""Builtin migration hooks for production deployments.

Notification hooks live in :mod:`confiture.core.hooks.notifications` —
the layered Transport / Renderer / Hook architecture, configured via
YAML.  This package holds no per-service notification class; pick a
transport + renderer from the notifications package.
"""

from confiture.core.hooks.builtin.audit_hook import AuditConfig, AuditHook
from confiture.core.hooks.builtin.backup_hook import BackupConfig, BackupHook

__all__ = [
    "AuditConfig",
    "AuditHook",
    "BackupConfig",
    "BackupHook",
]
