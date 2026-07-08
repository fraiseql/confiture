"""Unit tests for FunctionBodyNormalizer."""

from confiture.core.function_body_normalizer import FunctionBodyNormalizer

# ---------------------------------------------------------------------------
# Cycle 1: Line comment stripping
# ---------------------------------------------------------------------------


def test_strip_line_comment():
    norm = FunctionBodyNormalizer()
    body = "SELECT id -- primary key\nFROM users;"
    result = norm.normalize(body)
    assert "--" not in result
    assert "primary key" not in result
    assert "select id" in result
    assert "from users" in result


def test_strip_line_comment_preserves_string_content():
    """Content inside string literals that looks like a comment is kept."""
    norm = FunctionBodyNormalizer()
    body = "SELECT '-- not a comment' FROM t;"
    result = norm.normalize(body)
    assert "-- not a comment" in result


# ---------------------------------------------------------------------------
# Cycle 2: Block comment stripping
# ---------------------------------------------------------------------------


def test_strip_block_comment_single_line():
    norm = FunctionBodyNormalizer()
    result = norm.normalize("SELECT /* inline */ id FROM t;")
    assert "/*" not in result
    assert "inline" not in result
    assert "select" in result and "id" in result


def test_strip_block_comment_multiline():
    norm = FunctionBodyNormalizer()
    body = """
    /*
     * Computes the total price.
     * Used by billing module.
     */
    SELECT price * quantity FROM orders;
    """
    result = norm.normalize(body)
    assert "/*" not in result
    assert "computes" not in result
    assert "select price * quantity from orders;" in result


# ---------------------------------------------------------------------------
# Cycle 3: Hash determinism and collision resistance
# ---------------------------------------------------------------------------


def test_hash_body_deterministic():
    norm = FunctionBodyNormalizer()
    body = "SELECT 1;"
    assert norm.hash_body(body) == norm.hash_body(body)


def test_hash_body_length():
    norm = FunctionBodyNormalizer()
    h = norm.hash_body("SELECT 1;")
    assert len(h) == 12
    assert all(c in "0123456789abcdef" for c in h)


def test_hash_body_same_logic_same_hash():
    norm = FunctionBodyNormalizer()
    a = "-- find user\nSELECT id FROM users WHERE email = $1;"
    b = "select id from users where email = $1;"
    assert norm.hash_body(a) == norm.hash_body(b)


def test_hash_body_different_logic_different_hash():
    norm = FunctionBodyNormalizer()
    a = "SELECT id FROM users WHERE email = $1;"
    b = "SELECT id FROM accounts WHERE email = $1;"
    assert norm.hash_body(a) != norm.hash_body(b)


def test_hash_body_same_with_whitespace_variation():
    norm = FunctionBodyNormalizer()
    a = "SELECT   $1  +  1;"
    b = "SELECT $1 + 1;"
    assert norm.hash_body(a) == norm.hash_body(b)


def test_hash_body_same_with_case_variation():
    norm = FunctionBodyNormalizer()
    a = "SELECT $1 + 1;"
    b = "select $1 + 1;"
    assert norm.hash_body(a) == norm.hash_body(b)


# ---------------------------------------------------------------------------
# Cycle 4 (#177): normalize_for_diff — line-oriented normalisation
# ---------------------------------------------------------------------------


def test_normalize_for_diff_preserves_newlines():
    """Unlike normalize(), normalize_for_diff keeps line structure."""
    norm = FunctionBodyNormalizer()
    result = norm.normalize_for_diff("SELECT a\nFROM t\nWHERE x = 1;")
    assert result.splitlines() == ["select a", "from t", "where x = 1;"]


def test_normalize_for_diff_strips_comments_and_lowercases():
    norm = FunctionBodyNormalizer()
    result = norm.normalize_for_diff("-- header\nSELECT ID -- trailing\nFROM Users;")
    assert "header" not in result
    assert "trailing" not in result
    assert "--" not in result
    assert result.splitlines() == ["select id", "from users;"]


def test_normalize_for_diff_collapses_indentation_and_blank_lines():
    """Leading indentation, internal runs, and blank lines must not add diff noise."""
    norm = FunctionBodyNormalizer()
    a = norm.normalize_for_diff("SELECT   a,\n    b\nFROM t;")
    b = norm.normalize_for_diff("SELECT a,\n\nb\nFROM t;")
    assert a == b == "select a,\nb\nfrom t;"


def test_normalize_for_diff_is_line_oriented_where_normalize_is_flat():
    """normalize() collapses to one line; normalize_for_diff does not."""
    norm = FunctionBodyNormalizer()
    body = "SELECT 1;\nSELECT 2;"
    assert "\n" not in norm.normalize(body)
    assert "\n" in norm.normalize_for_diff(body)
