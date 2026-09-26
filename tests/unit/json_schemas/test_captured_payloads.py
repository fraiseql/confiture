"""Payloads captured from real ``--format json`` runs validate against their schemas.

A schema written by reading a dataclass agrees with that dataclass and nothing
else; these files were written by the commands themselves. They were captured
against PostgreSQL 18 with a one-migration project (``CREATE TABLE t``) — the seed
payloads with a seed file or two for ``t`` — by running each command with
``--format json`` and saving stdout unedited; the ``test-db`` payloads against a
scratch server database, the one-table ``db/schema/`` its template was built from,
and ``ram-setup`` run by a user who cannot hand the location to the server's OS
user. The ``bootstrap`` payloads come from a throwaway cluster whose initdb
superuser is not ``postgres`` (``REASSIGN OWNED BY postgres`` refuses the objects of
the one that is). The ``migrate fix-signatures`` payloads come from a project whose
``db/schema/`` declares ``app.total(bigint)`` against a database holding
``app.total(integer)`` (and, for ``--check-body``, another body); the ``migrate
generate`` payloads' absolute paths had the capture directory replaced with
``/tmp/project``, the one edit made. Recapture the same way when a payload changes
on purpose.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

REPO = Path(__file__).resolve().parents[3]
PAYLOADS = REPO / "tests" / "fixtures" / "payloads"
SCHEMAS = REPO / "python" / "confiture" / "schemas"

#: Captured payload → the schema its command publishes.
CAPTURED = {
    "migrate-up.json": "migrate-up.schema.json",
    "migrate-down.json": "migrate-down.schema.json",
    "migrate-reinit.json": "migrate-reinit.schema.json",
    "migrate-rebuild.json": "migrate-rebuild.schema.json",
    "migrate-rebuild-dry-run.json": "migrate-rebuild.schema.json",
    "test-db-clone.json": "test-db-clone.schema.json",
    "test-db-drop.json": "test-db-drop.schema.json",
    "test-db-drop-absent.json": "test-db-drop.schema.json",
    "test-db-list.json": "test-db-list.schema.json",
    "test-db-provision-template.json": "test-db-provision-template.schema.json",
    "test-db-prune.json": "test-db-prune.schema.json",
    "test-db-prune-none.json": "test-db-prune.schema.json",
    "test-db-ram-setup-action-required.json": "test-db-ram-setup.schema.json",
    "test-db-status.json": "test-db-status.schema.json",
    "test-db-status-absent.json": "test-db-status.schema.json",
    "test-db-status-stale.json": "test-db-status.schema.json",
    "schema-to-schema-setup.json": "migrate-schema-to-schema-setup.schema.json",
    "schema-to-schema-setup-skip-import.json": "migrate-schema-to-schema-setup.schema.json",
    "schema-to-schema-analyze.json": "migrate-schema-to-schema-analyze.schema.json",
    "schema-to-schema-migrate.json": "migrate-schema-to-schema-migrate.schema.json",
    "schema-to-schema-migrate-copy.json": "migrate-schema-to-schema-migrate.schema.json",
    "schema-to-schema-migrate-table.json": "migrate-schema-to-schema-migrate-table.schema.json",
    "schema-to-schema-verify.json": "migrate-schema-to-schema-verify.schema.json",
    "schema-to-schema-verify-mismatch.json": "migrate-schema-to-schema-verify.schema.json",
    "schema-to-schema-cleanup.json": "migrate-schema-to-schema-cleanup.schema.json",
    "seed-apply.json": "seed-apply.schema.json",
    "seed-apply-profile.json": "seed-apply.schema.json",
    "seed-apply-continue-on-error.json": "seed-apply.schema.json",
    "seed-generate.json": "seed-generate.schema.json",
    "seed-generate-refused.json": "seed-generate.schema.json",
    "migrate-apply-as.json": "migrate-apply-as.schema.json",
    "migrate-baseline.json": "migrate-baseline.schema.json",
    "migrate-baseline-dry-run.json": "migrate-baseline.schema.json",
    "migrate-baseline-already-applied.json": "migrate-baseline.schema.json",
    "migrate-baseline-from-db.json": "migrate-baseline.schema.json",
    "migrate-baseline-from-db-dry-run.json": "migrate-baseline.schema.json",
    "bootstrap-check-drift.json": "bootstrap.schema.json",
    "bootstrap-check-clean.json": "bootstrap.schema.json",
    "bootstrap-plan.json": "bootstrap.schema.json",
    "bootstrap-apply.json": "bootstrap.schema.json",
    "bootstrap-apply-nothing.json": "bootstrap.schema.json",
    "diff.json": "diff.schema.json",
    "diff-no-changes.json": "diff.schema.json",
    "install-helpers.json": "install-helpers.schema.json",
    "install-helpers-already-installed.json": "install-helpers.schema.json",
    "install-helpers-dry-run.json": "install-helpers.schema.json",
    "validate-profile.json": "validate-profile.schema.json",
    "debug-cte.json": "debug-cte.schema.json",
    "debug-cte-failed.json": "debug-cte.schema.json",
    "migrate-fix-signatures-plan.json": "migrate-fix-signatures.schema.json",
    "migrate-fix-signatures-applied.json": "migrate-fix-signatures.schema.json",
    "migrate-fix-signatures-clean.json": "migrate-fix-signatures.schema.json",
    "migrate-fix-signatures-check-body-plan.json": "migrate-fix-signatures.schema.json",
    "migrate-fix-signatures-check-body-applied.json": "migrate-fix-signatures.schema.json",
    "migrate-fix-signatures-check-body-clean.json": "migrate-fix-signatures.schema.json",
    "migrate-generate.json": "migrate-generate.schema.json",
    "migrate-generate-verbose-name-conflict.json": "migrate-generate.schema.json",
    "migrate-generate-dry-run.json": "migrate-generate.schema.json",
    "migrate-generate-generator.json": "migrate-generate.schema.json",
    "migrate-generate-generator-dry-run.json": "migrate-generate.schema.json",
}


def _validator(name: str) -> Draft202012Validator:
    registry = Registry().with_resources(
        (path.name, Resource.from_contents(json.loads(path.read_text()), DRAFT202012))
        for path in SCHEMAS.glob("*.schema.json")
    )
    return Draft202012Validator(json.loads((SCHEMAS / name).read_text()), registry=registry)


@pytest.mark.parametrize(("payload", "schema"), sorted(CAPTURED.items()))
def test_a_captured_payload_validates(payload: str, schema: str) -> None:
    errors = [
        e.message
        for e in _validator(schema).iter_errors(json.loads((PAYLOADS / payload).read_text()))
    ]

    assert errors == []


def test_every_captured_payload_is_checked() -> None:
    assert sorted(p.name for p in PAYLOADS.glob("*.json")) == sorted(CAPTURED)
