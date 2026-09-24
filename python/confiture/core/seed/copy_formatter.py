"""Generate PostgreSQL COPY format from seed data.

This module provides CopyFormatter to convert seed data into PostgreSQL's
efficient COPY format for bulk loading.
"""

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
        lines = []

        # Add COPY header
        column_list = ", ".join(columns)
        lines.append(f"COPY {table_name} ({column_list}) FROM stdin;")

        # Add data rows
        for row in rows:
            values = []
            for col in columns:
                value = row.get(col)
                formatted = self._format_value(value)
                values.append(formatted)
            lines.append("\t".join(values))

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
