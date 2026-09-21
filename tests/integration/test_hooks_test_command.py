"""``confiture hooks test``, run by its command line against a real HTTP endpoint.

The hook under test is an HTTP transport with a Slack renderer, pointed at a
server this file starts on ``127.0.0.1``, so "contacted nothing" and "delivered
it" are observed at the far end of a socket rather than inferred from a patched
``send``. The file pins:

- ``--mode plan`` renders the notification to stdout and the endpoint receives
  nothing; so does the bare command, whose default mode is ``plan``, whether the
  environment is named by ``--config`` or ``--env``;
- ``--mode send`` POSTs to the endpoint the very payload ``plan`` printed;
- a ``send`` the endpoint cannot receive exits 1 and says the hook failed.
"""

from __future__ import annotations

import json
import socket
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.error_codes import FINDINGS

pytestmark = pytest.mark.integration

runner = CliRunner()


@dataclass
class Received:
    path: str
    content_type: str | None
    body: bytes


@dataclass
class Endpoint:
    """A local HTTP server and every request it has received."""

    url: str
    requests: list[Received] = field(default_factory=list)


@pytest.fixture
def endpoint() -> Iterator[Endpoint]:
    received: list[Received] = []

    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            received.append(
                Received(self.path, self.headers.get("Content-Type"), self.rfile.read(length))
            )
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, format: str, *args: object) -> None:
            """Keep the server quiet: the requests are the record."""

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield Endpoint(url=f"http://127.0.0.1:{server.server_address[1]}/hook", requests=received)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _environment_yaml(url: str) -> str:
    return (
        "name: test\n"
        "database_url: postgresql://localhost/nonexistent\n"
        "include_dirs: [db/schema]\n"
        "notifications:\n"
        "  hooks:\n"
        "    - id: team-slack\n"
        f'      transport: {{type: http, url: "{url}"}}\n'
        '      renderer: {type: slack, channel: "#migrations"}\n'
    )


@pytest.fixture
def config(tmp_path: Path, endpoint: Endpoint) -> Path:
    """``db/environments/test.yaml`` holding one hook that POSTs to *endpoint*."""
    environments = tmp_path / "db" / "environments"
    environments.mkdir(parents=True)
    path = environments / "test.yaml"
    path.write_text(_environment_yaml(endpoint.url))
    return path


def _rendered(stdout: str) -> dict:
    """The one notification payload the plan wrote to stdout among its status lines."""
    (line,) = [line for line in stdout.splitlines() if line.startswith("{")]
    return json.loads(line)


def _without_clock(payload: dict) -> dict:
    """*payload* minus the Slack ``Time`` field, which reads the wall clock to the minute."""
    attachment = payload["attachments"][0]
    fields = [f for f in attachment["fields"] if f["title"] != "Time"]
    return {**payload, "attachments": [{**attachment, "fields": fields}]}


def test_plan_renders_the_notification_and_contacts_nothing(
    config: Path, endpoint: Endpoint
) -> None:
    result = runner.invoke(app, ["hooks", "test", "--config", str(config), "--mode", "plan"])

    assert result.exit_code == 0, result.output
    payload = _rendered(result.stdout)
    assert payload["channel"] == "#migrations"
    (attachment,) = payload["attachments"]
    assert attachment["title"] == "Migration Succeeded"
    assert {f["title"]: f["value"] for f in attachment["fields"]}["Migration"] == (
        "synthetic_test_migration"
    )
    assert endpoint.requests == []


def test_the_bare_command_plans_and_reads_the_environment_named_by_env(
    config: Path, endpoint: Endpoint, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(config.parents[2])

    result = runner.invoke(app, ["hooks", "test", "--env", "test"])

    assert result.exit_code == 0, result.output
    assert _rendered(result.stdout)["channel"] == "#migrations"
    assert endpoint.requests == []


def test_send_delivers_the_payload_plan_rendered(config: Path, endpoint: Endpoint) -> None:
    plan = runner.invoke(app, ["hooks", "test", "--config", str(config)])
    assert plan.exit_code == 0, plan.output
    assert endpoint.requests == []

    result = runner.invoke(app, ["hooks", "test", "--config", str(config), "--mode", "send"])

    assert result.exit_code == 0, result.output
    (request,) = endpoint.requests
    assert (request.path, request.content_type) == ("/hook", "application/json")
    assert _without_clock(json.loads(request.body)) == _without_clock(_rendered(plan.stdout))


def _closed_port() -> int:
    """A port on 127.0.0.1 that nothing listens on."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_send_to_an_endpoint_that_refuses_reports_the_hook_failed(tmp_path: Path) -> None:
    config = tmp_path / "confiture.yaml"
    config.write_text(_environment_yaml(f"http://127.0.0.1:{_closed_port()}/hook"))

    result = runner.invoke(app, ["hooks", "test", "--config", str(config), "--mode", "send"])

    assert result.exit_code == FINDINGS, result.output
    assert "Hook 'team-slack' failed" in result.stdout
