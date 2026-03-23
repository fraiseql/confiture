# COPY Format Loading - Documentation Index

> **New to COPY format?** Start with the [Quick Start](#quick-start) section below.

## 📚 Complete Documentation Suite

This documentation provides everything you need to understand and use PostgreSQL COPY format for fast seed loading in Confiture.

### Quick Start

**First time using COPY format?** Read these in order:

1. **[COPY Format Loading Guide](copy-format-loading.md)** (15 min read)
   - What is COPY format and why it's faster
   - Quick start examples
   - When to use COPY format
   - How to integrate into your workflow

2. **[Seed Loading Decision Tree](seed-loading-decision-tree.md)** (10 min read)
   - Choose the right strategy for your project
   - Decision flowchart
   - Performance expectations
   - Migration path from old approaches

3. **[Practical Examples](copy-format-examples.md)** (20 min read)
   - Real-world scenarios (8 detailed examples)
   - Docker integration
   - CI/CD pipelines
   - Troubleshooting

### Deep Dives

**Going deeper into specific topics:**

- **[COPY Format Loading Guide](copy-format-loading.md)**
  - Overview and philosophy
  - Quick start (3 approaches)
  - How it works (format conversion, escaping, transaction safety)
  - Use cases (fresh DB, large files, CI/CD, format conversion, performance analysis)
  - Advanced configuration
  - Converting INSERT to COPY
  - Troubleshooting
  - Performance tuning

- **[Seed Loading Decision Tree](seed-loading-decision-tree.md)**
  - 4 strategies (Concatenate, Sequential, Sequential+COPY, Pre-converted)
  - Decision matrix (data size vs approach)
  - Performance tiers and expectations
  - Migration path from old approaches

- **[Practical Examples](copy-format-examples.md)**
  - Scenario 1: Simple project (< 5K rows)
  - Scenario 2: Growing project (5-50K rows)
  - Scenario 3: CI/CD pipeline
  - Scenario 4: Converting existing seeds
  - Scenario 5: Production initialization
  - Scenario 6: Handling unconvertible files
  - Scenario 7: Docker deployment
  - Scenario 8: Large file optimization

### Related Documentation

- **[Sequential Seed Execution](sequential-seed-execution.md)**
  - Solves PostgreSQL's 650+ row parser limit
  - How savepoint isolation works
  - Configuration

- **[Seed Validation](seed-validation.md)**
  - Check seed data quality before loading
  - Validation patterns and fixes
  - Integration with COPY format

---

## 🎯 By Use Case

### "I have a small project"
→ **[COPY Format Loading: Decision Tree → Strategy A](seed-loading-decision-tree.md)**
- Use simple concatenation
- COPY format optional

### "I have 500+ row seed files"
→ **[Sequential Seed Execution](sequential-seed-execution.md)**
- Solves parser limit
- Combine with COPY for speed

### "I want maximum performance"
→ **[COPY Format Loading](copy-format-loading.md) + [Decision Tree → Strategy C](seed-loading-decision-tree.md)**
- Use Sequential + COPY format
- 2-10x faster

### "I need CI/CD integration"
→ **[Practical Examples → Scenario 3](copy-format-examples.md)**
- GitHub Actions workflow
- Docker integration
- Fast, reliable setup

### "I'm converting existing seeds"
→ **[Practical Examples → Scenario 4](copy-format-examples.md)**
- Step-by-step conversion guide
- Handling unconvertible files
- Before/after comparison

### "I'm optimizing a large project"
→ **[Practical Examples → Scenario 8](copy-format-examples.md)**
- Performance analysis
- File splitting strategies
- Tuning options

---

## 🔍 By Command

### `confiture seed apply`

**What it does:** Load seeds into the database

**With COPY format:**
```bash
confiture seed apply --sequential --copy-format --env local
```

**Documentation:**
- Quick start: [COPY Format Loading](copy-format-loading.md#quick-start)
- Full reference: [COPY Format Loading](copy-format-loading.md#use-cases)
- Examples: [Practical Examples](copy-format-examples.md)

### `confiture seed convert`

**What it does:** Transform INSERT statements to COPY format

```bash
confiture seed convert --input seeds.sql --output seeds_copy.sql
```

**Documentation:**
- Quick start: [COPY Format Loading](copy-format-loading.md#2-convert-insert-to-copy-format)
- Converting seeds: [COPY Format Loading](copy-format-loading.md#converting-insert-to-copy)
- Example scenarios: [Practical Examples → Scenario 4](copy-format-examples.md)

### `confiture seed benchmark`

**What it does:** Compare VALUES vs COPY performance

```bash
confiture seed benchmark --seeds-dir db/seeds
```

**Documentation:**
- Quick start: [COPY Format Loading](copy-format-loading.md#3-benchmark-performance)
- Performance analysis: [Seed Loading Decision Tree](seed-loading-decision-tree.md#performance-expectations)
- Example output: [Practical Examples → Scenario 2](copy-format-examples.md)

### `confiture build --copy-format`

**What it does:** Build schema and apply seeds with COPY format

```bash
confiture build --sequential --copy-format --database-url postgresql://localhost/myapp
```

**Documentation:**
- Quick start: [COPY Format Loading](copy-format-loading.md#4-full-integration-with-build)
- Strategy comparison: [Seed Loading Decision Tree](seed-loading-decision-tree.md)
- CI/CD example: [Practical Examples → Scenario 3](copy-format-examples.md)

---

## 📊 Decision Tree (Quick Reference)

```
How many rows total? ───────────────────────┐
│                                           │
├─ < 5,000 rows ─→ [Strategy A] Concatenate
├─ 5-50K rows ──→ [Strategy B] Sequential
├─ > 50K rows ──→ [Strategy C] Sequential + COPY ⭐
└─ (Very large) ─→ [Strategy D] Pre-converted COPY

👉 Read: Seed Loading Decision Tree for full details
```

---

## ⚡ Performance Summary

| Approach | Speed | Best For |
|----------|-------|----------|
| VALUES (concat) | Baseline | Dev, < 5K rows |
| VALUES (sequential) | Baseline | Dev, 5-50K rows |
| **COPY (sequential)** | **2-10x faster** | **Production, > 50K rows** |
| COPY (pre-converted) | **3-10x faster** | **CI/CD, very large data** |

👉 See actual numbers in [Practical Examples](copy-format-examples.md)

---

## 🚀 Getting Started Checklist

- [ ] **Read** [COPY Format Loading](copy-format-loading.md) (15 min)
- [ ] **Review** [Decision Tree](seed-loading-decision-tree.md) (10 min)
- [ ] **Pick your strategy** based on data size
- [ ] **Try it out:**
  ```bash
  confiture seed benchmark --seeds-dir db/seeds
  ```
- [ ] **If faster, use it:**
  ```bash
  confiture seed apply --sequential --copy-format --env local
  ```
- [ ] **Integrate into CI/CD** ([Example](copy-format-examples.md#scenario-3-cicd-pipeline))

---

## ❓ FAQ

### Q: Which guide should I read first?
**A:** Start with [COPY Format Loading](copy-format-loading.md). It answers most questions in one place.

### Q: How much faster is COPY?
**A:** Typically 2-10x faster for large datasets (50K+ rows). See [Performance Summary](#-performance-summary) and [Practical Examples](copy-format-examples.md#performance-comparison-across-scenarios).

### Q: Will COPY break my existing workflow?
**A:** No! COPY is completely optional. Existing workflows continue to work. Enable with `--copy-format` flag.

### Q: Can I use COPY with my custom SQL?
**A:** Most SQL patterns work. If not, Confiture gracefully skips the file (stays as INSERT). See [Handling Unconvertible Files](copy-format-loading.md#handling-unconvertible-patterns).

### Q: Should I store converted seeds in git?
**A:** Optional. Two approaches have tradeoffs:
- **Store INSERT**: Readable, easier to edit, convert on-demand
- **Store COPY**: Faster builds, easier CI/CD, less readable

See [Practical Examples → Strategy D](copy-format-examples.md#scenario-4-converting-existing-seeds) for comparison.

### Q: Is COPY safe?
**A:** Yes! Full ACID guarantees with savepoint isolation. See [How It Works](copy-format-loading.md#how-it-works).

### Q: What if something goes wrong?
**A:** See [Troubleshooting](copy-format-loading.md#troubleshooting) section in main guide.

---

## 🔗 Related Topics

Not seeing what you need? Check these related guides:

- **[Sequential Seed Execution](sequential-seed-execution.md)** - Solves 650+ row parser limit
- **[Seed Validation](seed-validation.md)** - Check seed quality before loading
- **[Build from DDL](01-build-from-ddl.md)** - Fresh database initialization
- **[Seed Validation Guide](seed-validation.md)** - Complete validation reference

---

## 📞 Getting Help

### CLI Help
All commands have built-in help:
```bash
confiture seed apply --help
confiture seed convert --help
confiture seed benchmark --help
confiture build --help
```

### Documentation Issues
Found a typo or confusing section?
👉 [GitHub Issues](https://github.com/evoludigit/confiture/issues)

---

## 📖 Document Versions

| Document | Purpose | Time | Audience |
|----------|---------|------|----------|
| [COPY Format Loading](copy-format-loading.md) | Complete guide | 20 min | Everyone |
| [Decision Tree](seed-loading-decision-tree.md) | Strategy selection | 10 min | Architects |
| [Practical Examples](copy-format-examples.md) | Real scenarios | 20 min | Developers |
| [Sequential Execution](sequential-seed-execution.md) | Parser limits | 15 min | Advanced users |
| [Seed Validation](seed-validation.md) | Quality checks | 15 min | Quality teams |

---

## 🎓 Learning Path

### Path 1: Quick Implementation
1. [COPY Format Loading](copy-format-loading.md#quick-start) - 5 min
2. Try a command: `confiture seed benchmark`
3. [Practical Examples](copy-format-examples.md) - 10 min

**Result:** Can use COPY format in 15 minutes

### Path 2: Strategic Planning
1. [COPY Format Loading](copy-format-loading.md) - 15 min
2. [Decision Tree](seed-loading-decision-tree.md) - 10 min
3. [Practical Examples](copy-format-examples.md) - 20 min

**Result:** Understand all strategies and tradeoffs

### Path 3: Deep Technical Understanding
1. [COPY Format Loading](copy-format-loading.md) - 20 min
2. [Sequential Execution](sequential-seed-execution.md) - 15 min
3. [Seed Validation](seed-validation.md) - 15 min
4. [Practical Examples](copy-format-examples.md) - 20 min

**Result:** Expert understanding of all features

---

## 📝 Last Updated

**Documentation created:** February 14, 2026
**COPY Format Phase:** Phase 12 (Complete)
**Test Coverage:** 205 tests passing
**Stability:** Production-ready

---

**👉 Ready to get started?**

1. **Quick learner:** Start with [Quick Start](copy-format-loading.md#quick-start) in main guide
2. **Decision maker:** Read [Seed Loading Decision Tree](seed-loading-decision-tree.md)
3. **Hands-on learner:** Check [Practical Examples](copy-format-examples.md)
