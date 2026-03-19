"""SSH tunnel context manager for remote database access.

Opens an ``ssh -N -L`` tunnel before yielding a patched database URL,
then tears the tunnel down on exit — even when an exception is raised.

Two remote-side transport modes are supported:

* **TCP** (default): forward to ``remote_host:remote_port``.
* **Unix socket**: set ``remote_socket`` to the socket path on the server
  (e.g. ``/var/run/postgresql/.s.PGSQL.5432``).  Requires OpenSSH ≥ 6.7.

The ``local_port`` may be 0, in which case a free OS-assigned port is
picked automatically.  The ``database_url`` is expected to contain the
literal ``${TUNNEL_LOCAL_PORT}`` placeholder, which is substituted with
the real port before yielding.
"""

from __future__ import annotations

import socket
import subprocess
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from confiture.config.environment import SshTunnelConfig


def _find_free_port() -> int:
    """Bind to port 0 and let the OS choose a free port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("localhost", 0))
        return s.getsockname()[1]  # type: ignore[no-any-return]


def _wait_for_port(port: int, timeout: int) -> None:
    """Poll localhost:port until it accepts connections or timeout expires.

    Args:
        port: Local TCP port to probe.
        timeout: Maximum seconds to wait.

    Raises:
        TimeoutError: If the port does not accept a connection within *timeout* seconds.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("localhost", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.2)
    raise TimeoutError(f"SSH tunnel did not open on port {port} within {timeout}s")


def _build_ssh_cmd(config: SshTunnelConfig, local_port: int) -> list[str]:
    """Construct the ``ssh`` command list from a tunnel config.

    Args:
        config: Tunnel configuration.
        local_port: Resolved local port (must not be 0).

    Returns:
        Argument list suitable for ``subprocess.Popen``.
    """
    if config.remote_socket:
        forward = f"{local_port}:{config.remote_socket}"
    else:
        forward = f"{local_port}:{config.remote_host}:{config.remote_port}"

    cmd: list[str] = [
        "ssh",
        "-N",
        "-L",
        forward,
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        f"ConnectTimeout={config.timeout_s}",
    ]

    if config.identity_file:
        cmd += ["-i", str(Path(config.identity_file).expanduser())]

    user_host = f"{config.user}@{config.host}" if config.user else config.host
    cmd.append(user_host)
    return cmd


@contextmanager
def ssh_tunnel(
    config: SshTunnelConfig,
    database_url: str,
) -> Generator[str, None, None]:
    """Open an SSH tunnel and yield a patched *database_url*.

    Replaces the ``${TUNNEL_LOCAL_PORT}`` placeholder in *database_url* with
    the actual local port after the tunnel opens, then yields the patched URL.
    The SSH subprocess is terminated in the ``finally`` block regardless of
    whether the body raises.

    Args:
        config: SSH tunnel configuration (host, user, ports/socket, …).
        database_url: PostgreSQL connection URL containing
            ``${TUNNEL_LOCAL_PORT}`` where the local port should be inserted.

    Yields:
        Patched *database_url* with the real port substituted.

    Raises:
        TimeoutError: If the tunnel does not open within ``config.timeout_s`` seconds.
        FileNotFoundError: If the ``ssh`` binary is not on ``PATH``.

    Example::

        with ssh_tunnel(config, "postgresql://localhost:${TUNNEL_LOCAL_PORT}/mydb") as url:
            conn = psycopg.connect(url)
    """
    local_port = config.local_port if config.local_port > 0 else _find_free_port()
    cmd = _build_ssh_cmd(config, local_port)

    proc = subprocess.Popen(cmd, stderr=subprocess.PIPE)  # noqa: S603
    try:
        _wait_for_port(local_port, timeout=config.timeout_s)
        patched_url = database_url.replace("${TUNNEL_LOCAL_PORT}", str(local_port))
        yield patched_url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
