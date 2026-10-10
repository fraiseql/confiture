"""The desired-state guide documents composition as the pipeline (#679).

A FraiseQL artifact is a fragment: it indexes relations the project authors.
Diffed alone against a database it is refused (``DIFFER_406``); composed into
the environment's tree through ``include_dirs`` it is one concurrent index. The
guide must say so, and must not show ``--from db --to <dir>`` as if a fragment
were a whole schema.
"""

import re
from pathlib import Path

GUIDE = Path(__file__).resolve().parents[3] / "docs" / "guides" / "desired-state.md"


def _pipeline() -> str:
    text = GUIDE.read_text()
    return text[
        text.index("## The pipeline") : text.index("\n## ", text.index("## The pipeline") + 1)
    ]


def test_the_pipeline_composes_through_include_dirs() -> None:
    pipeline = _pipeline()

    for needed in ("include_dirs", "order:", "auto_discover: false", "--to-env"):
        assert needed in pipeline, needed


def test_the_guide_names_every_code_the_pipeline_can_raise() -> None:
    text = GUIDE.read_text()

    for code in ("DIFFER_405", "DIFFER_406", "DIFFER_407"):
        assert code in text, code


def test_a_from_db_to_dir_example_is_for_a_whole_schema() -> None:
    text = GUIDE.read_text()

    for match in re.finditer(r"--from db --to (?!-)", text):
        nearby = text[max(0, match.start() - 600) : match.end() + 600]
        assert "whole" in nearby, nearby
