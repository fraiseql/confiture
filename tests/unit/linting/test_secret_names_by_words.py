"""A credential column is recognised by its words, and a placeholder by its words (#560).

``sec_001`` and ``sec_003`` matched a column name by substring, so ``tokenizer``
was a token and ``lessons`` held an ``ssn``, while ``smtp_passwd`` and
``db_credential`` were nothing. A placeholder had to be one exact word, so
``'PLACEHOLDER-not-a-real-credential'`` was reported as a live secret.
"""

from __future__ import annotations

import pytest

from confiture.core.linting.schema_linter import SchemaLinter
from confiture.core.linting.seed_secrets import is_placeholder, secret_kind


@pytest.mark.parametrize(
    ("column", "kind"),
    [
        ("password", "password"),
        ("smtp_passwd", "password"),
        ("db_credential", "credential"),
        ("stripeApiKey", "API key"),
        ("apikey", "API key"),
        ("api_key", "API key"),
        ("client_secret", "secret"),
        ("access_token", "token"),
        ("credit_card_number", "credit card"),
        ("ssn", "social security number"),
        ("tokenizer", None),
        ("lessons", None),
        ("monkey", None),
        ("passport_number", None),
    ],
)
def test_a_column_is_named_for_a_secret_by_its_words(column: str, kind: str | None) -> None:
    assert secret_kind(column) == kind


@pytest.mark.parametrize(
    ("value", "placeholder"),
    [
        ("PLACEHOLDER-not-a-real-credential", True),
        ("test_password", True),
        ("test", True),
        ("changeme", True),
        ("my-example-secret", True),
        ("dummy_value", True),
        ("not-a-secret", True),
        ("testify123!", False),
        ("Tr0ub4dor&3", False),
        ("contest-winner-2024", False),
    ],
)
def test_a_placeholder_is_recognised_by_its_words(value: str, placeholder: bool) -> None:
    assert is_placeholder(value) is placeholder


def test_a_column_matching_two_kinds_is_one_finding() -> None:
    report = SchemaLinter(env="local").lint("CREATE TABLE app.tb_login (password_token text);\n")
    found = [v for v in [*report.errors, *report.warnings, *report.info] if v.rule_id == "sec_001"]
    assert len(found) == 1
    assert "password" in found[0].message and "token" in found[0].message
