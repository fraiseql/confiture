"""Every example environment file and README snippet loads through the real ``Environment`` model.

``examples/*/db/environments/*.yaml`` are what a reader copies first. A file the model
rejects (the pre-0.10 ``database:`` block, an unknown key) is documentation of a
configuration format that does not exist. The files come from ``git ls-files`` — tracked
examples only, never whatever a build left under ``examples/`` — inside the tests rather
than at collection time (``test_collection_integrity``), with a floor on the count so an
empty listing cannot pass vacuously.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from confiture.config.environment import Environment

REPO_ROOT = Path(__file__).resolve().parents[3]
PLACEHOLDER_DSN = "postgresql://user:secret@db.example.internal:5432/app"
MIN_ENV_FILES = 6
MIN_README_FILES = 5
_YAML_BLOCK = re.compile(r"```ya?ml\n(.*?)```", re.S)
_ENV_VAR = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)(?::-[^}]*)?\}")


def _tracked(*patterns: str) -> list[Path]:
    """Tracked files matching the git pathspecs, relative to the repo root."""
    out = subprocess.run(
        ["git", "ls-files", "--", *patterns],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return sorted(REPO_ROOT / line for line in out.splitlines() if line)


def _env_files() -> list[Path]:
    return _tracked("examples/*/db/environments/*.yaml")


def _readme_files() -> list[Path]:
    return _tracked("examples/*/README.md", "examples/*/QUICK_START.md")


def test_every_example_environment_file_loads(monkeypatch: pytest.MonkeyPatch) -> None:
    files = _env_files()
    assert len(files) >= MIN_ENV_FILES, "the examples lost their environment files"
    failures: list[str] = []
    for env_file in files:
        for var in set(_ENV_VAR.findall(env_file.read_text())):
            monkeypatch.setenv(var, PLACEHOLDER_DSN if "URL" in var or "DSN" in var else "x")
        try:
            env = Environment.load(env_file.stem, project_dir=env_file.parents[2])
        except Exception as exc:
            failures.append(f"{env_file.relative_to(REPO_ROOT)}: {exc}")
            continue
        if env.name != env_file.stem:
            failures.append(f"{env_file.relative_to(REPO_ROOT)}: name {env.name!r} != file stem")
    assert failures == [], "example environment files the model rejects:\n" + "\n".join(failures)


def _environment_blocks(markdown: Path) -> list[tuple[int, dict]]:
    """YAML blocks that read as an environment file (they set ``name`` or ``include_dirs``)."""
    text = markdown.read_text(encoding="utf-8")
    blocks = []
    for match in _YAML_BLOCK.finditer(text):
        # The loader expands ${VAR} before validation; mirror that with a placeholder.
        expanded = _ENV_VAR.sub("placeholder", match.group(1))
        try:
            data = yaml.safe_load(expanded)
        except yaml.YAMLError:
            continue
        if isinstance(data, dict) and ({"name", "include_dirs", "database_url"} & data.keys()):
            if data.get("database_url") == "placeholder":
                data["database_url"] = PLACEHOLDER_DSN
            blocks.append((text[: match.start()].count("\n") + 1, data))
    return blocks


def test_every_example_readme_config_snippet_validates() -> None:
    """A README's environment snippets validate through the model — no legacy ``database:`` block."""
    files = _readme_files()
    assert len(files) >= MIN_README_FILES, "the examples lost their READMEs"
    failures: list[str] = []
    checked = 0
    for markdown in files:
        for line, data in _environment_blocks(markdown):
            checked += 1
            where = f"{markdown.relative_to(REPO_ROOT)}:{line}"
            if "database" in data:
                failures.append(
                    f"{where}: legacy `database:` block; the model reads `database_url`"
                )
                continue
            # A partial snippet (only `include_dirs`, say) is fine; the keys it sets must be real.
            data.setdefault("name", "snippet")
            data.setdefault("database_url", PLACEHOLDER_DSN)
            try:
                Environment.model_validate(data)
            except ValidationError as exc:
                failures.append(f"{where}: {exc}")
    assert checked > 0, "no environment snippet found in any example README"
    assert failures == [], "README snippets the model rejects:\n" + "\n".join(failures)
