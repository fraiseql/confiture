"""Scaffold package — pluggable SQL function file generation.

Public API::

    from confiture.core.scaffold import EmittedFunction, ConfitureEmitter
    from confiture.core.scaffold import ScaffoldOrchestrator, ScaffoldResult
"""

from confiture.core.scaffold.emitter import ConfitureEmitter, EmittedFunction
from confiture.core.scaffold.orchestrator import ScaffoldOrchestrator, ScaffoldResult

__all__ = [
    "ConfitureEmitter",
    "EmittedFunction",
    "ScaffoldOrchestrator",
    "ScaffoldResult",
]
