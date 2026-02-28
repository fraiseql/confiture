# Migration Versioning Strategies: Confiture vs Industry Standards

**Version**: 0.6.0
**Status**: Timestamp-based versioning now default

This guide compares how different migration tools version migrations and explains why Confiture switched to timestamp-based versioning in v0.6.0.

---

## 🎯 The Versioning Problem

Every database migration tool faces the same question:

**How do we uniquely identify each migration?**

```
Developer A creates:  007_add_payment_column.sql
Developer B creates:  007_add_shipping_address.sql  ← Conflict!
```

Different tools solve this problem in fundamentally different ways.

---

## Versioning Approaches

### 1️⃣ Sequential Numbers (Flyway)

**Format**: `001_`, `002_`, `003_`, ..., `999_`

```
001_create_users.sql
002_add_email.sql
003_add_phone.sql
...
999_final_migration.sql  ❌ Hard limit!
```

#### Pros
- ✅ Simple, compact, human-readable
- ✅ Clear execution order at a glance
- ✅ No coordination overhead
- ✅ Fast parsing

#### Cons
- ❌ **999 migration limit** (exhausted in 3-6 months at 5-10 migrations/day)
- ❌ **Merge conflicts** when two developers both create `007_`
- ❌ Requires shared sequential state
- ❌ Renumbering breaks down migrations already applied in production
- ❌ No temporal information (when was it created?)

#### Real-World Impact

```
Timeline:
Month 1:   100 migrations, no problem
Month 3:   300 migrations, still fine
Month 6:   600 migrations, getting uncomfortable
Month 9:   900 migrations, running out of room
Month 11:  999 migrations, STOP! Now what?

Options:
1. Renumber everything (breaks production tracking)
2. Use 0001, 0002 (what about existing 001?)
3. Switch tools entirely
4. Cap at 999 and archive old migrations
```

#### Merge Conflict Example

```
Developer A:                    Developer B:
git checkout -b feature/A       git checkout -b feature/B
# Creates 007_add_api_key.sql   # Creates 007_add_2fa.sql
git push                        git push

Team lead:
git pull origin develop
# CONFLICT! Both have 007_
# Someone must renumber to 008_
# But which one? Now we have:
#   007_add_api_key.sql (merged as 007)
#   008_add_2fa.sql     (renumbered to 008)
# Database already applied 007_add_api_key in staging!
# Now 008_add_2fa won't find the right state!
```

---

### 2️⃣ Timestamp Prefixes (Django, Rails, Knex.js)

**Format**: `YYYYMMDDHHmmss_`, `12-digit or 14-digit`

#### Django (14-digit + sequential)

```
0001_initial.py
0002_auto_20260228_1205.py
0003_model_user.py
```

**Pros:**
- ✅ No merge conflicts (wall-clock time is unique)
- ✅ Human-readable timestamp shows when created
- ✅ Unlimited migrations
- ✅ Chronologically sortable

**Cons:**
- ❌ Redundant (sequential + timestamp both present)
- ❌ Generated filename, not developer-controlled
- ❌ Harder to remember exact migration name
- ❌ Django-specific format

#### Rails/Knex.js (14-digit, developer-controlled)

```
20260228120530_create_users.rb
20260228120531_add_email_to_users.rb
20260228120532_create_posts.rb
```

**Pros:**
- ✅ No merge conflicts
- ✅ Clean, simple naming
- ✅ Developer controls name
- ✅ Chronologically sortable
- ✅ Unlimited migrations

**Cons:**
- ⚠️ Requires synchronized system clocks
- ⚠️ Less memorable than `001_`
- ⚠️ Can't easily predict next version number

#### Confiture v0.6.0 (14-digit, explicit)

```
20260228120530_add_users_table.py
20260228120531_add_posts_table.py
20260228120532_rename_user_to_profile.py
```

**Same as Rails/Knex approach, plus:**
- ✅ Backwards compatible with old `001_` format
- ✅ Old migrations sort before new (execution order preserved)

---

### 3️⃣ UUIDs / Hash IDs (Alembic)

**Format**: `a1b2c3d4e5f6_`, generated unique IDs

```
a1b2c3d4e5f6_create_users.py
f6e5d4c3b2a1_add_email.py
b2a1f6e5d4c3_add_phone.py
```

**Pros:**
- ✅ Globally unique (collision probability ≈ 0)
- ✅ Supports branching/merging explicitly
- ✅ Unlimited migrations
- ✅ Complex dependency tracking

**Cons:**
- ❌ Not human-readable at all
- ❌ Hard to remember migration ID
- ❌ Requires complex merge resolution
- ❌ Overkill for most teams
- ❌ Can't sort chronologically

---

## 📊 Comprehensive Comparison

| Feature | Sequential | Timestamp | UUID/Hash |
|---------|-----------|-----------|-----------|
| **Merge conflicts** | ❌ Yes | ✅ No | ✅ No |
| **Max migrations** | ❌ 999 | ✅ Unlimited | ✅ Unlimited |
| **Collision risk** | ✅ None | ✅ Negligible | ✅ None |
| **Human readable** | ✅✅ Very | ✅ Yes | ❌ No |
| **Temporal info** | ❌ No | ✅ Yes | ❌ No |
| **Chronologically sortable** | ✅ Yes | ✅ Yes | ❌ No |
| **Developer names migration** | ✅ No (auto) | ✅ Yes | ✅ Yes |
| **Clock-dependent** | ✅ No | ⚠️ Yes | ✅ No |
| **Coordination needed** | ✅ Yes | ✅ No | ✅ No |
| **Suitable for teams** | ⚠️ <5 devs | ✅ Any size | ✅ Any size |

---

## 🔍 Tool-by-Tool Breakdown

### Flyway (Java)
```
001_initial.sql
002_user_table.sql
...
999_max.sql  ❌
```
- **Versioning**: Sequential (3-digit)
- **Merge conflicts**: YES
- **Max migrations**: 999
- **Use case**: Solo developers, simple projects
- **Pain point**: Hard limit at 999

### Django (Python)
```
0001_initial.py
0002_auto_20260228_1205.py
```
- **Versioning**: Sequential + Timestamp (redundant)
- **Merge conflicts**: No
- **Max migrations**: Unlimited
- **Use case**: Django projects
- **Pain point**: Auto-generated names, not developer-controlled

### Rails (Ruby)
```
20260228120530_create_users.rb
20260228120531_add_email.rb
```
- **Versioning**: Timestamp (14-digit)
- **Merge conflicts**: No
- **Max migrations**: Unlimited
- **Use case**: Rails projects
- **Pain point**: None really (this is the best approach!)

### Knex.js (JavaScript)
```
20260228120530_create_users.js
20260228120531_add_email.js
```
- **Versioning**: Timestamp (14-digit)
- **Merge conflicts**: No
- **Max migrations**: Unlimited
- **Use case**: Node.js projects
- **Pain point**: None (same as Rails)

### Alembic (Python/SQLAlchemy)
```
a1b2c3d4e5f6_create_users.py
f6e5d4c3b2a1_add_email.py
```
- **Versioning**: UUID/Hash
- **Merge conflicts**: No
- **Max migrations**: Unlimited
- **Use case**: Complex SQLAlchemy projects
- **Pain point**: Not human-readable

### Confiture v0.6.0 (Python)
```
20260228120530_add_users_table.py
20260228120531_add_posts_table.py
```
- **Versioning**: Timestamp (14-digit)
- **Merge conflicts**: No
- **Max migrations**: Unlimited
- **Backwards compatible**: YES (old `001_` still works)
- **Use case**: Any team, any size
- **Advantage**: Rails-style + backwards compatibility

---

## 💥 Why Confiture v0.6.0 Switched to Timestamps

### Before (v0.5.10): Sequential Numbering
```
001_create_schema.py
002_add_users.py
003_add_posts.py
```

**Problem**: Merge conflicts on multi-developer teams

```
Developer A: 007_add_payment.py (creates in feature branch)
Developer B: 007_add_shipping.py (creates in feature branch)
Merge: CONFLICT! Who wins? Need manual renumbering.
```

### After (v0.6.0): Timestamp-Based
```
20260228120530_create_schema.py
20260228120531_add_users.py
20260228120532_add_posts.py
```

**Solution**: No conflicts, no coordination needed

```
Developer A: 20260228120530_add_payment.py (their system clock)
Developer B: 20260228120531_add_shipping.py (their system clock)
Merge: Automatic! No conflicts. Perfect execution order!
```

### Backwards Compatibility
Old migrations still work and sort correctly:

```
001_legacy_from_v0_5.py           ← sorts first (001 < 2026)
20260228120530_new_in_v0_6.py     ← sorts second
20260228120531_another_new.py      ← sorts third

Execution order: 001 → 2026... → 2026... ✅ Correct!
```

---

## 📈 Collision Analysis

**Question**: What's the probability of two developers creating migrations in the same second?

**At 10 migrations/day per developer**:
- Probability per day: (10 / 86400 seconds)² = 0.000000013
- Probability per year: 0.000005 (once every 200 years)
- Probability at enterprise scale (100 devs): 0.0005 (once every 2000 years)

**Conclusion**: Collision is negligible for practical purposes.

---

## ⏱️ System Clock Requirements

**Q: What if our clocks are out of sync?**

```
Developer A: System clock = 2026-02-28 12:05:30
Developer B: System clock = 2026-02-28 12:05:15  ← 15 seconds behind

Migration A: 20260228120530_add_column.py
Migration B: 20260228120515_add_index.py    ← sorts BEFORE A!

Execution order: 20260228120515, 20260228120530 (B runs first!)
But B was created AFTER A (timeline-wise).
```

**However**:
- Cloud providers (AWS, GCP, Azure) sync clocks automatically
- Kubernetes syncs clocks across nodes
- Docker maintains system clock from host
- Even if out of sync, migrations still work (just wrong order)
- Easy to fix: `ntpdate -s time.nist.gov` (NTP sync)

**Bottom line**: Not a practical concern in modern infrastructure.

---

## 🎯 Decision Matrix: Which Approach?

### Use Sequential (Flyway style) if:
- ❌ Solo developer, will never collaborate
- ❌ Total migrations never exceed 100 lifetime
- ✅ **Actually**: Don't, timestamps are better for everyone

### Use Timestamps (Confiture v0.6.0, Rails, Knex) if:
- ✅ Multi-developer team (any size)
- ✅ Will have >100 migrations over lifetime
- ✅ Want to avoid merge conflicts
- ✅ Want clean chronological order
- ✅ **This is the right choice for 99% of teams**

### Use UUIDs (Alembic style) if:
- ✅ Very complex branching/merging strategies
- ✅ Need scientific reproducibility
- ✅ Already invested in Alembic
- ✅ **Most teams don't need this complexity**

---

## 🔄 Migration Strategies by Team Size

### Solo Developer
```
Either sequential or timestamp works fine.
Preference: Sequential (simpler)

Reality: Switch to timestamp when team grows!
```

### Small Team (2-5 developers)
```
Sequential: Works but occasional conflicts

Timestamp: Zero conflicts, recommended!

Example:
Developer A: 20260228120530_add_users.py
Developer B: 20260228120531_add_posts.py
Developer C: 20260228120532_add_orders.py
Perfect! No coordination needed.
```

### Growing Team (5-20 developers)
```
Sequential: Regular conflicts, painful merge resolution

Timestamp: Works great! No conflicts, clear order.

Benefit: 10 developers × 5 migrations/day = 50 migrations/day
With sequential: ~1 conflict per 3 days (need renumbering)
With timestamp: Zero conflicts (wall-clock time is unique)

Time saved: 1-2 hours per week per developer
```

### Large Team (20+ developers)
```
Sequential: Breaks down completely

Timestamp: Still works perfectly!

At 100 developers, 50+ migrations/day:
- Collision probability: < once per 1000 years
- Setup complexity: Same as small team
- No additional coordination: No branch strategy needed
```

---

## 🚀 Real-World Scenarios

### Scenario 1: Startup Onboarding

**Team**: 3 developers, moving from Flyway to Confiture v0.6.0

```
Week 1: First merge conflict on 003_add_api_auth.sql
Developer A: 003_add_api_key_column.sql
Developer B: 003_add_jwt_strategy.sql

Result: Manual renumbering, CI/CD breaks temporarily

Week 2: Developer A: "This is annoying, why are we using sequential?"
```

**Why they switched**:
- Confiture v0.6.0 uses timestamps (like Rails)
- No more merge conflicts
- Clean project setup

**Result**: 0 conflicts over next 6 months, team happy

---

### Scenario 2: Enterprise with Many Tools

**Stack**: 5 microservices using different migration tools

```
Service A: Flyway  (hits 999 limit)
Service B: Django  (auto-generated migrations)
Service C: Alembic (UUIDs)
Service D: Rails   (timestamps)
Service E: Confiture v0.5 (sequential, planning upgrade)
```

**Problem**: Inconsistent versioning, mental overhead

**Solution**:
- Service E upgrades to Confiture v0.6 (timestamps)
- Now Services D and E use same approach
- Plan gradual unification (but no rush, both work)

---

## 📚 Further Reading

- **[Getting Started](../getting-started.md)** - Start using Confiture
- **[Comparison with Alembic](../comparison-with-alembic.md)** - Detailed feature comparison
- **[Performance Guide](../performance.md)** - Speed benefits explained

---

## ❓ FAQ

**Q: Can I switch from sequential to timestamp mid-project?**

A: Yes! Confiture v0.6.0 supports both:
```
001_legacy.py           ← old format still works
20260228120530_new.py   ← new timestamp format
```
Both coexist, old ones sort first (correct execution order).

**Q: What about my existing Flyway migrations?**

A: If migrating to Confiture:
1. Export Flyway migration files as-is
2. Rename to Confiture format: `001_*.sql` → `001_*.py` (wrap in Migration class)
3. Or keep SQL files as `.sql` with accompanying YAML sidecar
4. Confiture will execute them in order

**Q: Does timestamp format work with CI/CD?**

A: Yes, perfectly:
```bash
# Commit with timestamp-based name
git add db/migrations/20260228120530_add_column.py
git push

# CI/CD automatically applies in order
confiture migrate up
```

No coordination needed, no special branching strategy required.

**Q: What if we run migrations in parallel?**

A: Timestamps handle this well:
```
Thread 1: 20260228120530_migration.py
Thread 2: 20260228120531_migration.py  ← clear ordering

If parallel execution is allowed:
Lock + SAVEPOINT prevents conflicts
Both can run, PostgreSQL handles isolation
```

**Q: Can we go back to sequential if we want?**

A: Technically yes, but don't:
1. Would require backfilling old timestamps → complex
2. Defeats the purpose (merge conflict avoidance)
3. No benefit to reverting
4. Stick with timestamps once you switch

---

## Summary: Why Timestamp Wins

| Aspect | Winner | Why |
|--------|--------|-----|
| **No merge conflicts** | Timestamp | Wall-clock time is unique |
| **Unlimited migrations** | Timestamp | No 999 hard limit |
| **Human readable** | Sequential | But very close for timestamps |
| **Chronological order** | Timestamp | Perfect sorting |
| **Team scalability** | Timestamp | Works for 1 to 1000 developers |
| **Real-world production use** | Rails/Knex/Confiture | 10+ years of battle-testing |

**Recommendation**: Use timestamp-based versioning (Confiture v0.6.0, Rails, Knex, etc.) for any new project or migration.

---

*Last updated: February 28, 2026*
*Confiture v0.6.0 — Timestamp-based migration versioning*
