"""The one path matcher: gitignore's pattern dialect, over paths relative to an include dir.

``PurePath.match`` — what ``find_sql_files`` filtered exclusions with until
1.5.0 — treats ``**`` as a single component and anchors at the *right* end of
the path, so every pattern in the reference manual matched a different set of
files from the one its reader assumed. The table below is issue #256's own
measurement with the expected column rewritten to the semantics that ship, plus
the rows that pin each of the four rules.
"""

from __future__ import annotations

from pathlib import PurePath, PurePosixPath, PureWindowsPath

import pytest

from confiture.core.path_globs import compile_pattern, matches, matches_any

# (pattern, path relative to the include directory, matches under 1.5.0)
ISSUE_256_TABLE = [
    ("**/*.bak", "a/x.bak", True),
    # ``x.bak`` at the root of the include dir was built; ``**`` spans zero
    # components now, so it is excluded like every other ``.bak``.
    ("**/*.bak", "x.bak", True),
    ("**/temp/**", "a/temp/x.sql", True),
    ("**/temp/**", "temp/x.sql", True),
    # #256's table calls this one ❌; measured on 3.11.14 it is ✅ even under
    # ``PurePath.match`` — three components, anchored right. It is ✅ here too.
    ("**/temp/**", "a/b/temp/x.sql", True),
    ("vendor/**", "vendor/y.sql", True),
    ("vendor/**", "vendor/sub/y.sql", True),
]

# Rule 1: no ``/`` in the pattern → it matches the file's *name*, at any depth.
# This is what keeps ``*.bak`` and ``*.sql`` working and the change from being
# a mass regression.
RULE_1_NAME_AT_ANY_DEPTH = [
    ("*.bak", "x.bak", True),
    ("*.bak", "a/b/x.bak", True),
    ("*.sql", "a/b/c/x.sql", True),
    ("10_users.sql", "a/10_users.sql", True),
    ("*.bak", "x.sql", False),
]

# Rule 2: a ``/`` anywhere → the whole relative path, left-anchored.
RULE_2_LEFT_ANCHORED = [
    ("10_tables/*.sql", "10_tables/x.sql", True),
    ("10_tables/*.sql", "a/10_tables/x.sql", False),
    ("temp/*.sql", "temp/x.sql", True),
    ("temp/*.sql", "a/temp/x.sql", False),
    ("temp/", "temp/x.sql", True),
    ("temp/", "a/temp/x.sql", False),
]

# Rule 3: ``**`` spans **zero** or more components. The zero case is the whole
# reason the non-recursive include rewrite can be deleted.
RULE_3_SPANS_ZERO_OR_MORE = [
    ("**/*.sql", "x.sql", True),
    ("**/*.sql", "a/b/x.sql", True),
    ("a/**/b.sql", "a/b.sql", True),
    ("a/**/b.sql", "a/x/b.sql", True),
    ("a/**/b.sql", "a/x/y/b.sql", True),
    ("**", "x.sql", True),
    ("**", "a/b/x.sql", True),
]

# Rule 4: ``*`` and ``?`` never cross a ``/``; ``[abc]`` is a class; matching is
# case-sensitive.
RULE_4_CLASSES_AND_CASE = [
    ("a/*.sql", "a/b/x.sql", False),
    ("*/x.sql", "a/b/x.sql", False),
    ("1?_t.sql", "10_t.sql", True),
    ("a?b.sql", "a/b.sql", False),
    ("[ab]_t.sql", "b_t.sql", True),
    ("[ab]_t.sql", "c_t.sql", False),
    ("[!ab]_t.sql", "c_t.sql", True),
    ("*.SQL", "x.sql", False),
    ("x.sql", "X.SQL", False),
]


@pytest.mark.parametrize(
    ("pattern", "path", "expected"),
    ISSUE_256_TABLE
    + RULE_1_NAME_AT_ANY_DEPTH
    + RULE_2_LEFT_ANCHORED
    + RULE_3_SPANS_ZERO_OR_MORE
    + RULE_4_CLASSES_AND_CASE,
)
def test_the_dialect(pattern: str, path: str, expected: bool) -> None:
    assert matches(PurePosixPath(path), pattern) is expected


def test_an_empty_pattern_matches_nothing() -> None:
    """A blank entry is ignored, as gitignore ignores a blank line — not a crash."""
    assert matches(PurePosixPath("x.sql"), "") is False
    assert matches(PurePosixPath("x.sql"), "   ") is False


def test_matching_reads_the_posix_spelling() -> None:
    """The answer does not depend on how the platform spells a separator."""
    assert matches(PureWindowsPath(r"a\b\x.sql"), "a/b/*.sql") is True
    assert matches(PurePath("a/b/x.sql"), "a/b/*.sql") is True


def test_matches_any_is_the_or_of_the_patterns() -> None:
    assert matches_any(PurePosixPath("a/x.bak"), ["*.sql", "**/*.bak"]) is True
    assert matches_any(PurePosixPath("a/x.sql"), ["*.bak"]) is False
    assert matches_any(PurePosixPath("a/x.sql"), []) is False


def test_consecutive_globstars_collapse_to_one() -> None:
    """``**/**/**/*.sql`` compiles to ``**/*.sql``'s regex, so it cannot backtrack.

    Nested unbounded quantifiers over attacker-influenced input are the only
    way a glob translation becomes a denial of service; collapsing the runs
    means the translated regex never contains one.
    """
    collapsed = compile_pattern("**/" * 6 + "*.sql")

    assert collapsed.pattern == compile_pattern("**/*.sql").pattern
    assert matches(PurePosixPath("a/b/c/x.sql"), "**/" * 6 + "*.sql") is True


def test_a_pattern_is_compiled_once() -> None:
    """The same pattern hands back the same compiled object."""
    assert compile_pattern("**/*.sql") is compile_pattern("**/*.sql")
