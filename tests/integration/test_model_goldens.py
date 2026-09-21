"""The schema model each example tree declares, pinned.

``inventory.build_model`` is the one representation every comparison of a DDL
tree is moving onto. What it holds for each tree — every column with both its
type identity and its spelling, every constraint wherever it was written, every
index with its method — is recorded here, so a change to what the model reads is
a visible edit to these files rather than a behaviour change found downstream.

Recorded by ``scripts/refresh_model_goldens.py --write --only model``; a refresh
names its reason in ``CHANGELOG.md`` under ``## [Unreleased]``.
"""

from __future__ import annotations

from test_diff_goldens import _explain, goldens


def test_model_goldens_are_recorded() -> None:
    assert goldens.recorded("model"), (
        "tests/fixtures/model_goldens/model/ is empty; record it with "
        "`uv run python scripts/refresh_model_goldens.py --write --only model`"
    )


def test_the_model_matches_its_goldens() -> None:
    live = goldens.model_goldens()
    on_disk = goldens.recorded("model")
    assert live == on_disk, (
        "the schema model changed. If deliberate, run "
        "`uv run python scripts/refresh_model_goldens.py --write --only model` and name "
        "the reason in CHANGELOG.md.\n" + _explain(live, on_disk)
    )
