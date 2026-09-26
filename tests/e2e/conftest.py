"""End-to-end test scaffolding: each module leaves the default ledger as it found it."""

import pytest
from tests.conftest import fail_if_ledger_left

# Each module leaves the default ledger empty: see `ledger_rows_left`.
_ledger_left_empty = pytest.fixture(autouse=True, scope="module")(fail_if_ledger_left)
