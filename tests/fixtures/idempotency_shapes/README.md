# Idempotency extractor shapes

One migration per argument shape the static extractor meets in the wild.
`tests/unit/idempotency/test_extractor_coverage.py` pins, for each file, how
many `execute`/`execute_file` calls resolve to SQL and which warning kinds the
rest produce. Widening the extractor is an edit to that table; narrowing it,
by any refactor, fails the table with the shape that regressed.

Every SQL statement here is idempotent, so a resolved call never produces a
violation — the table measures *reach*, not findings. The sibling file
`../idempotency_shapes_outside.sql` exists so the escape shape has a real
file to refuse.
