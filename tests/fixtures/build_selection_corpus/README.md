# Build-selection corpus

One minimal project per configuration shape whose build **changed in 1.5.0**, plus one control that
did not. `expected.json` records, for each:

- `before_1_5_0` — the selection and schema hash measured against a `v1.4.0` worktree;
- `since_1_5_0` — what this checkout selects, recomputed on every test run;
- `changed` — whether the two differ, asserted so a fixture cannot rot into a no-op.

`tests/unit/test_build_selection_corpus.py` runs it.

## Why it exists

The compatibility sweep over this repository's own environments and every example project covers 17
config files and 22 `include_dirs` entries, and **all 22 are plain strings** — not one sets `order`,
`include`, `exclude`, `recursive` or `auto_discover`. That sweep is a real regression net for the
default path and no evidence at all about a configuration at risk. This corpus is that evidence.

## The shapes

| project | what it exercises | changed |
|---|---|---|
| `distinct_order` | two entries at `order: 10` and `20` | ✅ order blocks decide |
| `overlapping_entries_unequal_order` | `db/schema` and `db/schema/10_tables` at different orders | ✅ built once, in the earlier block |
| `overlapping_entries_equal_order` | the same two entries, both at `order: 0` | ✅ built once, under the entry listed first |
| `duplicate_selecting_include` | `include: ["**/*.sql", "*.sql"]` | ✅ selected once |
| `path_shaped_exclude` | `exclude: ["temp/*.sql"]` | ✅ **grows** — left-anchoring un-excludes `a/temp/t2.sql` |
| `recursive_exclude` | `exclude: ["**/temp/**"]` | ✅ shrinks — a root-level `temp/` is now excluded |
| `non_recursive_depth_pattern` | `recursive: false` + `**/sub/*.sql` | ✅ selects nothing, and the build refuses |
| `slash_free_exclude` | `exclude: ["*.bak"]` | ❌ control — a `/`-free pattern cannot have changed |

`confiture build --list-files` is the tool for reading the selection a configuration produces:
`order` blocks, deduplication and overlap resolution are decided there, and nothing about a
pattern's spelling explains them.
