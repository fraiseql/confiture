"""Every pattern whose meaning changed in 1.5.0 says so, in both directions.

Left-anchoring removes files from a build *and* adds them to one: a relative
pattern like ``temp/*.sql`` used to match at any depth, so files it excluded
before are now built. A project has to be told before the change reaches a
build, and told which way it went.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.builder import SchemaBuilder
from confiture.exceptions import SchemaError

runner = CliRunner()


def _project(
    tmp_path: Path,
    *,
    include: list[str],
    exclude: list[str],
    files: list[str],
    recursive: bool = True,
) -> Path:
    schema_dir = tmp_path / "db" / "schema"
    for relative in files:
        path = schema_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("SELECT 1;\n")

    def block(key: str, patterns: list[str]) -> str:
        if not patterns:
            return ""
        return f"    {key}:\n" + "".join(f'      - "{pattern}"\n' for pattern in patterns)

    env_dir = tmp_path / "db" / "environments"
    env_dir.mkdir(parents=True)
    (env_dir / "local.yaml").write_text(
        "name: local\ndatabase_url: postgresql://localhost/test\n"
        "include_dirs:\n"
        f"  - path: {schema_dir}\n"
        f"    recursive: {str(recursive).lower()}\n"
        + block("include", include)
        + block("exclude", exclude)
        + "build:\n  validate_comments:\n    enabled: false\n"
    )
    return tmp_path


def _notes(project: Path) -> list[tuple[str, str, str]]:
    """The diagnostics themselves — computed without selecting, so an empty build still reports."""
    builder = SchemaBuilder(env="local", project_dir=project)
    return [(note.code, note.pattern, note.message) for note in builder.pattern_diagnostics()]


def test_a_pattern_that_now_matches_nothing_is_a_warning(tmp_path: Path) -> None:
    """``temp/*.sql`` excluded three files at depth; left-anchored it excludes none."""
    project = _project(
        tmp_path,
        include=["**/*.sql"],
        exclude=["temp/*.sql"],
        files=["a/temp/x.sql", "b/temp/y.sql", "c/temp/z.sql", "keep.sql"],
    )

    notes = _notes(project)

    assert [(code, pattern) for code, pattern, _ in notes] == [("CONFIG_013", "temp/*.sql")]
    message = notes[0][2]
    assert "3" in message
    assert "**/temp/*.sql" in message


def test_a_pattern_that_now_matches_more_is_an_info(tmp_path: Path) -> None:
    """``**/temp/**`` did not exclude a root-level ``temp/``; now it does."""
    project = _project(
        tmp_path,
        include=["**/*.sql"],
        exclude=["**/temp/**"],
        files=["temp/a.sql", "temp/b.sql", "keep.sql"],
    )

    notes = _notes(project)

    assert [(code, pattern) for code, pattern, _ in notes] == [("CONFIG_014", "**/temp/**")]
    assert "2" in notes[0][2]


def test_the_include_side_is_reported_too(tmp_path: Path) -> None:
    """Only a replay of the whole 1.4.0 selection can see this direction."""
    project = _project(
        tmp_path,
        include=["10_tables/*.sql"],
        exclude=[],
        files=["10_tables/x.sql", "a/10_tables/y.sql"],
    )

    notes = _notes(project)

    assert [(code, pattern) for code, pattern, _ in notes] == [("CONFIG_014", "10_tables/*.sql")]
    assert "a/10_tables/y.sql" in notes[0][2]


def test_empty_selection_error_carries_the_diagnostic(tmp_path: Path) -> None:
    """The failure this release most plausibly creates explains itself where it is reported."""
    project = _project(
        tmp_path,
        include=["10_tables/*.sql"],
        exclude=[],
        files=["a/10_tables/y.sql"],
    )

    with pytest.raises(SchemaError) as raised:
        SchemaBuilder(env="local", project_dir=project).find_sql_files()

    hint = raised.value.resolution_hint or ""
    assert "10_tables/*.sql" in hint
    assert "**/10_tables/*.sql" in hint


def test_replay_is_skipped_when_no_pattern_can_have_changed(tmp_path: Path, monkeypatch) -> None:
    """A config whose patterns carry no ``/`` cannot have changed meaning."""
    project = _project(
        tmp_path,
        include=["*.sql"],
        exclude=["*.bak"],
        files=["x.sql", "a/b/y.sql", "a/z.bak"],
    )
    walks: list[str] = []
    real_rglob = Path.rglob

    def counting_rglob(self, pattern, *args, **kwargs):
        walks.append(pattern)
        return real_rglob(self, pattern, *args, **kwargs)

    monkeypatch.setattr(Path, "rglob", counting_rglob)

    assert _notes(project) == []
    assert walks == []

    # …and a config that can have changed does pay for the replay, so the
    # assertion above is about the skip and not about the replay being absent.
    slashed = _project(
        tmp_path / "slashed",
        include=["**/*.sql"],
        exclude=["temp/*.sql"],
        files=["a/temp/x.sql", "keep.sql"],
    )
    _notes(slashed)
    assert walks != []


def test_build_prints_the_diagnostics(tmp_path: Path) -> None:
    """A project sees them without asking for them."""
    project = _project(
        tmp_path,
        include=["**/*.sql"],
        exclude=["temp/*.sql"],
        files=["a/temp/x.sql", "keep.sql"],
    )

    result = runner.invoke(
        app,
        [
            "build",
            "--env",
            "local",
            "--project-dir",
            str(project),
            "--output",
            str(tmp_path / "schema.sql"),
        ],
    )

    assert result.exit_code == 0
    assert "CONFIG_013" in result.stdout
    assert "temp/*.sql" in result.stdout


def test_validate_config_reports_them_as_issues(tmp_path: Path) -> None:
    """``validate-config`` folds them into the issues it already has."""
    project = _project(
        tmp_path,
        include=["**/*.sql"],
        exclude=["temp/*.sql"],
        files=["a/temp/x.sql", "keep.sql"],
    )

    result = runner.invoke(
        app,
        [
            "validate-config",
            "--config",
            str(project / "db" / "environments" / "local.yaml"),
            "--format",
            "json",
        ],
    )

    payload = json.loads(result.stdout)
    codes = [issue["code"] for issue in payload["issues"]]
    assert "CONFIG_013" in codes


def test_the_empty_build_is_not_reported_as_a_missing_directory(tmp_path: Path) -> None:
    """The terminal shows the pattern that emptied the build, not a canned wrong cause.

    ``No SQL files found`` used to route to the missing-schema-directory
    template, which prints "The schema directory doesn't exist" and tells the
    reader to ``mkdir`` it — over a directory that exists and is full of files
    the patterns stopped matching.
    """
    project = _project(
        tmp_path,
        include=["10_tables/*.sql"],
        exclude=[],
        files=["a/10_tables/y.sql"],
    )

    result = runner.invoke(
        app,
        [
            "build",
            "--env",
            "local",
            "--project-dir",
            str(project),
            "--output",
            str(tmp_path / "schema.sql"),
        ],
    )

    assert result.exit_code != 0
    assert "schema directory doesn't exist" not in result.stderr.lower()
    assert "mkdir" not in result.stderr
    assert "10_tables/*.sql" in result.stderr
    assert "10_tables/*.sql" in result.stdout


def test_a_pattern_that_needs_a_subdirectory_says_so(tmp_path: Path) -> None:
    """``recursive: false`` and a pattern that requires depth is a contradiction, not a mystery."""
    project = _project(
        tmp_path,
        include=["**/sub/*.sql"],
        exclude=[],
        files=["a/sub/deep.sql"],
        recursive=False,
    )

    notes = _notes(project)

    assert [(code, pattern) for code, pattern, _ in notes] == [("CONFIG_013", "**/sub/*.sql")]
    assert "recursive: false" in notes[0][2]


def test_the_default_include_under_non_recursive_says_nothing(tmp_path: Path) -> None:
    """``recursive: false`` + ``**/*.sql`` is normal and must stay silent.

    It is the model's default include, so a diagnostic here would fire for
    every non-recursive entry in every project and redden a currently-green
    ``validate-config --strict``.
    """
    project = _project(
        tmp_path,
        include=["**/*.sql"],
        exclude=[],
        files=["top.sql", "a/b/deep.sql"],
        recursive=False,
    )

    assert _notes(project) == []
