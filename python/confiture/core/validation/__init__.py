"""Validation orchestration for ``confiture migrate validate`` modes.

Each module here owns the *logic* of one validate mode — loading the relevant
config block, running the core check, and returning a typed result model. They
raise :class:`~confiture.exceptions.ConfiturError` on failure (never
``typer.Exit``) so the CLI dispatcher can funnel every failure through the
single ``fail()`` error boundary (#145/#146). Rendering lives separately in
``confiture.cli.formatters.validate_formatter``.
"""

from __future__ import annotations
