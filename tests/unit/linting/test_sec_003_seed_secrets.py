"""``sec_003``: a credential written as a literal in the tree (#427).

``sec_001`` checks column *names*. This is the other half: the *values* a seed
writes — a password in a seed file is in git history, in every developer's
database and in every environment that applies it. Rows are read by the one seed
reader (``INSERT … VALUES`` from the parse tree, ``COPY`` rows decoded), role
passwords from ``CREATE``/``ALTER ROLE``. A hash or an obvious placeholder is not
a finding, and a finding never repeats the secret it found.
"""

import pytest

from confiture.core.linting.rule_registry import LINT_RULES
from confiture.core.linting.schema_linter import SchemaLinter

_TABLES = """
CREATE SCHEMA app;
CREATE TABLE app.tb_user (id int PRIMARY KEY, email text, password text);
CREATE TABLE app.tb_api (id int PRIMARY KEY, name text, signing_key text, sort_key text);
"""

_LOGIN = "CREATE TABLE app.tb_login (password text, api_token text, note text);\n"


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


def test_a_row_is_never_named_by_another_secret() -> None:
    """Two secrets in one row: neither finding carries the other's value (#463)."""
    found = _findings(
        _LOGIN + "INSERT INTO app.tb_login (password, api_token) "
        "VALUES ('hunter2secret', 'tok_live_9f8a7s6d5f4g3h2j');\n"
    )

    assert sorted(f.object_name for f in found) == [
        "app.tb_login.api_token[row 1]",
        "app.tb_login.password[row 1]",
    ]


def test_a_row_is_never_named_by_a_key_shaped_value() -> None:
    """A column no rule flags can still hold a key; it does not name the row (#463)."""
    (finding,) = _findings(
        _LOGIN + "INSERT INTO app.tb_login (note, password) "
        "VALUES ('Zk8qP2vN7xR4tW9mB3cJ6hL1', 'hunter2secret');\n"
    )

    assert finding.object_name == "app.tb_login.password[row 1]"


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


_MAILBOX = "CREATE TABLE app.tb_mailbox (pk_mailbox bigint PRIMARY KEY, smtp_password text);\n"


def test_an_update_set_literal_is_a_finding_named_by_its_where_key() -> None:
    """#658: a seed that sets the credential in a second statement."""
    (finding,) = _findings(
        _MAILBOX
        + "UPDATE app.tb_mailbox SET smtp_password = 'Qe5Vb9Nw3Lz7Hk1Xs4Pd' WHERE pk_mailbox = 1;\n"
    )

    assert finding.object_name == "app.tb_mailbox.smtp_password[pk_mailbox=1]"
    assert finding.line_number == 6
    assert "Qe5Vb9Nw3Lz7Hk1Xs4Pd" not in f"{finding.message} {finding.suggested_fix}"


def test_an_update_without_a_where_key_is_named_by_its_line() -> None:
    (finding,) = _findings(
        _MAILBOX + "\nUPDATE app.tb_mailbox\n  SET smtp_password = 'Ua2Mf6Rk8Tc3Jn9Gy5Wq';\n"
    )

    assert finding.object_name == "app.tb_mailbox.smtp_password[line 7]"
    assert finding.line_number == 7


def test_an_on_conflict_do_update_set_literal_is_a_finding() -> None:
    found = _findings(
        _MAILBOX + "INSERT INTO app.tb_mailbox (pk_mailbox, smtp_password) VALUES (2, NULL)\n"
        "ON CONFLICT (pk_mailbox) DO UPDATE SET smtp_password = 'Fn3Wr7Jp1Ys5Dm9Ga2Xe';\n"
    )

    assert [(f.object_name, f.line_number) for f in found] == [
        ("app.tb_mailbox.smtp_password[line 6]", 6)
    ]


def test_the_issues_seed_reports_every_assignment() -> None:
    found = _findings(
        _MAILBOX
        + "INSERT INTO app.tb_mailbox (pk_mailbox, smtp_password) VALUES (1, 'Zc4Hx8Ld2Nv6Bq1Kt7Sm');\n"
        "UPDATE app.tb_mailbox SET smtp_password = 'Qe5Vb9Nw3Lz7Hk1Xs4Pd' WHERE pk_mailbox = 1;\n"
        "UPDATE app.tb_mailbox SET smtp_password = 'Ua2Mf6Rk8Tc3Jn9Gy5Wq';\n"
        "INSERT INTO app.tb_mailbox (pk_mailbox, smtp_password) VALUES (2, NULL)\n"
        "ON CONFLICT (pk_mailbox) DO UPDATE SET smtp_password = 'Fn3Wr7Jp1Ys5Dm9Ga2Xe';\n"
    )

    assert [f.line_number for f in found] == [6, 7, 8, 9]


@pytest.mark.parametrize(
    "assignment",
    [
        "smtp_password = 'changeme'",
        "smtp_password = '$2b$12$C6UzMDM.H6dfI/f/IKcEeO5kmbGJW.p3Ya0d4CUNFr8S2A6bCkUe6'",
        "smtp_password = NULL",
        "smtp_password = md5('x')",
        "smtp_password = excluded.smtp_password",
    ],
    ids=["placeholder", "hash", "null", "computed", "reference"],
)
def test_an_assignment_the_exemptions_cover_is_not_a_finding(assignment: str) -> None:
    assert _findings(_MAILBOX + f"UPDATE app.tb_mailbox SET {assignment};\n") == []


def test_a_multi_column_assignment_reads_each_value() -> None:
    (finding,) = _findings(
        _MAILBOX + "UPDATE app.tb_mailbox SET (pk_mailbox, smtp_password) "
        "= (3, 'Qe5Vb9Nw3Lz7Hk1Xs4Pd'::text) WHERE pk_mailbox = 3;\n"
    )

    assert finding.object_name == "app.tb_mailbox.smtp_password[pk_mailbox=3]"


def test_a_key_column_assignment_needs_a_high_entropy_value() -> None:
    found = _findings(
        "UPDATE app.tb_api SET sort_key = 'alpha' WHERE id = 1;\n"
        "UPDATE app.tb_api SET signing_key = 'Zk8qP2vN7xR4tW9mB3cJ6hL1' WHERE id = 2;\n"
    )

    assert [f.object_name for f in found] == ["app.tb_api.signing_key[id=2]"]


def test_a_where_key_that_is_a_secret_never_names_the_row() -> None:
    (finding,) = _findings(
        _LOGIN + "UPDATE app.tb_login SET password = 'hunter2secret' "
        "WHERE api_token = 'tok_live_9f8a7s6d5f4g3h2j';\n"
    )

    assert finding.object_name == "app.tb_login.password[line 6]"


def test_sec_003_is_registered_default_on_at_warning() -> None:
    (rule,) = [r for r in LINT_RULES if r.code == "sec_003"]

    assert (rule.family, rule.severity, rule.default_on) == ("security", "warning", True)
