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
from pathlib import Path, PurePath

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


# --------------------------------------------------------------------------
# The 1.4.0 selection, replayed so that a project can be told what changed.
#
# Quarantined here, called only by the migration diagnostic below, and deleted
# in 1.6.0 together with that diagnostic — see issue #263.
# --------------------------------------------------------------------------


def _legacy_include_patterns(include: list[str], *, recursive: bool) -> list[str]:
    """The patterns 1.4.0 actually globbed with.

    A non-recursive entry carrying the default include had it rewritten behind
    the user's back, to stop ``glob("**/*.sql")`` from recursing. A replay that
    skipped the rewrite would report a change where there was none.
    """
    if include == ["**/*.sql"] and not recursive:
        return ["*.sql"]
    return include


def _legacy_include_sets(
    directory: Path, include: list[str], *, recursive: bool
) -> dict[str, set[Path]]:
    """Which files each written include pattern selected under 1.4.0."""
    used = _legacy_include_patterns(include, recursive=recursive)
    sets: dict[str, set[Path]] = {}
    for written, pattern in zip(include, used, strict=True):
        walker = directory.rglob if recursive else directory.glob
        sets[written] = {path for path in walker(pattern) if path.is_file()}
    return sets


def _legacy_exclude_sets(
    directory: Path, exclude: list[str], candidates: set[Path]
) -> dict[str, set[Path]]:
    """Which of *candidates* each exclude pattern removed under 1.4.0."""
    return {
        pattern: {path for path in candidates if path.relative_to(directory).match(pattern)}
        for pattern in exclude
    }


def can_have_changed(include: list[str], exclude: list[str]) -> bool:
    """Whether any configured pattern can mean something different in 1.5.0.

    A pattern carrying no ``/`` matched the filename at any depth under
    ``PurePath.match`` and still does, and ``rglob``/``glob`` gave it the same
    reach — so a config written entirely in such patterns cannot have changed,
    and does not pay for the replay.
    """
    return any("/" in pattern for pattern in (*include, *exclude))


def _names(paths: set[Path], directory: Path, limit: int = 3) -> str:
    """*paths* as a readable list relative to *directory*, truncated when long."""
    relative = sorted(path.relative_to(directory).as_posix() for path in paths)
    if len(relative) > limit:
        return ", ".join(relative[:limit]) + f", … ({len(relative) - limit} more)"
    return ", ".join(relative)


def _restoring_rewrite(pattern: str, before: set[Path], directory: Path, walked: list[Path]) -> str:
    """``**/`` + *pattern* when that selects exactly what *pattern* used to, else ``""``."""
    candidate = f"**/{pattern.lstrip('/')}"
    restored = {path for path in walked if matches(path.relative_to(directory), candidate)}
    return candidate if restored == before else ""


_VERBS = {"include": ("selects", "excludes"), "exclude": ("excludes", "selects")}


def _note(
    kind: str,
    pattern: str,
    before: set[Path],
    after: set[Path],
    directory: Path,
    walked: list[Path],
) -> tuple[str, str, str] | None:
    """One ``(code, pattern, message)`` for a pattern whose match set moved."""
    if before == after:
        return None
    verb = _VERBS[kind][0]
    if before and not after:
        rewrite = _restoring_rewrite(pattern, before, directory, walked)
        hint = f"; write '{rewrite}' to keep the old meaning" if rewrite else ""
        return (
            "CONFIG_013",
            pattern,
            f"{kind} pattern '{pattern}' {verb} nothing now; before 1.5.0 it matched "
            f"{len(before)} file(s): {_names(before, directory)}{hint}",
        )
    clauses = []
    if gained := after - before:
        clauses.append(f"now {verb} {len(gained)} more file(s): {_names(gained, directory)}")
    if lost := before - after:
        clauses.append(f"no longer {verb} {len(lost)} file(s): {_names(lost, directory)}")
    return ("CONFIG_014", pattern, f"{kind} pattern '{pattern}' " + ", and ".join(clauses))


def migration_notes(
    directory: Path,
    walked: list[Path],
    *,
    recursive: bool,
    include: list[str],
    exclude: list[str],
) -> list[tuple[str, str, str]]:
    """``(code, pattern, message)`` for every pattern of this entry whose meaning moved.

    Args:
        directory: The include directory the patterns are relative to.
        walked: Every file under it that 1.5.0's walk found.
        recursive: The entry's ``recursive`` flag.
        include: The entry's include patterns, as written.
        exclude: The entry's exclude patterns, as written.

    Returns:
        One entry per changed pattern; empty when nothing can have changed.
    """
    if not can_have_changed(include, exclude):
        return []
    before_include = _legacy_include_sets(directory, include, recursive=recursive)
    after_include = {
        pattern: {path for path in walked if matches(path.relative_to(directory), pattern)}
        for pattern in include
    }
    before_exclude = _legacy_exclude_sets(
        directory, exclude, set().union(*before_include.values()) if before_include else set()
    )
    after_exclude = {
        pattern: {path for path in walked if matches(path.relative_to(directory), pattern)}
        for pattern in exclude
    }
    notes = [
        _note(kind, pattern, before[pattern], after[pattern], directory, walked)
        for kind, before, after in (
            ("include", before_include, after_include),
            ("exclude", before_exclude, after_exclude),
        )
        for pattern in before
    ]
    return [note for note in notes if note is not None]
