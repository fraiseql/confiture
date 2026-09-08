# Hexadecimal Sorting

**Intuitive file ordering for complex database schemas**

---

## Overview

Hexadecimal sorting orders files by the numeric value of their filename prefix
rather than by the string. It is useful for large schemas that need more than
nine top-level sections, or clearer visual separation between major sections.

```yaml
# db/environments/production.yaml
build:
  sort_mode: hex
```

The default is `alphabetical`, which sorts by the whole path as text.

---

## File naming convention

### Prefix format

```
{HH}_{description}.sql

Where:
- HH: hexadecimal digits, either case, carrying at least one decimal digit
- _:  underscore separator
- description: human-readable name
```

There is **no `0x` marker**. `x` is not a hexadecimal digit, so `0x0A_users.sql`
carries no prefix confiture can read and sorts as an unnumbered file. Write the
digits alone.

### Which base a prefix is read in

The base belongs to the **directory**, not to the filename: one hex-lettered
prefix among the siblings makes the whole group hexadecimal, and a group of
pure digits is decimal. This is the rule `confiture generate alloc` already uses
when it picks the next number, so a directory it numbers and a directory the
linter reads agree.

It matters for `tree_003`, which reports gaps: `0009` → `0010` is one step in a
decimal directory and seven in a hex one.

### Valid examples

```bash
00_extensions.sql        # 0   - Extensions
01_security.sql          # 1   - Security setup
0a_users.sql             # 10  - User domain
0b_posts.sql             # 11  - Content domain
14_views.sql             # 20  - Views
1e_functions.sql         # 30  - Functions
28_triggers.sql          # 40  - Triggers
ff_finalize.sql          # 255 - Final steps
```

`0A_users.sql` is the same number as `0a_users.sql`. `confiture generate alloc`
writes lower case.

### What is not a prefix

```bash
users.sql                # no prefix — sorts after every numbered sibling
0x0A_users.sql           # 'x' is not a hex digit; no prefix
gg_users.sql             # 'g' is not a hex digit; no prefix
add_column.sql           # every letter is a hex digit, but there is no
                         # decimal digit — a word, not a number
0Ausers.sql              # no underscore
```

The decimal-digit rule is what keeps `add_`, `face_`, `dead_` and `cafe_` out
of the numbering. Without it `add_column.sql` would sort as 2781.

---

## Ordering rules

The sort key reads the number on **every** path component — each directory's,
then the file's — and ends with the path itself:

1. within one directory, numbered entries come before unnumbered ones;
2. numbered entries sort by value, then by what follows the prefix;
3. unnumbered entries sort by name;
4. two entries a numbering cannot separate (`0001_x` and `001_x` are both 1)
   fall back to the path, so the order is total.

Being total is the point: a key that ties leaves the order to `Path.rglob`,
which returns the filesystem's order and differs between machines. A
`generate alloc`-shaped tree, where every directory restarts at `00001`, ties on
the filename alone.

```bash
# File order with sort_mode: hex
0a_core/00001_create.sql     # directory 10, file 1
0a_core/00002_index.sql      # directory 10, file 2
14_views/00001_create.sql    # directory 20
helpers/00001_create.sql     # unnumbered directory, after every numbered one
```

---

## Examples

### Basic schema organization

```bash
db/schema/
├── 00_extensions.sql
├── 01_security.sql
├── 0a_core_tables/
│   ├── 0a01_users.sql
│   ├── 0a02_posts.sql
│   └── 0a03_comments.sql
├── 14_views/
│   └── 1401_user_stats.sql
└── 1e_functions/
    └── 1e01_create_user.sql
```

A child's prefix continuing its parent's is one of the two idiomatic
conventions, and the one `confiture lint --select tree` checks — see
[`tree_006`](../reference/lint-rules.md#tree_006-the-convention-is-read-from-the-tree-not-assumed).

### Migration from decimal

```bash
# Before (decimal)
00_extensions.sql
10_tables.sql
20_views.sql

# After (hex — room to insert)
00_extensions.sql
0a_tables.sql
14_views.sql
# 0f_reports.sql now fits between tables and views
```

Renaming even one file to a hex-lettered prefix makes the whole directory
hexadecimal, so rename the directory's files together: `20_views.sql` is 32,
not 20, once `0a_tables.sql` sits beside it.

---

## Implementation details

### Sort algorithm

1. Decide each directory's base: hexadecimal if any sibling prefix carries a
   letter, decimal otherwise.
2. Key each path component: `(numbered?, value, remainder)`.
3. Append the path's own parts, so the key is total.
4. Sort.

The one definition of "prefix" lives in `confiture.core.tree_prefix` and is
imported by the builder, the `tree` lint rules, `generate alloc` and
`generate renumber` — four modules that used to answer the question three
different ways.

### Backward compatibility

- **Default**: alphabetical sorting.
- **Opt-in**: set `sort_mode: hex`.
- Hex sorting applies only when at least one file carries a numeric prefix;
  otherwise the build falls back to alphabetical.

---

## Checking the arrangement

`confiture lint --select tree` reports the shapes that quietly change the order
a numbering was supposed to fix: a prefix shared by two siblings, a prefix that
does not extend its parent's, an entry nobody numbered, and a status word in a
name the build reads. The family is opt-in; `--baseline` adopts it on a tree
that has never been checked.

---

## Troubleshooting

### Files not sorting as expected

1. Is `sort_mode: hex` set for the environment being built?
2. Does the prefix carry a decimal digit and no `0x`?
3. Does another file in the same directory carry a hex letter? That makes the
   directory hexadecimal, and `20_views.sql` becomes 32.
4. `confiture lint --select tree` names the entries whose numbering is
   ambiguous.

### Mixed environments

Different environments sorting differently means different `sort_mode`
settings. The schema hash is order-dependent, so the digests will differ too.

---

## See also

- **[Organizing SQL Files](../organizing-sql-files.md)** — complete file organization guide
- **[Lint rules: the `tree` family](../reference/lint-rules.md#the-tree-family-the-arrangement-that-decides-the-build-order)** — checking the arrangement
- **[Configuration Reference](../reference/configuration.md)** — build configuration options

---

*Hex sorting brings clarity to complex schemas — 255 categories instead of 9.* 🎯
