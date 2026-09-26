"""A built bundle's header says what it can prove, so a plain ``diff`` works (#428).

The header carried the *source* fingerprint (``compute_hash``: the files and their
paths), which moved between confiture versions while the body did not, and a
timestamp that moved on every build — so every consumer dropped two header lines
by position. The header now carries the SHA-256 of the body it heads, and takes
its timestamp from ``SOURCE_DATE_EPOCH`` when set: two builds of one tree are
then byte-identical.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from tests.unit.test_build_selection_is_stable import golden_project

runner = CliRunner()
_BODY_HASH = re.compile(r"^-- Body SHA-256: ([0-9a-f]{64})$", re.MULTILINE)


def _build(project: Path, output: Path) -> bytes:
    result = runner.invoke(
        app, ["build", "--env", "local", "--project-dir", str(project), "--output", str(output)]
    )
    assert result.exit_code == 0, result.output
    return output.read_bytes()


def _split(bundle: bytes) -> tuple[str, bytes]:
    """The header (up to its closing rule and blank line) and the body after it."""
    text = bundle.decode("utf-8")
    closing = "-- ============================================\n\n"
    end = text.index(closing, len(closing)) + len(closing)
    return text[:end], bundle[len(text[:end].encode("utf-8")) :]


def test_the_header_carries_the_sha256_of_the_body_it_heads(tmp_path: Path) -> None:
    header, body = _split(_build(golden_project(tmp_path), tmp_path / "out.sql"))

    (claimed,) = _BODY_HASH.findall(header)
    assert claimed == hashlib.sha256(body).hexdigest()


def test_source_date_epoch_makes_two_builds_byte_identical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1790000000")
    project = golden_project(tmp_path)

    first = _build(project, tmp_path / "a.sql")
    second = _build(project, tmp_path / "b.sql")

    assert first == second
    assert b"-- Generated: 2026-09-21T" in first
