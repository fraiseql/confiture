"""Base classes for hooks with priority and dependencies."""
from __future__ import annotations


from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar
from datetime import datetime

T = TypeVar("T")


@dataclass
class HookResult:
    """Result of hook execution."""

    success: bool
    rows_affected: int = 0
    stats: dict[str, Any] | None = None
    error: str | None = None


class Hook(Generic[T], ABC):
    """Base class for all hooks."""

    def __init__(
        self,
        hook_id: str,
        name: str,
        priority: int = 5,  # 1-10, lower = higher priority
        depends_on: list[str] | None = None,
    ):
        self.id = hook_id
        self.name = name
        self.priority = priority
        self.depends_on = depends_on or []

    @abstractmethod
    async def execute(self, context: "HookContext[T]") -> HookResult:
        """Execute hook - must be implemented by subclasses."""
        pass
