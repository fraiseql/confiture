"""Normalise PostgreSQL function bodies for drift comparison.

Normalisation removes cosmetic differences (comments, whitespace, casing)
that are irrelevant to function logic, so only genuine body changes trigger
a drift report.
"""

from __future__ import annotations

import hashlib
import re


class FunctionBodyNormalizer:
    """Normalise a raw PostgreSQL function body string into a canonical form.

    Normalisation steps (in order):
    1. Strip block comments (/* … */)
    2. Strip line comments (-- …) outside string literals
    3. Collapse whitespace (including newlines) to a single space
    4. Lowercase all content

    String literals (single-quoted and dollar-quoted) are preserved verbatim
    so that changes inside quoted values are still detected as drift.
    """

    # Matches — in priority order — single-quoted string, dollar-quoted string,
    # line comment, block comment.  The dollar-quote tag is captured in group 1
    # so that the back-reference \1 can close the matching delimiter.
    _TOKENIZER = re.compile(
        r"'(?:[^'\\]|\\.)*'"  # single-quoted string (preserves content)
        r"|(\$[^$]*\$).*?\1"  # dollar-quoted string (group 1 = tag, e.g. $$ or $func$)
        r"|--[^\n]*"  # line comment — strip
        r"|/\*.*?\*/",  # block comment — strip
        re.DOTALL,
    )

    def _replace_token(self, m: re.Match[str]) -> str:
        text = m.group(0)
        if text.startswith("--") or text.startswith("/*"):
            return " "  # strip comments, replace with a space to avoid token merging
        return text  # preserve string literals unchanged

    def normalize(self, body: str) -> str:
        """Return a canonical, lowercased representation of *body*.

        Two bodies that differ only in comments, whitespace, or keyword casing
        will produce the same normalised string.  Bodies with different logic
        will produce different strings.
        """
        stripped = self._TOKENIZER.sub(self._replace_token, body)
        lowered = stripped.lower()
        collapsed = re.sub(r"\s+", " ", lowered).strip()
        return collapsed

    def hash_body(self, body: str) -> str:
        """Return a 12-character hex digest of the normalised *body*.

        Uses SHA-256 truncated to 12 hex characters.  The short digest is
        suitable for display in CLI output; it is not cryptographically secure
        but provides sufficient collision resistance for drift detection.
        """
        canonical = self.normalize(body)
        return hashlib.sha256(canonical.encode()).hexdigest()[:12]
