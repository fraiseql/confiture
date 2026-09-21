"""A ``--config`` named on the command line is read (issue #284).

`migrate status`, `migrate validate`, `migrate fix` and `migrate preflight` took
a `--config` path and never opened it. A file that would not parse, or that did
not exist at all, produced the same green output and the same exit 0 as a valid
one — and `migrate preflight` rendered a full Pre-flight Check table, which is a
pre-deployment gate reporting on a configuration that was not there.

The invariant is the whole guard and needs no allow-list: **no command succeeds
with a `--config` it could not read**. A command that exits 2 because it has a
required argument satisfies it honestly; only one that prints a tick violates it.

The *ambient* `confiture.yaml` keeps its behaviour. #152's precedence contract
says a merely-present config must not force a connection, and that is still
true — what changed is a path the operator typed.
"""

from pathlib import Path

import pytest
from typer.main import get_command
from typer.testing import CliRunner

from confiture.cli.main import app

BROKEN_YAML = (
    "name: probe\ndatabase_url: postgresql://localhost/somedb\n"
    "  this line is indented wrong: and: breaks: yaml\n"
)


def commands_declaring_config() -> list[str]:
    """Every leaf command with a ``--config`` option, as a space-joined path.

    Walks ``.commands`` by duck typing: ``TyperGroup`` is not a ``click.Group``
    *instance* here, so ``isinstance`` finds nothing and the sweep silently
    returns an empty list — a guard that passes because it checked nothing.
    """

    def walk(command, path=()):
        subs = getattr(command, "commands", None)
        if subs:
            for name, sub in subs.items():
                yield from walk(sub, (*path, name))
            return
        for param in getattr(command, "params", []):
            if "--config" in (getattr(param, "opts", []) or []):
                yield " ".join(path)
                break

    return sorted(walk(get_command(app)))


ALL_COMMANDS = commands_declaring_config()


def test_the_sweep_found_the_commands():
    """A floor: an empty sweep would make every test below vacuous."""
    assert len(ALL_COMMANDS) > 20
    for expected in ("migrate status", "migrate validate", "migrate fix", "migrate preflight"):
        assert expected in ALL_COMMANDS


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty project: migrations directory, no config file."""
    (tmp_path / "db" / "migrations").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.mark.parametrize("command", ALL_COMMANDS)
def test_no_command_succeeds_with_a_config_that_does_not_exist(command: str, project: Path):
    result = CliRunner().invoke(app, [*command.split(), "--config", "absent.yaml"])
    assert result.exit_code != 0, (
        f"`confiture {command} --config absent.yaml` exited 0 in an empty project. "
        f"A path the operator typed and the command never opened is the shape of "
        f"a gate that cannot fail.\n{result.output}"
    )


@pytest.mark.parametrize("command", ALL_COMMANDS)
def test_no_command_succeeds_with_a_config_that_does_not_parse(command: str, project: Path):
    (project / "broken.yaml").write_text(BROKEN_YAML)
    result = CliRunner().invoke(app, [*command.split(), "--config", "broken.yaml"])
    assert result.exit_code != 0, (
        f"`confiture {command} --config broken.yaml` exited 0 on YAML that does "
        f"not parse.\n{result.output}"
    )


class TestTheFourFromTheReport:
    """Named, so a regression says which command rather than which parameter."""

    @pytest.mark.parametrize(
        "command", ["migrate status", "migrate validate", "migrate fix", "migrate preflight"]
    )
    def test_a_missing_config_is_config_004(self, command: str, project: Path):
        result = CliRunner().invoke(app, [*command.split(), "--config", "absent.yaml"])
        assert result.exit_code == 5
        assert "CONFIG_004" in result.output

    @pytest.mark.parametrize(
        "command", ["migrate status", "migrate validate", "migrate fix", "migrate preflight"]
    )
    def test_an_unparseable_config_is_config_002(self, command: str, project: Path):
        (project / "broken.yaml").write_text(BROKEN_YAML)
        result = CliRunner().invoke(app, [*command.split(), "--config", "broken.yaml"])
        assert result.exit_code == 5
        assert "CONFIG_002" in result.output


class TestTheAmbientConfigIsUnchanged:
    """#152: a merely-present `confiture.yaml` must not force a connection."""

    def test_status_without_a_config_flag_still_reports(self, project: Path):
        result = CliRunner().invoke(app, ["migrate", "status"])
        assert result.exit_code == 0

    def test_an_ambient_broken_config_is_still_not_opened(self, project: Path):
        """Not a regression to fix here — the contract says ambient is ambient.

        `migrate status` declares `--config` with a default of `None`, so this
        alone does not pin the rule: a helper that checked *every* config, not
        only an explicit one, would still pass. `migrate fix` below is the case
        that bites, because its default is a present path.
        """
        (project / "confiture.yaml").write_text(BROKEN_YAML)
        result = CliRunner().invoke(app, ["migrate", "status"])
        assert result.exit_code == 0

    def test_a_defaulted_config_path_is_not_opened_either(self, project: Path):
        """`migrate fix` defaults `--config` to `confiture.yaml` — a *present* path.

        That default is exactly what `config_is_explicit` exists to tell from an
        operator's flag (#152): the resolved `Path` is identical either way. A
        check that looked only at the value would open this file and fail a
        command that was never asked to read it.
        """
        (project / "confiture.yaml").write_text(BROKEN_YAML)
        result = CliRunner().invoke(app, ["migrate", "fix"])
        assert result.exit_code == 0
        assert "No fix type specified" in result.output

    def test_a_defaulted_config_path_that_is_absent_is_not_opened(self, project: Path):
        result = CliRunner().invoke(app, ["migrate", "fix"])
        assert result.exit_code == 0
