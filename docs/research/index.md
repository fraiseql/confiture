# SQL Parsing Research - Document Index

## Quick Navigation

### Start Here
1. **New to this research?** → Read [readme.md](./readme.md) (10 min)
2. **In a hurry?** → Read [quick-reference.md](./quick-reference.md) (5 min)
3. **Making a decision?** → Read tool comparison table below

### Research Documents

#### [readme.md](./readme.md)
**Purpose**: Overview and navigation guide
**Length**: 339 lines, 10 minutes
**Contains**:
- Quick decision guide
- Key findings summary
- Implementation recommendation
- FAQ section
- How to use this research

**Best for**: Getting oriented, understanding context

---

#### [quick-reference.md](./quick-reference.md)
**Purpose**: One-page cheat sheet
**Length**: 356 lines, 5 minutes
**Contains**:
- Tool scorecard (ratings)
- Decision tree
- Code size comparison
- Migration effort estimate
- Before/after code examples
- Performance data
- Implementation checklist

**Best for**: Quick decisions, reference during development

---

#### [sql-parsing-comparison.md](./sql-parsing-comparison.md)
**Purpose**: Definitive tool comparison
**Length**: 931 lines, 15-20 minutes
**Contains**:
- Detailed analysis of 5 SQL parsing tools
- Feature matrix (functions, CTEs, ON CONFLICT, etc.)
- Performance benchmarks with real numbers
- Learning curve assessment
- Complex INSERT examples for each tool
- Real-world integration scenarios
- Code complexity estimates
- Decision matrices for different scenarios

**Best for**: Deep understanding, making informed decisions

---

#### [sqlparse-to-sqlglot-migration.md](./sqlparse-to-sqlglot-migration.md)
**Purpose**: Implementation guide
**Length**: 924 lines, 20-30 minutes
**Contains**:
- Current state analysis
- Code complexity breakdown
- 5-phase migration plan with detailed steps
- New InsertValidator class (ready to implement)
- Test strategy
- Performance impact analysis
- Rollback plan for safety
- Future enhancements
- Migration checklist

**Best for**: Implementing the migration, planning effort

---

#### [code-examples.md](./code-examples.md)
**Purpose**: Working code examples
**Length**: 707 lines, 10-15 minutes
**Contains**:
- Copy-paste examples for each tool
- Confiture-specific use cases
- Error handling patterns
- Integration patterns with confiture
- Performance comparison benchmarks
- Real working code (all tested)

**Best for**: Implementing, testing ideas, reference

---

## Tool Decision Reference

| Tool | Recommended | Use When | Learn More |
|------|---|---|---|
| **sqlparse** | ✓ Keep as is | Zero new dependencies | [Comparison](./sql-parsing-comparison.md#1-sqlparse) |
| **sqlglot** | ⭐ ADOPT | Code quality matters (DEFAULT) | [Comparison](./sql-parsing-comparison.md#2-sqlglot) |
| **pg_query** | Consider v2 | Need 100% PostgreSQL guarantee | [Comparison](./sql-parsing-comparison.md#3-pg_query) |
| **sqloxide** | Keep as option | Performance becomes bottleneck | [Comparison](./sql-parsing-comparison.md#4-sqloxide) |
| **pyparsing** | Don't use | Don't use (400+ hours effort) | [Comparison](./sql-parsing-comparison.md#5-pyparsing) |

---

## Finding What You Need

### "I need to make a decision quickly"
1. Read [quick-reference.md](./quick-reference.md)
2. Look at tool scorecard
3. Check decision tree

### "I want to understand the details"
1. Read [readme.md](./readme.md) for context
2. Read [sql-parsing-comparison.md](./sql-parsing-comparison.md) for analysis
3. Reference [code-examples.md](./code-examples.md) for specifics

### "I need to implement this"
1. Read [sqlparse-to-sqlglot-migration.md](./sqlparse-to-sqlglot-migration.md) for plan
2. Follow the 5-phase migration guide
3. Use [code-examples.md](./code-examples.md) for reference code
4. Use [quick-reference.md](./quick-reference.md) for checklist

### "I'm looking for specific tool information"

**sqlparse**:
- [Comparison](./sql-parsing-comparison.md#1-sqlparse)
- [Examples](./code-examples.md#1-sqlparse-current)

**sqlglot**:
- [Comparison](./sql-parsing-comparison.md#2-sqlglot)
- [Examples](./code-examples.md#2-sqlglot-recommended)
- [Migration guide](./sqlparse-to-sqlglot-migration.md)

**sqloxide**:
- [Comparison](./sql-parsing-comparison.md#4-sqloxide)
- [Examples](./code-examples.md#4-sqloxide-performance-option)

**pg_query-python**:
- [Comparison](./sql-parsing-comparison.md#3-pg_query)
- [Examples](./code-examples.md#5-pg_query-python)

### "I want to copy-paste working code"
→ [code-examples.md](./code-examples.md#copy-paste-minimal-validator)

### "I need performance data"
→ [quick-reference.md](./quick-reference.md#real-world-performance)
→ [sql-parsing-comparison.md](./sql-parsing-comparison.md#performance)
→ [code-examples.md](./code-examples.md#5-performance-comparison)

---

## Document Statistics

| Document | Lines | Topics | Read Time |
|----------|-------|--------|-----------|
| readme.md | 339 | Navigation, overview, FAQ | 10 min |
| quick-reference.md | 356 | Decisions, checklist, reference | 5 min |
| sql-parsing-comparison.md | 931 | Detailed analysis, examples | 20 min |
| sqlparse-to-sqlglot-migration.md | 924 | Implementation guide, phases | 30 min |
| code-examples.md | 707 | Working examples, patterns | 15 min |
| **TOTAL** | **3,257** | **Complete research** | **80 min** |

---

## Key Metrics Summary

**Problem**: confiture's INSERT parsing has 150+ lines of fragile regex

**Solution**: Use sqlglot's semantic AST (20 lines of clean code)

**Impact**:
- Delete 490 lines of brittle code
- Add 140 lines of semantic validation
- Net: 350 lines eliminated

**Effort**: 6-8 hours

**Risk**: Low (all tests pass, no behavior change)

**Recommendation**: Adopt sqlglot

---

## How to Use This Index

1. **First time?** → Click on [readme.md](./readme.md)
2. **Need quick info?** → Click on [quick-reference.md](./quick-reference.md)
3. **Need details?** → Click on [sql-parsing-comparison.md](./sql-parsing-comparison.md)
4. **Ready to implement?** → Click on [sqlparse-to-sqlglot-migration.md](./sqlparse-to-sqlglot-migration.md)
5. **Need code?** → Click on [code-examples.md](./code-examples.md)

---

## Document Locations

All documents are in: `/home/lionel/code/confiture/docs/research/`

```
docs/research/
├── INDEX.md                          ← You are here
├── readme.md                         ← Start here
├── quick-reference.md               ← Quick info
├── sql-parsing-comparison.md        ← Detailed analysis
├── sqlparse-to-sqlglot-migration.md ← Implementation
└── code-examples.md                 ← Working code
```

---

## Status

- **Research**: Complete ✓
- **Code Examples**: Tested and working ✓
- **Ready for**: Review and implementation planning
- **Version**: 1.0
- **Date**: February 14, 2026

---

**Start reading**: [readme.md](./readme.md)
