"""Builtin migration hooks for production deployments.

Notification hooks live in :mod:`confiture.core.hooks.notifications` —
the layered Transport / Renderer / Hook architecture, configured via
YAML.  Per-service helper classes used to live here but have been
removed; pick a transport + renderer from the notifications package
instead.
"""

from confiture.core.hooks.builtin.audit_hook import AuditConfig, AuditHook
from confiture.core.hooks.builtin.backup_hook import BackupConfig, BackupHook

__all__ = [
    "AuditConfig",
    "AuditHook",
    "BackupConfig",
    "BackupHook",
]
