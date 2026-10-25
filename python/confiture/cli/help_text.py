"""A command's help as paragraphs Rich can re-wrap: a sentence's line breaks removed (#751).

Typer keeps every line break of a docstring after its first paragraph, and Rich
then wraps inside each source line, so on a terminal narrower than the source a
sentence breaks twice: once where Rich wraps, once where the docstring did.
:func:`unwrap` joins the lines of a sentence and leaves alone what is laid out on
purpose — a heading, a list item, an example, a deeper indent, a ``\\b`` block,
anything after a form feed. :class:`UnwrappingGroup` applies it to every command
once, when Typer builds the tree, so ``--help``, ``CliRunner`` and the generated
reference read the same text.
"""

import inspect
import re
from typing import Any

from typer.core import TyperGroup

#: A list item, a pointer or a symbol-led line: its words start after the marker.
_ITEM = re.compile(r"(?:\d+[.)]?|[^\w\s`'\"(]+)\s")
#: An example command, or a ``Label: value`` line.
_LAID_OUT = re.compile(r"(?:confiture\s|[A-Z][\w-]*:\s)")
#: Two or more spaces between words: the line is aligned in columns.
_COLUMNS = re.compile(r"\S {2,}\S")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _text_column(line: str) -> int:
    """Where *line*'s words start: past its indent, and past a list marker or ``↳``."""
    item = _ITEM.match(line.lstrip(" "))
    return _indent(line) + (item.end() if item else 0)


def _starts_anew(line: str) -> bool:
    """Whether *line* begins something of its own rather than going on with a sentence."""
    text = line.strip()
    return (
        not text
        or bool(_ITEM.match(text) or _LAID_OUT.match(text) or _COLUMNS.search(text))
        or not (text[0].isalpha() or text[0] in "`'\"(")
    )


def _joins(previous: str, line: str) -> bool:
    """Whether *line* continues *previous*'s sentence: same text column, nothing new started."""
    return (
        bool(previous.strip())
        and _indent(line) == _text_column(previous)
        and not previous.rstrip().endswith((":", "\\"))
        and not _COLUMNS.search(previous.strip())
        and not _starts_anew(line)
    )


def _paragraph(paragraph: str) -> str:
    if paragraph.startswith("\b"):
        return paragraph
    lines: list[str] = []
    for line in paragraph.split("\n"):
        if lines and _joins(lines[-1], line):
            lines[-1] = f"{lines[-1].rstrip()} {line.strip()}"
        else:
            lines.append(line)
    return "\n".join(lines)


def unwrap(help_text: str) -> str:
    """*help_text* with each sentence's line breaks removed, everything laid out kept."""
    text = inspect.cleandoc(help_text)
    body, feed, tail = text.partition("\f")
    return "\n\n".join(_paragraph(p) for p in body.split("\n\n")) + feed + tail


def _unwrap_tree(command: Any) -> None:
    if command.help:
        command.help = unwrap(command.help)
    for sub in (getattr(command, "commands", None) or {}).values():
        _unwrap_tree(sub)


class UnwrappingGroup(TyperGroup):
    """The root group: every command below it has its help unwrapped once, as Typer builds it."""

    def __init__(self, **attrs: Any) -> None:
        super().__init__(**attrs)
        _unwrap_tree(self)
