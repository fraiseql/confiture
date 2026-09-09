"""The one path matcher: does this path, relative to its include directory, match this glob?

The dialect is **gitignore's** — ``gitignore(5)``, and ``pathspec``'s
``gitwildmatch`` as a reference implementation — because that is what a reader
who writes ``**/temp/**`` in a configuration file means by it. Four rules, in
the order the translation applies them:

1. A pattern containing no ``/`` matches the file's **name**, at any depth. This
   is what keeps ``*.bak`` and ``*.sql`` working.
2. A pattern containing a ``/`` is matched against the whole relative path,
   **left-anchored**. A leading ``/`` is redundant and ignored; a trailing ``/``
   names a directory and takes everything beneath it.
3. ``**`` spans **zero or more** components, so ``**/*.sql`` selects a top-level
   ``x.sql`` as well as a nested one, and ``**/temp/**`` catches ``temp/x.sql``
   and ``a/b/temp/x.sql`` alike. Consecutive ``**`` are collapsed to one, so a
   translated pattern never contains a nested unbounded quantifier.
4. ``*`` and ``?`` never cross a ``/``; ``[abc]`` is a character class and
   ``[!abc]`` its negation; matching is case-sensitive and reads the POSIX
   spelling of the path, so the answer does not depend on the platform.

Until 1.5.0 exclusions were filtered with :meth:`pathlib.PurePath.match`, where
``**`` is a single component and matching is anchored at the *right* end — so
``**/*.bak`` did not exclude a ``.bak`` at the root of the include directory and
``temp/*.sql`` excluded one at any depth (issue #256).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache
from pathlib import PurePath

# A regex that cannot match: an empty pattern is ignored, as gitignore ignores
# a blank line, rather than raising from inside a build.
_MATCHES_NOTHING = re.compile("(?!)")


def _class_fragment(component: str, start: int) -> tuple[str, int] | None:
    """The regex for the ``[...]`` class opening at *start*, and the index after it.

    Args:
        component: One path component of the pattern.
        start: Index of the opening ``[``.

    Returns:
        ``(fragment, next_index)``, or None when the class is never closed — an
        unterminated ``[`` is a literal bracket, as it is in ``fnmatch``.
    """
    end = start + 1
    if end < len(component) and component[end] in "!^":
        end += 1
    if end < len(component) and component[end] == "]":
        end += 1
    while end < len(component) and component[end] != "]":
        end += 1
    if end >= len(component):
        return None
    body = component[start + 1 : end]
    if body.startswith("!"):
        body = "^" + body[1:]
    return f"[{body}]", end + 1


def _translate_component(component: str) -> str:
    """One component's glob as a regex fragment that cannot cross a ``/``."""
    fragments: list[str] = []
    index = 0
    while index < len(component):
        char = component[index]
        if char == "*":
            fragments.append("[^/]*")
        elif char == "?":
            fragments.append("[^/]")
        elif char == "[":
            klass = _class_fragment(component, index)
            if klass is not None:
                fragments.append(klass[0])
                index = klass[1]
                continue
            fragments.append(re.escape(char))
        else:
            fragments.append(re.escape(char))
        index += 1
    return "".join(fragments)


def _components(pattern: str) -> list[str]:
    """*pattern* as the components the translation walks, rules 1-3 applied."""
    text = pattern.strip().removeprefix("/")
    if not text:
        return []
    if text.endswith("/"):
        text += "**"
    if "/" not in text:
        text = f"**/{text}"
    collapsed: list[str] = []
    for component in text.split("/"):
        if component == "**" and collapsed and collapsed[-1] == "**":
            continue
        collapsed.append(component)
    return collapsed


@lru_cache(maxsize=512)
def compile_pattern(pattern: str) -> re.Pattern[str]:
    """*pattern* as a compiled regex over a ``/``-separated relative path.

    Args:
        pattern: A configured ``include`` or ``exclude`` glob.

    Returns:
        The compiled regex, cached, so the same pattern is translated once.
    """
    components = _components(pattern)
    if not components:
        return _MATCHES_NOTHING
    fragments: list[str] = []
    for index, component in enumerate(components):
        last = index == len(components) - 1
        if component == "**":
            fragments.append(".*" if last else "(?:[^/]+/)*")
            continue
        fragments.append(_translate_component(component))
        if not last:
            fragments.append("/")
    return re.compile("^" + "".join(fragments) + r"\Z")


def _posix(rel_path: PurePath | str) -> str:
    """*rel_path* spelled the one way the patterns are written."""
    return rel_path.as_posix() if isinstance(rel_path, PurePath) else str(rel_path)


def matches(rel_path: PurePath | str, pattern: str) -> bool:
    """Whether *rel_path*, relative to its include directory, matches *pattern*."""
    return compile_pattern(pattern).match(_posix(rel_path)) is not None


def matches_any(rel_path: PurePath | str, patterns: Iterable[str]) -> bool:
    """Whether *rel_path* matches any of *patterns* (false for an empty list)."""
    text = _posix(rel_path)
    return any(compile_pattern(pattern).match(text) is not None for pattern in patterns)
