"""``sec_003``: a credential written as a literal in the tree (#427).

``sec_001`` checks column *names*. This is the other half: the *values* a seed
writes — a password in a seed file is in git history, in every developer's
database and in every environment that applies it. Rows are read by the one seed
reader (``INSERT … VALUES`` from the parse tree, ``COPY`` rows decoded), role
passwords from ``CREATE``/``ALTER ROLE``. A hash or an obvious placeholder is not
a finding, and a finding never repeats the secret it found.
"""

from __future__ import annotations

import pytest

from confiture.core.linting.rule_registry import LINT_RULES
from confiture.core.linting.schema_linter import SchemaLinter

_TABLES = """
CREATE SCHEMA app;
CREATE TABLE app.tb_user (id int PRIMARY KEY, email text, password text);
CREATE TABLE app.tb_api (id int PRIMARY KEY, name text, signing_key text, sort_key text);
"""


def _findings(sql: str):
    report = SchemaLinter(env="local").lint(_TABLES + sql)
    found = [*report.errors, *report.warnings, *report.info]
    return [v for v in found if v.rule_id == "sec_003"]


def test_a_plaintext_password_in_an_insert_is_a_finding() -> None:
    (finding,) = _findings(
        "INSERT INTO app.tb_user (id, email, password) VALUES (1, 'a@b.c', 'hunter22');\n"
    )

    assert finding.object_name == "app.tb_user.password[id=1]"
    assert finding.severity.value == "warning"
    assert finding.line_number == 5


def test_the_finding_never_repeats_the_secret() -> None:
    (finding,) = _findings(
        "INSERT INTO app.tb_user (id, email, password) VALUES (1, 'a@b.c', 'hunter22');\n"
    )

    assert "hunter22" not in f"{finding.message} {finding.object_name} {finding.suggested_fix}"


@pytest.mark.parametrize(
    "value",
    [
        "$2b$12$C6UzMDM.H6dfI/f/IKcEeO5kmbGJW.p3Ya0d4CUNFr8S2A6bCkUe6",
        "$argon2id$v=19$m=65536,t=3,p=4$c2FsdHNhbHQ$aGFzaGhhc2hoYXNo",
        "SCRAM-SHA-256$4096:c2FsdA==$c3RvcmVkS2V5$c2VydmVyS2V5",
        "md5" + "0" * 32,
    ],
    ids=["bcrypt", "argon2", "scram", "md5"],
)
def test_a_hash_is_not_plaintext(value: str) -> None:
    assert (
        _findings(f"INSERT INTO app.tb_user (id, email, password) VALUES (1, 'a', '{value}');\n")
        == []
    )


@pytest.mark.parametrize(
    "value", ["", "changeme", "<redacted>", "xxxxxx", "********", "{{ DB_PASSWORD }}"]
)
def test_an_obvious_placeholder_is_not_a_credential(value: str) -> None:
    assert (
        _findings(f"INSERT INTO app.tb_user (id, email, password) VALUES (1, 'a', '{value}');\n")
        == []
    )


def test_a_copy_row_is_read_and_named_by_its_own_line() -> None:
    (finding,) = _findings(
        "COPY app.tb_user (id, email, password) FROM stdin;\n"
        "1\ta@b.c\tchangeme\n"
        "2\tx@y.z\ts3cr3t-Pa55\n"
        "\\.\n"
    )

    assert finding.object_name == "app.tb_user.password[id=2]"
    assert finding.line_number == 7


def test_an_insert_without_a_column_list_uses_the_table_order() -> None:
    (finding,) = _findings("INSERT INTO app.tb_user VALUES (3, 'q@r.s', 'letmein99');\n")

    assert finding.object_name == "app.tb_user.password[id=3]"


def test_a_role_password_literal_is_a_finding() -> None:
    (finding,) = _findings("ALTER ROLE app_user PASSWORD 'hunter22';\n")

    assert finding.object_name == "role app_user"
    assert "hunter22" not in finding.message


@pytest.mark.parametrize(
    "clause", ["PASSWORD NULL", "PASSWORD 'SCRAM-SHA-256$4096:c2FsdA==$a2V5$c2Vydg=='", "LOGIN"]
)
def test_a_role_without_a_plaintext_password_is_not_a_finding(clause: str) -> None:
    assert _findings(f"CREATE ROLE app_reader {clause};\n") == []


def test_a_key_column_needs_a_high_entropy_value() -> None:
    findings = _findings(
        "INSERT INTO app.tb_api (id, name, signing_key, sort_key) VALUES "
        "(1, 'a', 'kP9x2QmZ7vL4tR8wB3nY6cJ1', 'by_name'),"
        "(2, 'b', 'by_date', 'kP9x2QmZ7vL4tR8wB3nY6cJ1');\n"
    )

    assert sorted(f.object_name for f in findings) == [
        "app.tb_api.signing_key[id=1]",
        "app.tb_api.sort_key[id=2]",
    ]


def test_a_uuid_in_a_key_column_is_an_identifier_not_a_secret() -> None:
    assert (
        _findings(
            "INSERT INTO app.tb_api (id, name, signing_key, sort_key) VALUES "
            "(1, 'a', NULL, '6f1c1f86-8a7d-4f0e-9d5b-3c2a1b0e9f7d');\n"
        )
        == []
    )


def test_a_documented_example_in_a_comment_is_not_a_statement() -> None:
    assert (
        _findings("-- INSERT INTO app.tb_user (id, email, password) VALUES (1, 'a', 'hunter22');\n")
        == []
    )


def test_sec_003_is_registered_default_on_at_warning() -> None:
    (rule,) = [r for r in LINT_RULES if r.code == "sec_003"]

    assert (rule.family, rule.severity, rule.default_on) == ("security", "warning", True)
