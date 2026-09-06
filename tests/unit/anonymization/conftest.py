"""Shared fixtures for the anonymization strategy tests.

The keyed strategies read ``ANONYMIZATION_SECRET`` and refuse to run without
it (D8). Every test here gets a fixed test secret so the strategies can be
exercised; a test about the *absence* of the secret deletes it explicitly.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _anonymization_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANONYMIZATION_SECRET", "unit-test-secret")
