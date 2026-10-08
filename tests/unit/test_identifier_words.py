"""The words of a name: one tokeniser, for every rule that matches a name by meaning."""

import pytest

from confiture.core.schema_identity import contains_words, identifier_words


@pytest.mark.parametrize(
    ("name", "words"),
    [
        ("smtp_passwd", ("smtp", "passwd")),
        ("stripeApiKey", ("stripe", "api", "key")),
        ("HTTPServer2Url", ("http", "server", "2", "url")),
        ("tokenizer", ("tokenizer",)),
        ("api_key", ("api", "key")),
        ("apikey", ("apikey",)),
        ("tb_user__old", ("tb", "user", "old")),
        ("010_create-table.sql", ("010", "create", "table", "sql")),
        ("", ()),
    ],
)
def test_a_name_splits_into_its_words(name: str, words: tuple[str, ...]) -> None:
    assert identifier_words(name) == words


@pytest.mark.parametrize(
    ("name", "words", "found"),
    [
        ("db_credential", ("credential",), True),
        ("access_token_hash", ("access", "token"), True),
        ("token_access", ("access", "token"), False),
        ("tokenizer", ("token",), False),
        ("lessons", ("ssn",), False),
        ("monkey", ("key",), False),
    ],
)
def test_words_are_matched_whole_and_in_order(
    name: str, words: tuple[str, ...], found: bool
) -> None:
    assert contains_words(name, words) is found
