"""Every preflight issue code is in the codebook, at the severity the report gives it."""

import re
from pathlib import Path

from confiture.models.results import PFLIGHT_CODES

CODEBOOK = Path(__file__).parents[3] / "docs" / "reference" / "error-codes.md"
_ROW = re.compile(r"^\| `(PFLIGHT_[A-Z_]+)` \| (error|warning|info) \|", re.MULTILINE)


def test_every_preflight_code_has_a_codebook_row_at_its_severity() -> None:
    rows = dict(_ROW.findall(CODEBOOK.read_text(encoding="utf-8")))
    assert {code: severity for code, (severity, _) in PFLIGHT_CODES.items()} == {
        code: rows.get(code) for code in PFLIGHT_CODES
    }
