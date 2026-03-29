"""Two-pass FK extraction for cross-schema build ordering.

Extracts FOREIGN KEY constraints from CREATE TABLE statements and generates
corresponding ALTER TABLE ADD CONSTRAINT statements. This allows all tables
to be created first (pass 1), then all FK constraints added (pass 2),
eliminating cross-schema ordering failures.

See: https://github.com/evoludigit/confiture/issues/94
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ── Identifier pattern (bare or double-quoted, optionally schema-qualified) ──

_IDENT = r'(?:"[^"]+"|[A-Za-z_]\w*)'
_QUAL_IDENT = rf"{_IDENT}(?:\.{_IDENT})*"

# ── CREATE TABLE finder ─────────────────────────────────────────────────────

_CREATE_TABLE_RE = re.compile(
    rf"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?({_QUAL_IDENT})\s*\(",
    re.IGNORECASE,
)

# ── ON DELETE / ON UPDATE / DEFERRABLE modifiers ─────────────────────────────

_ON_DELETE_RE = re.compile(
    r"\s+ON\s+DELETE\s+(CASCADE|SET\s+NULL|SET\s+DEFAULT|RESTRICT|NO\s+ACTION)",
    re.IGNORECASE,
)
_ON_UPDATE_RE = re.compile(
    r"\s+ON\s+UPDATE\s+(CASCADE|SET\s+NULL|SET\s+DEFAULT|RESTRICT|NO\s+ACTION)",
    re.IGNORECASE,
)
_DEFERRABLE_RE = re.compile(
    r"\s+((?:NOT\s+)?DEFERRABLE(?:\s+INITIALLY\s+(?:DEFERRED|IMMEDIATE))?)",
    re.IGNORECASE,
)

# ── Inline REFERENCES (within a column definition line) ──────────────────────

_INLINE_REF_RE = re.compile(
    rf"(?:\s+CONSTRAINT\s+({_IDENT}))?"  # optional CONSTRAINT name
    rf"\s+REFERENCES\s+({_QUAL_IDENT})"  # REFERENCES target_table
    rf"(?:\s*\(([^)]+)\))?"  # optional (target_columns)
    rf"("  # begin modifiers capture group
    rf"(?:\s+ON\s+(?:DELETE|UPDATE)\s+(?:CASCADE|SET\s+NULL|SET\s+DEFAULT|RESTRICT|NO\s+ACTION))*"
    rf"(?:\s+(?:NOT\s+)?DEFERRABLE(?:\s+INITIALLY\s+(?:DEFERRED|IMMEDIATE))?)?"
    rf")",  # end modifiers
    re.IGNORECASE,
)

# ── Table-level FOREIGN KEY ─────────────────────────────────────────────────

_TABLE_FK_RE = re.compile(
    rf"(?:CONSTRAINT\s+({_IDENT})\s+)?"  # optional CONSTRAINT name
    rf"FOREIGN\s+KEY\s*\(([^)]+)\)"  # FOREIGN KEY (source_columns)
    rf"\s*REFERENCES\s+({_QUAL_IDENT})"  # REFERENCES target_table
    rf"\s*\(([^)]+)\)"  # (target_columns)
    rf"("  # begin modifiers
    rf"(?:\s+ON\s+(?:DELETE|UPDATE)\s+(?:CASCADE|SET\s+NULL|SET\s+DEFAULT|RESTRICT|NO\s+ACTION))*"
    rf"(?:\s+(?:NOT\s+)?DEFERRABLE(?:\s+INITIALLY\s+(?:DEFERRED|IMMEDIATE))?)?"
    rf")",  # end modifiers
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ForeignKeyInfo:
    """Represents an extracted foreign key constraint."""

    source_table: str
    source_columns: list[str] = field(default_factory=list)
    target_table: str = ""
    target_columns: list[str] = field(default_factory=list)
    constraint_name: str | None = None
    on_delete: str | None = None
    on_update: str | None = None
    deferrable: str | None = None


def _parse_modifiers(modifiers_text: str) -> tuple[str | None, str | None, str | None]:
    """Extract ON DELETE, ON UPDATE, DEFERRABLE from a modifier string."""
    on_delete = None
    on_update = None
    deferrable = None

    m = _ON_DELETE_RE.search(modifiers_text)
    if m:
        on_delete = m.group(1).upper()

    m = _ON_UPDATE_RE.search(modifiers_text)
    if m:
        on_update = m.group(1).upper()

    m = _DEFERRABLE_RE.search(modifiers_text)
    if m:
        deferrable = m.group(1).upper()

    return on_delete, on_update, deferrable


def _split_columns(cols: str) -> list[str]:
    """Split a comma-separated column list, trimming whitespace."""
    return [c.strip() for c in cols.split(",")]


def _strip_comments(line: str) -> str:
    """Strip line comments and block comments from a line for matching purposes."""
    # Remove block comments
    result = re.sub(r"/\*.*?\*/", "", line)
    # Remove line comments
    idx = result.find("--")
    if idx >= 0:
        result = result[:idx]
    return result


def _find_create_table_blocks(sql: str) -> list[tuple[int, int, str]]:
    """Find all CREATE TABLE blocks, tracking parenthesis nesting.

    Returns list of (start, end, table_name) tuples where start..end
    spans the full CREATE TABLE statement including the closing ;.
    """
    blocks = []
    for m in _CREATE_TABLE_RE.finditer(sql):
        table_name = m.group(1)
        depth = 1
        pos = m.end()
        in_line_comment = False
        in_block_comment = False
        in_string = False
        string_char = None

        while pos < len(sql) and depth > 0:
            ch = sql[pos]

            if in_line_comment:
                if ch == "\n":
                    in_line_comment = False
            elif in_block_comment:
                if ch == "*" and pos + 1 < len(sql) and sql[pos + 1] == "/":
                    in_block_comment = False
                    pos += 1
            elif in_string:
                if ch == string_char:
                    # Check for escaped quote ('' in SQL)
                    if ch == "'" and pos + 1 < len(sql) and sql[pos + 1] == "'":
                        pos += 1  # skip escaped quote
                    else:
                        in_string = False
            else:
                if ch == "-" and pos + 1 < len(sql) and sql[pos + 1] == "-":
                    in_line_comment = True
                    pos += 1
                elif ch == "/" and pos + 1 < len(sql) and sql[pos + 1] == "*":
                    in_block_comment = True
                    pos += 1
                elif ch in ("'",):
                    in_string = True
                    string_char = ch
                elif ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1

            pos += 1

        if depth == 0:
            # Find the semicolon after the closing paren
            end = pos
            while end < len(sql) and sql[end] in (" ", "\t", "\n", "\r"):
                end += 1
            if end < len(sql) and sql[end] == ";":
                end += 1
            blocks.append((m.start(), end, table_name))

    return blocks


def _extract_fks_from_body(body: str, table_name: str) -> tuple[str, list[ForeignKeyInfo]]:
    """Extract FK constraints from a CREATE TABLE body and return cleaned body + FK list."""
    fks: list[ForeignKeyInfo] = []
    lines = body.split("\n")
    new_lines: list[str] = []

    for line in lines:
        stripped_for_check = _strip_comments(line)

        # Check for table-level FOREIGN KEY
        table_fk_match = _TABLE_FK_RE.search(stripped_for_check)
        if table_fk_match:
            constraint_name = table_fk_match.group(1)
            source_cols = _split_columns(table_fk_match.group(2))
            target_table = table_fk_match.group(3)
            target_cols = _split_columns(table_fk_match.group(4))
            modifiers = table_fk_match.group(5) if table_fk_match.group(5) else ""
            on_delete, on_update, deferrable = _parse_modifiers(modifiers)

            fks.append(
                ForeignKeyInfo(
                    constraint_name=constraint_name,
                    source_table=table_name,
                    source_columns=source_cols,
                    target_table=target_table,
                    target_columns=target_cols,
                    on_delete=on_delete,
                    on_update=on_update,
                    deferrable=deferrable,
                )
            )
            # Remove this entire line (FK constraint line)
            continue

        # Check for inline REFERENCES
        inline_match = _INLINE_REF_RE.search(stripped_for_check)
        if inline_match:
            constraint_name = inline_match.group(1)
            target_table = inline_match.group(2)
            target_cols_raw = inline_match.group(3)
            modifiers = inline_match.group(4) if inline_match.group(4) else ""
            on_delete, on_update, deferrable = _parse_modifiers(modifiers)

            # Extract source column name from the beginning of this line
            col_match = re.match(
                rf"\s*({_IDENT})\s+",
                stripped_for_check,
            )
            source_col = col_match.group(1) if col_match else "unknown"

            target_cols = _split_columns(target_cols_raw) if target_cols_raw else [source_col]

            fks.append(
                ForeignKeyInfo(
                    constraint_name=constraint_name,
                    source_table=table_name,
                    source_columns=[source_col],
                    target_table=target_table,
                    target_columns=target_cols,
                    on_delete=on_delete,
                    on_update=on_update,
                    deferrable=deferrable,
                )
            )

            # Strip the REFERENCES clause (and optional preceding CONSTRAINT) from original line
            # We operate on the original line to preserve comments etc.
            cleaned = _INLINE_REF_RE.sub("", line)
            new_lines.append(cleaned)
            continue

        new_lines.append(line)

    # Clean up trailing commas: if the last non-empty content line before )
    # ends with a comma, remove it
    cleaned_body = "\n".join(new_lines)
    if fks:
        cleaned_body = _fix_trailing_commas(cleaned_body)

    return cleaned_body, fks


def _fix_trailing_commas(body: str) -> str:
    """Remove trailing comma before closing paren in CREATE TABLE body.

    After FK lines are removed, we may end up with:
        col BIGINT,
        <blank lines>

    This removes the trailing comma from the last non-blank line
    and cleans up blank lines at the end, but preserves a final newline.
    """
    lines = body.split("\n")

    # Remove blank lines at the end (from removed FK lines)
    while lines and not lines[-1].strip():
        lines.pop()

    # Find the last non-blank line and strip its trailing comma
    for i in range(len(lines) - 1, -1, -1):
        rstripped = lines[i].rstrip()
        if rstripped:
            if rstripped.endswith(","):
                lines[i] = rstripped[:-1]
            break

    # Restore trailing newline
    return "\n".join(lines) + "\n"


def extract_and_strip_fks(sql: str) -> tuple[str, list[ForeignKeyInfo]]:
    """Extract all FK constraints from CREATE TABLE statements.

    Returns a tuple of (modified_sql, list_of_fk_infos) where:
    - modified_sql has all FK constraints removed from CREATE TABLE bodies
    - list_of_fk_infos contains the extracted FK information

    Non-CREATE TABLE SQL (indexes, views, functions, etc.) is preserved unchanged.
    """
    blocks = _find_create_table_blocks(sql)

    if not blocks:
        return sql, []

    all_fks: list[ForeignKeyInfo] = []
    result_parts: list[str] = []
    prev_end = 0

    for start, end, table_name in blocks:
        # Add everything before this CREATE TABLE block
        result_parts.append(sql[prev_end:start])

        block_text = sql[start:end]

        # Find the opening paren position within the block
        paren_pos = block_text.index("(")
        # Find the body (everything between outer parens)
        header = block_text[: paren_pos + 1]

        # Re-find the closing paren by tracking depth
        depth = 1
        pos = paren_pos + 1
        in_line_comment = False
        in_block_comment = False
        in_string = False
        string_char = None

        while pos < len(block_text) and depth > 0:
            ch = block_text[pos]
            if in_line_comment:
                if ch == "\n":
                    in_line_comment = False
            elif in_block_comment:
                if ch == "*" and pos + 1 < len(block_text) and block_text[pos + 1] == "/":
                    in_block_comment = False
                    pos += 1
            elif in_string:
                if ch == string_char:
                    if ch == "'" and pos + 1 < len(block_text) and block_text[pos + 1] == "'":
                        pos += 1
                    else:
                        in_string = False
            else:
                if ch == "-" and pos + 1 < len(block_text) and block_text[pos + 1] == "-":
                    in_line_comment = True
                    pos += 1
                elif ch == "/" and pos + 1 < len(block_text) and block_text[pos + 1] == "*":
                    in_block_comment = True
                    pos += 1
                elif ch == "'":
                    in_string = True
                    string_char = ch
                elif ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
            pos += 1

        close_paren_pos = pos - 1
        body = block_text[paren_pos + 1 : close_paren_pos]
        footer = block_text[close_paren_pos:]

        cleaned_body, fks = _extract_fks_from_body(body, table_name)
        all_fks.extend(fks)

        result_parts.append(header + cleaned_body + footer)
        prev_end = end

    # Add remaining SQL after last CREATE TABLE block
    result_parts.append(sql[prev_end:])

    return "".join(result_parts), all_fks


def _bare_table_name(table_name: str) -> str:
    """Extract the bare table name without schema prefix or quotes.

    Examples:
        'crm.tb_order' -> 'tb_order'
        '"my_schema"."MyTable"' -> 'MyTable'
        'orders' -> 'orders'
    """
    # Take the last dot-separated part
    parts = table_name.split(".")
    name = parts[-1]
    # Remove quotes
    return name.strip('"')


def _bare_column_name(col_name: str) -> str:
    """Remove quotes from a column name."""
    return col_name.strip().strip('"')


def generate_alter_statements(fks: list[ForeignKeyInfo]) -> str:
    """Generate ALTER TABLE ADD CONSTRAINT statements for extracted FKs.

    Returns empty string if no FKs provided.
    """
    if not fks:
        return ""

    lines = [
        "-- ============================================",
        "-- Pass 2: Foreign Key Constraints",
        "-- ============================================",
        "",
    ]

    for fk in fks:
        # Determine constraint name
        if fk.constraint_name:
            name = fk.constraint_name
        else:
            bare_table = _bare_table_name(fk.source_table)
            bare_cols = "_".join(_bare_column_name(c) for c in fk.source_columns)
            name = f"{bare_table}_{bare_cols}_fkey"

        src_cols = ", ".join(fk.source_columns)
        tgt_cols = ", ".join(fk.target_columns)

        stmt = f"ALTER TABLE {fk.source_table}\n"
        stmt += f"    ADD CONSTRAINT {name}\n"
        stmt += f"    FOREIGN KEY ({src_cols}) REFERENCES {fk.target_table} ({tgt_cols})"

        if fk.on_delete:
            stmt += f"\n    ON DELETE {fk.on_delete}"
        if fk.on_update:
            stmt += f"\n    ON UPDATE {fk.on_update}"
        if fk.deferrable:
            stmt += f"\n    {fk.deferrable}"

        stmt += ";\n"
        lines.append(stmt)

    return "\n".join(lines)
