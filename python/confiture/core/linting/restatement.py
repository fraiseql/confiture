"""Does a ``COMMENT`` say anything the object's own name does not (#250)?

``doc_001``–``doc_004`` are satisfied by any comment, so a project driving the
documentation counter to zero is rewarded for writing ``'Deletes a widget'`` on
``delete_widget``. This is the narrowest band of that failure which is
mechanical rather than editorial, and the only one implemented: **every
meaningful word of the comment is already a word of the name.**

The bound the issue also offers — "shorter than 40 characters on an object with
more than one parameter" — is deliberately not implemented (D8). A short
accurate comment is common, so that rule would be wrong more often than right.

What is here is a heuristic and is wrong sometimes: a comment that is correct
*and* happens to restate the name is a false positive. It is why ``doc_005``
emits ``info``, is opt-in, and is documented as something to baseline rather
than to reword. Nothing in this module reads meaning; it compares strings.
"""

from __future__ import annotations

import re

#: Word characters, so punctuation and hyphens split rather than join:
#: ``'Soft-deletes'`` is ``soft`` and ``deletes``, and only one of them is in
#: ``delete_widget``.
_WORDS = re.compile(r"[a-z0-9]+")

#: Words a comment may use freely. They say nothing about the object, so their
#: presence must not save a comment from being read as a restatement — which is
#: the whole difference between ``'Deletes a widget'`` and ``'Deletes widget'``.
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "into",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "their",
        "then",
        "these",
        "this",
        "those",
        "to",
        "with",
    }
)

#: Endings an English verb or plural adds, longest first. Stripped from both
#: sides of the comparison so ``deletes``, ``deleting`` and ``deleted`` all meet
#: ``delete`` — a leading verb inflected is still the name's own word.
_SUFFIXES = ("ing", "es", "ed", "s")

#: What a stem may not shrink below. ``yes`` is not ``y`` and ``es`` is not an
#: inflection of anything; a two-letter stem matches far too much.
_MIN_STEM = 3

#: How many ``_``-separated parts a name needs before a comment is judged
#: against it. A one-word name gives a comment nothing to restate, so there is
#: nothing here to be right or wrong about, and the rule declines to guess.
_MIN_NAME_PARTS = 2


def _strip(word: str, ending: str) -> str | None:
    """*word* without *ending*, or ``None`` when that is not a stem worth having."""
    if not word.endswith(ending) or len(word) - len(ending) < _MIN_STEM:
        return None
    return word[: -len(ending)]


def _stem(word: str) -> str:
    """One spelling for a word and its inflections.

    Crude on purpose: strip the longest ending it has, then a silent ``e``, so
    ``delete`` and ``deletes`` both reach ``delet`` without a stemmer, a word
    list, or a dependency. Over-stemming would make two different words match;
    :data:`_MIN_STEM` is what keeps that to words nobody writes.
    """
    for ending in _SUFFIXES:
        stripped = _strip(word, ending)
        if stripped is not None:
            return _strip(stripped, "e") or stripped
    return _strip(word, "e") or word


def _name_stems(name: str) -> set[str]:
    return {_stem(part) for part in name.lower().split("_") if part}


def adds_nothing(comment: str, name: str) -> bool:
    """Whether every meaningful word of *comment* is already a word of *name*.

    Args:
        comment: The comment text, as written.
        name: The object's local name — ``delete_widget``, not
            ``app.delete_widget(uuid)``. A schema and a signature are not
            things a comment restates.

    Returns:
        True when the comment carries no word the name does not, and there was
        a name to compare against. False for a comment with nothing in it (an
        object with no documentation is ``doc_001``–``doc_004``'s finding, not
        this one) and for a one-word name.
    """
    stems = _name_stems(name)
    if len(stems) < _MIN_NAME_PARTS:
        return False
    words = [word for word in _WORDS.findall(comment.lower()) if word not in _STOPWORDS]
    return bool(words) and all(_stem(word) in stems for word in words)
