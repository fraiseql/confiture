"""Generate PostgreSQL COPY format from seed data.

This module provides CopyFormatter to convert seed data into PostgreSQL's
efficient COPY format for bulk loading.
"""

from collections.abc import Collection, Iterator
from dataclasses import dataclass
from typing import Any


class CopyFormatter:
    r"""Generate PostgreSQL COPY format from seed data.

    Converts seed data (list of dicts) into PostgreSQL COPY format for
    efficient bulk loading. Handles:
    - NULL value representation (\N)
    - Special character escaping (backslash, newline, tab, etc.)
    - Multiple data types (UUID, numeric, string, boolean)
    - Column ordering preservation
    - Tab-separated values

    Example:
        >>> formatter = CopyFormatter()
        >>> rows = [
        ...     {"id": "1", "name": "Alice"},
        ...     {"id": "2", "name": "Bob"},
        ... ]
        >>> columns = ["id", "name"]
        >>> copy_format = formatter.format_table("users", rows, columns)
        >>> print(copy_format)
        COPY users (id, name) FROM stdin;
        1\tAlice
        2\tBob
        \.
    """

    def __init__(self) -> None:
        """Initialize the formatter."""
        pass

    def format_table(
        self,
        table_name: str,
        rows: list[dict[str, Any]],
        columns: list[str],
    ) -> str:
        """Format a table into PostgreSQL COPY format.

        Args:
            table_name: Name of the table
            rows: List of row dictionaries
            columns: Column names in order

        Returns:
            String in PostgreSQL COPY format
        """
        return self.format_rows(
            table_name, [[row.get(col) for col in columns] for row in rows], columns
        )

    def format_rows(self, table_name: str, rows: list[list[Any]], columns: list[str] | None) -> str:
        """Format positional rows into a COPY block.

        Args:
            table_name: Name of the table
            rows: Each row's values, in column order
            columns: The column list, or ``None`` for ``COPY t FROM stdin`` — every
                column of the table, in its order, as an ``INSERT`` without a list

        Returns:
            String in PostgreSQL COPY format
        """
        header = f"COPY {table_name} ({', '.join(columns)})" if columns else f"COPY {table_name}"
        lines = [f"{header} FROM stdin;"]
        lines.extend("\t".join(self._format_value(value) for value in row) for row in rows)

        # Add COPY terminator
        lines.append("\\.")

        return "\n".join(lines) + "\n"

    @staticmethod
    def _format_value(value: Any) -> str:
        """Format a single value for COPY format.

        Args:
            value: The value to format

        Returns:
            String representation for COPY format
        """
        if value is None:
            return "\\N"
        return copy_escape(str(value))


#: COPY's text format reads a backslash as an escape, and a tab, a newline and a
#: carriage return as the row's structure; ``\b`` and ``\f`` are escaped for a
#: reader's sake. Any other character — a vertical tab included — is data as it is.
_COPY_ESCAPES = str.maketrans(
    {"\\": "\\\\", "\t": "\\t", "\n": "\\n", "\r": "\\r", "\b": "\\b", "\f": "\\f"}
)


def copy_escape(text: str) -> str:
    """*text* as one field of COPY's text format reads it back: the one escaper."""
    return text.translate(_COPY_ESCAPES)


#: The letters COPY's text format reads after a backslash as a control character.
_COPY_LETTERS = {"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v"}
_OCTAL = "01234567"
_HEX = "0123456789abcdefABCDEF"


def _digits(field: str, start: int, alphabet: str, most: int) -> int:
    """The offset past the run of up to *most* characters of *alphabet* from *start*."""
    end = start
    while end < len(field) and end - start < most and field[end] in alphabet:
        end += 1
    return end


def copy_unescape(field: str) -> str:
    r"""One field of COPY's text format as PostgreSQL reads it: the one unescaper.

    ``\b \f \n \r \t \v`` are control characters; ``\`` and one to three octal
    digits, or ``\x`` and one or two hex digits, is a byte of the file's encoding
    (UTF-8), so ``\xc3\xa9`` is ``é``; a backslash before anything else is that
    character. The NULL marker is not decoded here — it is a whole raw field,
    which :func:`copy_row` compares before decoding.

    Raises:
        ValueError: the bytes the escapes spell are not UTF-8, which PostgreSQL
            refuses too.
    """
    if "\\" not in field:
        return field
    out = bytearray()
    i = 0
    while i < len(field):
        char = field[i]
        if char != "\\" or i + 1 == len(field):
            out += char.encode()
            i += 1
            continue
        after = field[i + 1]
        if after in _OCTAL:
            end = _digits(field, i + 1, _OCTAL, 3)
            out.append(int(field[i + 1 : end], 8) & 0xFF)
        elif after == "x" and _digits(field, i + 2, _HEX, 2) > i + 2:
            end = _digits(field, i + 2, _HEX, 2)
            out.append(int(field[i + 2 : end], 16))
        else:
            end = i + 2
            out += _COPY_LETTERS.get(after, after).encode()
        i = end
    try:
        return out.decode("utf-8")
    except UnicodeDecodeError as exc:
        msg = f"the escapes in {field!r} spell bytes that are not UTF-8: {exc.reason}"
        raise ValueError(msg) from exc


def copy_row(line: str, *, delimiter: str = "\t", null: str = "\\N") -> tuple[str | None, ...]:
    r"""One line of a text-format ``COPY … FROM stdin`` block, as the row PostgreSQL reads.

    The line is split on *delimiter* where it is not escaped, a field that is
    exactly *null* is ``None``, and every other field is :func:`copy_unescape`\d.
    A carriage return ending the line is the line's ending, not data.

    Raises:
        ValueError: as :func:`copy_unescape`.
    """
    line = line.removesuffix("\r")
    fields: list[str] = []
    start = i = 0
    while i < len(line):
        if line[i] == "\\":
            i += 2
            continue
        if line[i] == delimiter:
            fields.append(line[start:i])
            start = i + 1
        i += 1
    fields.append(line[start:])
    return tuple(None if raw == null else copy_unescape(raw) for raw in fields)


@dataclass(frozen=True)
class CsvOptions:
    """A CSV ``COPY``'s options, PostgreSQL's defaults where the statement gives none.

    ``escape`` is the quote unless given. ``header`` is ``True`` to skip the first
    row, ``"match"`` to require it to name ``columns`` in order. ``force_null`` and
    ``force_not_null`` hold column positions.
    """

    delimiter: str = ","
    quote: str = '"'
    escape: str | None = None
    null: str = ""
    header: bool | str = False
    columns: tuple[str, ...] | None = None
    force_null: frozenset[int] = frozenset()
    force_not_null: frozenset[int] = frozenset()


def copy_csv_rows(
    data: str, options: CsvOptions | None = None
) -> list[tuple[int, tuple[str | None, ...]]]:
    """The rows of a CSV-format ``COPY … FROM stdin`` block, as PostgreSQL reads them.

    *data* is the block's rows, read as one stream: a newline inside quotes is data,
    so a row is not a line. Each row comes with the index of the line it starts on.
    A field is NULL when it is unquoted and equal to the NULL string, or equal to it
    at all in a ``force_null`` column; a ``force_not_null`` column is never NULL.

    Raises:
        ValueError: a quoted field is not closed, or a header that must match does
            not; PostgreSQL refuses both.
    """
    opts = options or CsvOptions()
    delimiter, quote, null = opts.delimiter, opts.quote, opts.null
    header, columns = opts.header, opts.columns
    force_null, force_not_null = opts.force_null, opts.force_not_null
    escape = quote if opts.escape is None else opts.escape
    rows: list[tuple[int, tuple[str | None, ...]]] = []
    for line, fields in _csv_records(data, delimiter=delimiter, quote=quote, escape=escape):
        values = tuple(
            _csv_value(i, text, quoted, null, force_null, force_not_null)
            for i, (text, quoted) in enumerate(fields)
        )
        rows.append((line, values))
    if header and rows:
        (_, names), *rows = rows
        if header == "match" and columns is not None and tuple(names) != columns:
            raise ValueError(f"the header names {names!r}, not the column list {columns!r}")
    return rows


def _csv_value(
    index: int,
    text: str,
    quoted: bool,
    null: str,
    force_null: Collection[int],
    force_not_null: Collection[int],
) -> str | None:
    if index in force_not_null:
        return text
    if text == null and (not quoted or index in force_null):
        return None
    return text


def _csv_records(
    data: str, *, delimiter: str, quote: str, escape: str
) -> Iterator[tuple[int, list[tuple[str, bool]]]]:
    """Each record of *data*: the line it starts on, and its fields as ``(text, quoted)``."""
    line = start_line = 0
    fields: list[tuple[str, bool]] = []
    field: list[str] = []
    quoted = in_quote = False
    i = 0
    while i < len(data):
        char = data[i]
        if in_quote:
            if char == escape and i + 1 < len(data) and data[i + 1] in (escape, quote):
                field.append(data[i + 1])
                i += 2
                continue
            if char == quote:
                in_quote = False
            else:
                field.append(char)
                line += char == "\n"
            i += 1
            continue
        if char == quote:
            in_quote = quoted = True
        elif char == delimiter:
            fields.append(("".join(field), quoted))
            field, quoted = [], False
        elif char in "\r\n":
            fields.append(("".join(field), quoted))
            yield start_line, fields
            if char == "\r" and data[i + 1 : i + 2] == "\n":
                i += 1
            line += 1
            start_line = line
            fields, field, quoted = [], [], False
        else:
            field.append(char)
        i += 1
    if in_quote:
        raise ValueError(f"unterminated quoted field in the row starting on line {start_line + 1}")
    if field or fields or quoted:
        fields.append(("".join(field), quoted))
        yield start_line, fields
