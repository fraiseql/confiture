"""Shared per-run resources for ``migrate validate`` (#187).

Before 0.40.0 each validation mode returned as soon as it finished, so nothing
was ever shared: five ``core/validation`` handlers each called ``load_config``
and opened their own connection. Once the modes *compose*, running
``--check-signatures --check-live-drift`` would parse the config twice and open
two connections — and over ``--ssh``, spin up two tunnel subprocesses.

:class:`ValidationContext` owns those resources for the whole run. It is lazy:
a run of purely static checks never touches the database, and a config that is
never needed is never read. ``open_connection`` and ``load_config`` are imported
at module scope so tests can patch them here — this module is the single place
the live connection is opened.
"""

from __future__ import annotations

from contextlib import ExitStack
from typing import TYPE_CHECKING, Any

from confiture.core.connection import load_config, open_connection

if TYPE_CHECKING:
    from pathlib import Path
    from types import TracebackType

    import psycopg


class ValidationContext:
    """Config and database connection shared by every check in one run.

    Use as a context manager so the connection — and any SSH tunnel behind it —
    is closed once, after the last check has run::

        with ValidationContext(config_path=cfg, ssh_via=None) as ctx:
            outcomes = run_checks(checks, ctx)

    Attributes:
        config_path: The resolved config file. Not read until something asks.
        ssh_via: ``user@host`` tunnel target overriding the config's own
            ``ssh_tunnel`` block, or ``None``.
        effective_base_ref: ``--since or --base-ref``, resolved once for every
            git-backed check rather than per check.
        staged: Whether ``--staged`` was passed.
    """

    def __init__(
        self,
        *,
        config_path: Path,
        ssh_via: str | None = None,
        effective_base_ref: str = "origin/main",
        staged: bool = False,
    ) -> None:
        self.config_path = config_path
        self.ssh_via = ssh_via
        self.effective_base_ref = effective_base_ref
        self.staged = staged
        self._config_data: Any = None
        self._config_loaded = False
        self._connection: psycopg.Connection[Any] | None = None
        self._stack = ExitStack()

    def __enter__(self) -> ValidationContext:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    @property
    def config_data(self) -> Any:  # noqa: ANN401 — dict or Environment, per load_config
        """The parsed config, read at most once per run."""
        if not self._config_loaded:
            self._config_data = load_config(self.config_path)
            self._config_loaded = True
        return self._config_data

    def connection(self) -> psycopg.Connection[Any]:
        """The live database connection, opened at most once per run.

        Honours ``ssh_via`` by layering an ``ssh_tunnel`` block onto the config,
        the same override ``--check-signatures`` has always applied — which is
        how ``--check-live-drift`` finally gains the ``--ssh`` support its help
        text has always claimed.
        """
        if self._connection is None:
            from confiture.core.validation.signature_drift import _ssh_override

            config = self.config_data
            if self.ssh_via:
                config = _ssh_override(config, self.ssh_via)
            self._connection = self._stack.enter_context(open_connection(config))
        return self._connection

    def close(self) -> None:
        """Release the connection and any tunnel behind it. Idempotent."""
        self._connection = None
        self._stack.close()
        self._stack = ExitStack()
