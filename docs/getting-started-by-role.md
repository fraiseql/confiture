# Getting Started by Role

**Choose your role to find the right starting point** for learning Confiture.

---

## 👶 First-Time Visitor (5 minutes)

### "What is Confiture? Should I use it?"

**Reading path**:
1. **[Why Confiture?](https://github.com/fraiseql/confiture/blob/main/README.md#why-confiture)** (2 min)
   - Understand the core philosophy: DDL-first vs migration history
   - Learn the performance advantage (50-700x faster)
   - See the key benefits

2. **[The Four Mediums](https://github.com/fraiseql/confiture/blob/main/README.md#the-four-mediums)** (2 min)
   - See the 4 strategies available
   - Understand when to use each

3. **[Quick decision](comparison-with-alembic.md#-decision-matrix)** (1 min)
   - Decide: Is Confiture right for me?

**Next**: If interested → Choose your role below

---

## 👨‍💻 Developer: Getting Started (20 minutes)

### "I want to use Confiture for my project"

**Reading path**:

1. **[Quick Start](getting-started.md)** (10 min)
   - Installation and first commands
   - Create your first project
   - Build your first database

2. **[Migration Decision Tree](guides/migration-decision-tree.md)** (5 min)
   - Flowchart to choose the right strategy
   - Understand when to use each medium

3. **Choose Your Medium** (5-10 min) - Read relevant guide:
   - **[Medium 1: Build from DDL](guides/01-build-from-ddl.md)** - Fresh databases
   - **[Medium 2: Incremental Migrations](guides/02-incremental-migrations.md)** - Simple ALTER changes
   - **[Medium 3: Production Data Sync](guides/03-production-sync.md)** - Copy production data locally
   - **[Medium 4: Zero-Downtime](guides/04-schema-to-schema.md)** - Large production changes

**Hands-on next**: Try one of these [Examples](https://github.com/fraiseql/confiture/tree/main/examples)

**Need help?** → See [Troubleshooting](troubleshooting.md)

---

## 🏗️ DevOps / Infrastructure Engineer (30 minutes)

### "I need production-ready migrations with zero downtime"

**Reading path**:

1. **[Why Confiture?](https://github.com/fraiseql/confiture/blob/main/README.md#why-confiture)** (3 min)
   - Understand the philosophy
   - Learn performance benefits

2. **[Architecture](https://github.com/fraiseql/confiture/blob/main/ARCHITECTURE.md)** (10 min)
   - How Confiture works internally
   - Safety and transaction handling
   - Error recovery

3. **[Zero-Downtime Migrations](guides/04-schema-to-schema.md)** (10 min)
   - Complete guide to FDW strategy
   - Real-world production scenario
   - Handling large tables

4. **[Performance Guide](performance.md)** (5 min)
   - Benchmarks and real-world numbers
   - Optimization techniques
   - Impact on CI/CD and deployments

5. **[Configuration Reference](reference/configuration.md)** (2 min)
   - Environment setup
   - Multi-database configuration

**Hands-on**: Try [Zero-Downtime Example](https://github.com/fraiseql/confiture/tree/main/examples/03-zero-downtime-migration)

**Deployment questions?** → Check [Medium 4 troubleshooting](guides/04-schema-to-schema.md#troubleshooting)

---

## 🔐 Security / Compliance Officer (20 minutes)

### "How does Confiture handle sensitive data?"

**Reading path**:

1. **[Production Data Sync](guides/03-production-sync.md)** (10 min)
   - How data is copied from production
   - PII anonymization explained
   - Safety mechanisms

2. **[Anonymization Guide](guides/anonymization.md)** (5 min)
   - Available anonymization strategies
   - Custom strategy extension
   - Data masking techniques

3. **[Security Considerations](security/)** (5 min)
   - Threat model
   - GDPR compliance
   - Safe seed data handling

**Questions?** → Review specific anonymization strategies in [Anonymization Guide](guides/anonymization.md)

---

## 🔬 Researcher / Architect (60 minutes)

### "I want to understand the design philosophy and compare approaches"

**Reading path**:

1. **[Why Confiture?](https://github.com/fraiseql/confiture/blob/main/README.md#why-confiture)** (10 min)
   - Understand DDL-first philosophy
   - Learn design principles
   - See core value proposition

2. **[Architecture](https://github.com/fraiseql/confiture/blob/main/ARCHITECTURE.md)** (15 min)
   - Deep dive into how Confiture works
   - Design decisions explained
   - Performance optimizations

3. **[Comparison with Alembic](comparison-with-alembic.md)** (20 min)
   - Philosophy comparison
   - Feature-by-feature analysis
   - Trade-offs and design decisions
   - Migration path if switching

4. **[The Four Mediums](https://github.com/fraiseql/confiture/blob/main/README.md#the-four-mediums)** (10 min)
   - Understand all 4 strategies
   - When to use each
   - Design rationale

5. **[Advanced Patterns](guides/advanced-patterns.md)** (5 min)
   - Extension points
   - Customization possibilities

**Next**: Contribute improvements or research paper

---

## 🎓 Advanced User: Mastering Confiture (30+ minutes)

### "I want to master advanced techniques and implement complex migrations"

**Reading path**:

1. **[Advanced Patterns](guides/advanced-patterns.md)** (15 min)
   - Custom anonymization strategies
   - Hook orchestration (all 6 phases)
   - Performance optimization
   - Complex migration scenarios
   - CQRS backfilling patterns

2. **[Anonymization Guide](guides/anonymization.md)** (10 min)
   - All built-in strategies
   - Creating custom strategies
   - Composition and chaining

3. **[Migration Hooks](guides/hooks.md)** (10 min)
   - Complete hook API reference
   - All 6 hook phases
   - Error handling

4. **[Examples](https://github.com/fraiseql/confiture/tree/main/examples)** (10+ min)
   - Study real-world implementations
   - Learn patterns and best practices

**Deep dive**: Pick a scenario and implement it

**Optimization questions?** → See [Performance Guide](performance.md)

---

## 🏃 Fast Track: "I Know What I Want!" (5 minutes)

### Use this site map to navigate directly

**By Task**:
- **"I need to build a fresh database"** → [Medium 1: Build from DDL](guides/01-build-from-ddl.md)
- **"I need to make simple schema changes"** → [Medium 2: Incremental](guides/02-incremental-migrations.md)
- **"I need to copy production data locally"** → [Medium 3: Production Sync](guides/03-production-sync.md)
- **"I need zero-downtime production migration"** → [Medium 4: Zero-Downtime](guides/04-schema-to-schema.md)
- **"I need to test migrations first"** → [Dry-Run Guide](guides/dry-run.md)
- **"I need custom logic"** → [Advanced Patterns](guides/advanced-patterns.md)

**By Topic**:
- **Getting started**: [Quick Start](getting-started.md)
- **Decision making**: [Decision Tree](guides/migration-decision-tree.md)
- **Comparing with Alembic**: [Comparison](comparison-with-alembic.md)
- **Performance**: [Performance Guide](performance.md)
- **All commands**: [CLI Reference](reference/cli.md)
- **Python API**: [API Reference](api/)
- **Examples**: [Examples](https://github.com/fraiseql/confiture/tree/main/examples)
- **Definitions**: [Glossary](glossary.md)

---

## 📋 Common Questions Answered

**Q: "I use Alembic. Should I switch?"**
→ Read [Comparison with Alembic](comparison-with-alembic.md#-decision-matrix)

**Q: "How fast is Confiture?"**
→ See [Performance Guide](performance.md) with real benchmarks

**Q: "How do I migrate from Alembic?"**
→ Follow [Migration Path](comparison-with-alembic.md#-migration-path-from-alembic)

**Q: "What about production deployments?"**
→ See [Medium 4: Zero-Downtime](guides/04-schema-to-schema.md)

**Q: "How do I handle sensitive data?"**
→ Read [Production Data Sync](guides/03-production-sync.md) and [Anonymization](guides/anonymization.md)

**Q: "I'm stuck on something..."**
→ Check [Troubleshooting](troubleshooting.md) or [Advanced Patterns](guides/advanced-patterns.md)

---

## 🗺️ Full Documentation Map

```
Getting Started
├─ [Quick Start](getting-started.md)
├─ [Getting Started by Role](getting-started-by-role.md) ← You are here
└─ [Glossary](glossary.md)

User Guides (Choose Your Medium)
├─ [Decision Tree](guides/migration-decision-tree.md)
├─ [Medium 1: Build from DDL](guides/01-build-from-ddl.md)
├─ [Medium 2: Incremental](guides/02-incremental-migrations.md)
├─ [Medium 3: Production Sync](guides/03-production-sync.md)
└─ [Medium 4: Zero-Downtime](guides/04-schema-to-schema.md)

Advanced Topics
├─ [Advanced Patterns](guides/advanced-patterns.md)
├─ [Comparison with Alembic](comparison-with-alembic.md)
├─ [Performance Guide](performance.md)
├─ [Dry-Run Guide](guides/dry-run.md)
├─ [Anonymization Guide](guides/anonymization.md)
├─ [Migration Hooks](guides/hooks.md)
└─ [Schema Linting](linting.md)

Reference
├─ [CLI Reference](reference/cli.md)
├─ [Configuration](reference/configuration.md)
└─ [API Reference](api/)

Help & Examples
├─ [Troubleshooting](troubleshooting.md)
├─ [Examples](https://github.com/fraiseql/confiture/tree/main/examples)
└─ [Architecture](https://github.com/fraiseql/confiture/blob/main/ARCHITECTURE.md)
```

---

## 🎯 Your Next Step

**Pick your role above and follow the reading path.**

Most developers need 20 minutes to get productive with Confiture.

---

*Last updated: January 17, 2026*
*Questions? Check [Glossary](glossary.md) for term definitions or [Troubleshooting](troubleshooting.md) for common issues.*
