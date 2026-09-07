"""`confiture branch …` behaviour against a client that has the real PgGitClient interface.

pgGit is a PostgreSQL extension the local test server does not carry, so the commands
are driven through their one seam — ``_get_pggit_client`` — with a fake whose methods
have the *same signatures and return types* as ``PgGitClient`` (``get_branch(name)``,
``get_current_branch()``, ``status() -> StatusInfo``, ``diff() -> list[DiffEntry]``).
A command that calls the client in a way the real client does not support fails here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests._helpers import strip_ansi
from typer.testing import CliRunner

from confiture.cli import branch as branch_cli
from confiture.cli.main import app
from confiture.integrations.pggit.client import Branch, Commit, DiffEntry, MergeResult, StatusInfo

runner = CliRunner()
WHEN = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)


class FakeConnection:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakePgGitClient:
    """Same public surface as PgGitClient, backed by in-memory state."""

    def __init__(self) -> None:
        self.current = "main"
        self.branches: dict[str, Branch] = {
            "main": Branch(name="main", status="ACTIVE", commit_count=3, last_commit=WHEN),
            "feature/x": Branch(name="feature/x", status="ACTIVE", commit_count=1),
        }
        self.commits: list[Commit] = [
            Commit(hash="abcdef1234567890", message="init", author="lionel", timestamp=WHEN),
            Commit(hash="0123456789abcdef", message="add widget"),
        ]
        self.calls: list[tuple] = []
        self.merge_result = MergeResult(success=True, message="ok", merged_objects=2)
        self.diff_entries: list[DiffEntry] = [
            DiffEntry(object_type="TABLE", object_name="widget", operation="CREATE"),
            DiffEntry(object_type="VIEW", object_name="v_widget", operation="ALTER"),
            DiffEntry(object_type="FUNCTION", object_name="fn_old", operation="DROP"),
        ]

    def get_current_branch(self) -> str:
        return self.current

    def get_branch(self, name: str) -> Branch:
        return self.branches[name]

    def list_branches(self, status: str | None = None) -> list[Branch]:
        return list(self.branches.values())

    def create_branch(
        self, name: str, from_branch: str = "main", *, copy_data: bool = False
    ) -> Branch:
        self.calls.append(("create_branch", name, from_branch, copy_data))
        self.branches[name] = Branch(name=name, status="ACTIVE", commit_count=0)
        return self.branches[name]

    def checkout(self, branch_name: str) -> str:
        self.calls.append(("checkout", branch_name))
        self.current = branch_name
        return f"Switched to branch {branch_name}"

    def delete_branch(self, name: str, *, force: bool = False) -> None:
        self.calls.append(("delete_branch", name, force))
        del self.branches[name]

    def status(self) -> StatusInfo:
        return StatusInfo(
            components={"tracking": {"status": "active"}},
            current_branch=self.current,
            tracking_enabled=True,
        )

    def commit(self, message: str, *, author: str | None = None) -> Commit:
        self.calls.append(("commit", message))
        return Commit(hash="fedcba9876543210", message=message, author=author)

    def log(self, _branch: str | None = None, limit: int = 50) -> list[Commit]:
        return self.commits[:limit]

    def merge(self, source_branch: str, target_branch: str = "main") -> MergeResult:
        self.calls.append(("merge", source_branch, target_branch))
        return self.merge_result

    def abort_merge(self) -> None:
        self.calls.append(("abort_merge",))

    def diff(self, from_ref: str, to_ref: str = "HEAD") -> list[DiffEntry]:
        self.calls.append(("diff", from_ref, to_ref))
        return self.diff_entries


@pytest.fixture
def fake(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[FakePgGitClient, FakeConnection, Path]:
    client, conn = FakePgGitClient(), FakeConnection()
    monkeypatch.setattr(branch_cli, "_get_pggit_client", lambda config: (client, conn))
    config = tmp_path / "local.yaml"
    config.write_text("name: local\ndatabase_url: postgresql://x/y\n")
    return client, conn, config


def _run(config: Path, *args: str):
    result = runner.invoke(app, ["branch", *args, "--config", str(config)])
    return result, strip_ansi(result.output)


def test_list_table_marks_the_current_branch(fake) -> None:
    _client, conn, config = fake
    result, out = _run(config, "list")
    assert result.exit_code == 0, out
    assert "feature/x" in out and "Current branch: main" in out
    assert conn.closed


def test_list_json_is_machine_readable(fake) -> None:
    import json

    _client, _conn, config = fake
    result, out = _run(config, "list", "--format", "json")
    assert result.exit_code == 0, out
    payload = json.loads(out)
    assert payload["current"] == "main"
    assert {b["name"]: b["is_current"] for b in payload["branches"]} == {
        "main": True,
        "feature/x": False,
    }
    assert payload["branches"][0]["created_at"] == WHEN.isoformat()


def test_create_then_checkout(fake) -> None:
    client, _conn, config = fake
    result, out = _run(config, "create", "feature/y", "--from", "main", "--checkout")
    assert result.exit_code == 0, out
    assert (
        "create_branch",
        "feature/y",
        "main",
        True,
    ) in client.calls  # --copy-data is on by default
    assert ("checkout", "feature/y") in client.calls
    assert client.current == "feature/y"


def test_checkout_switches(fake) -> None:
    client, _conn, config = fake
    result, out = _run(config, "checkout", "feature/x")
    assert result.exit_code == 0, out
    assert client.current == "feature/x"


def test_delete_refuses_the_current_branch(fake) -> None:
    client, _conn, config = fake
    result, _out = _run(config, "delete", "main")
    assert result.exit_code != 0
    assert "main" in client.branches
    assert not any(c[0] == "delete_branch" for c in client.calls)


def test_delete_other_branch_with_force(fake) -> None:
    client, _conn, config = fake
    result, out = _run(config, "delete", "feature/x", "--force")
    assert result.exit_code == 0, out
    assert ("delete_branch", "feature/x", True) in client.calls


def test_status_renders_the_real_status_info(fake) -> None:
    _client, _conn, config = fake
    result, out = _run(config, "status")
    assert result.exit_code == 0, out
    assert "On branch: main" in out
    assert "tracking" in out.lower()


def test_commit_records_the_message(fake) -> None:
    client, _conn, config = fake
    result, out = _run(config, "commit", "add widget")
    assert result.exit_code == 0, out
    assert ("commit", "add widget") in client.calls
    assert "fedcba98" in out


def test_log_respects_the_limit(fake) -> None:
    _client, _conn, config = fake
    result, out = _run(config, "log", "--limit", "1")
    assert result.exit_code == 0, out
    assert "abcdef1234567890" in out and "0123456789abcdef" not in out
    assert "Author: lionel" in out


def test_merge_dry_run_lists_the_diff_by_operation(fake) -> None:
    client, _conn, config = fake
    result, out = _run(config, "merge", "feature/x", "--dry-run")
    assert result.exit_code == 0, out
    assert "CREATE: TABLE widget" in out
    assert not any(c[0] == "merge" for c in client.calls)


def test_merge_success_reports_merged_objects(fake) -> None:
    client, _conn, config = fake
    result, out = _run(config, "merge", "feature/x")
    assert result.exit_code == 0, out
    assert ("merge", "feature/x", "main") in client.calls
    assert "Successfully merged" in out


def test_merge_conflict_is_pggit_900(fake) -> None:
    client, _conn, config = fake
    client.merge_result = MergeResult(
        success=False,
        message="conflicts",
        conflicts=[{"object_type": "TABLE", "object_name": "widget"}],
    )
    result, out = _run(config, "merge", "feature/x")
    assert result.exit_code != 0
    assert "TABLE: widget" in out
    assert "merge-abort" in out


def test_merge_abort(fake) -> None:
    client, _conn, config = fake
    result, out = _run(config, "merge-abort")
    assert result.exit_code == 0, out
    assert ("abort_merge",) in client.calls


def test_diff_groups_by_operation(fake) -> None:
    client, _conn, config = fake
    result, out = _run(config, "diff")
    assert result.exit_code == 0, out
    assert ("diff", "main", "main") in client.calls
    assert "widget" in out and "v_widget" in out and "fn_old" in out


def test_diff_identical_branches(fake) -> None:
    client, _conn, config = fake
    client.diff_entries = []
    result, out = _run(config, "diff")
    assert result.exit_code == 0, out
    assert "identical" in out


def test_missing_pggit_is_a_precondition_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from confiture.exceptions import ConfiturError

    def _raise(config: Path):
        raise ConfiturError("pgGit extension is not installed", error_code="PRECON_1000")

    monkeypatch.setattr(branch_cli, "_get_pggit_client", _raise)
    config = tmp_path / "local.yaml"
    config.write_text("name: local\ndatabase_url: postgresql://x/y\n")
    result, out = _run(config, "list")
    assert result.exit_code == 5
    assert "pgGit" in out
