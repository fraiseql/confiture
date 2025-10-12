# Zero-Downtime Migration Scenario

**Scenario**: Production name field refactoring without service interruption

**Last Updated**: October 12, 2025

---

## Business Context

### The Problem

**Company**: SocialNet Inc. - A social media platform with 10M+ users

**Current Situation**:
- User profile stores names as single `full_name` field
- Marketing team needs separate first/last names for personalization
- Legal team needs proper name handling for GDPR/CCPA compliance
- Product team wants to enable "formal" vs "casual" name display options

**Pain Points**:
1. Email templates say "Hello Full Name" instead of "Hello First Name"
2. Cannot sort users by last name in admin interface
3. Analytics broken for name-based cohorts
4. User import/export requires manual name splitting

**Business Impact**:
- Lost revenue: $50K/month (poor email engagement due to impersonal greetings)
- Support burden: 200 tickets/month related to name display issues
- Compliance risk: GDPR audits flagging improper name handling
- Developer time: 5 hours/week manual name manipulation

### Success Criteria

**Primary Goals**:
1. Split `full_name` into `first_name` and `last_name` with >99.9% accuracy
2. Zero production downtime during migration
3. Zero data loss
4. Complete migration within 4 hours
5. Enable rollback capability at any stage

**Secondary Goals**:
1. Performance impact < 10% during migration
2. Migration cost < $500 (database resources)
3. Document process for future schema migrations
4. Team training on zero-downtime patterns

**Success Metrics**:
- Application uptime: 100% (0 seconds downtime)
- Data accuracy: >99.9% (measured by sample verification)
- Performance degradation: <10% during migration
- Migration completion time: <4 hours
- Rollback time (if needed): <15 minutes

---

## Technical Requirements

### Current Schema

```sql
-- Existing production schema
CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL,
    bio TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_full_name ON users(full_name);
```

**Table Statistics**:
- Total rows: 10,234,567
- Average row size: 312 bytes
- Total table size: 3.2 GB
- Index size: 890 MB
- Write rate: 1,000 INSERTs/sec (peak), 500 UPDATEs/sec (peak)
- Read rate: 10,000 SELECTs/sec (peak)

**Name Format Distribution**:
```sql
-- Analysis of current full_name data
SELECT
    CASE
        WHEN full_name ~ '^[^ ]+ [^ ]+$' THEN 'First Last' -- 85%
        WHEN full_name ~ '^[^ ]+ [^ ]+ [^ ]+$' THEN 'First Middle Last' -- 10%
        WHEN full_name ~ '^[^ ]+$' THEN 'Single Name' -- 4%
        ELSE 'Complex' -- 1%
    END as name_pattern,
    COUNT(*) as count,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) as percentage
FROM users
GROUP BY name_pattern;

-- Results:
-- First Last: 8,699,381 (85%)
-- First Middle Last: 1,023,456 (10%)
-- Single Name: 409,382 (4%)
-- Complex: 102,348 (1%)
```

### Target Schema

```sql
-- Desired production schema
CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    bio TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_first_name ON users(first_name);
CREATE INDEX idx_users_last_name ON users(last_name);
CREATE INDEX idx_users_full_name ON users(first_name, last_name);
```

**Schema Changes**:
1. **Remove column**: `full_name`
2. **Add column**: `first_name TEXT NOT NULL`
3. **Add column**: `last_name TEXT NOT NULL`
4. **Add index**: `idx_users_first_name`
5. **Add index**: `idx_users_last_name`
6. **Modify index**: `idx_users_full_name` now covers `(first_name, last_name)`

### Data Transformation Rules

**Name Splitting Logic**:

```python
def split_full_name(full_name: str) -> tuple[str, str]:
    """
    Split full_name into first_name and last_name.

    Strategy:
    1. Trim whitespace
    2. Find last space (everything before = first_name, everything after = last_name)
    3. This preserves middle names as part of first_name
    4. Handle edge cases (single names, empty strings, etc.)

    Examples:
        "John Doe" → ("John", "Doe")
        "Mary Jane Watson" → ("Mary Jane", "Watson")
        "Madonna" → ("Madonna", "")
        "  Spaced  Out  " → ("Spaced", "Out")
        "" → ("", "")
    """
    if not full_name:
        return ("", "")

    full_name = full_name.strip()

    if ' ' not in full_name:
        return (full_name, "")

    # Find last space
    last_space_idx = full_name.rfind(' ')
    first_name = full_name[:last_space_idx].strip()
    last_name = full_name[last_space_idx + 1:].strip()

    return (first_name, last_name)
```

**Name Concatenation Logic** (for reverse sync):

```python
def concat_names(first_name: str, last_name: str) -> str:
    """
    Concatenate first_name and last_name into full_name.

    Examples:
        ("John", "Doe") → "John Doe"
        ("Mary Jane", "Watson") → "Mary Jane Watson"
        ("Madonna", "") → "Madonna"
        ("", "Prince") → "Prince"
        ("", "") → ""
    """
    parts = [p.strip() for p in [first_name, last_name] if p]
    return " ".join(parts)
```

**Data Accuracy Requirements**:
- Lossless transformation: `concat_names(split_full_name(x)) ≈ x` (modulo whitespace)
- Verification sample size: 10,000 random rows (99.9% accuracy required)
- Edge case handling: NULL values, empty strings, excessive whitespace

---

## Infrastructure Context

### Production Environment

**Database**:
- PostgreSQL 15.4
- Instance type: AWS RDS db.r6g.2xlarge (8 vCPU, 64 GB RAM)
- Storage: 500 GB GP3 SSD (12,000 IOPS provisioned)
- Multi-AZ deployment: Yes
- Backup retention: 7 days
- Maintenance window: Sunday 03:00-04:00 UTC

**Application**:
- Architecture: Microservices (Kubernetes)
- Replicas: 20 pods (horizontal autoscaling)
- Language: Python 3.11 (FastAPI)
- ORM: SQLAlchemy 2.0
- Connection pool: 10 connections per pod (200 total)
- Average request latency: 45ms (p95: 120ms)

**Traffic Patterns**:
```
Hour (UTC) | Requests/sec | DB Writes/sec | DB Reads/sec
-----------|--------------|---------------|-------------
00:00      | 2,000        | 200           | 1,800
04:00      | 1,500        | 150           | 1,350  ← LOWEST
08:00      | 5,000        | 500           | 4,500
12:00      | 8,000        | 800           | 7,200
16:00      | 12,000       | 1,200         | 10,800 ← PEAK
20:00      | 10,000       | 1,000         | 9,000
```

**Best Migration Window**: 04:00-08:00 UTC (lowest traffic)

### Technical Constraints

**Database Constraints**:
1. **No downtime allowed**: 99.99% SLA (52 minutes/year max)
2. **No blocking locks**: Must use `CONCURRENTLY` for all DDL
3. **Resource limits**: CPU < 80%, Memory < 75%, IOPS < 80% during migration
4. **Replication lag**: Must stay < 5 seconds (RDS read replicas)

**Application Constraints**:
1. **Zero code changes for cutover**: Use connection string switch only
2. **Backward compatible**: Old and new schemas must coexist
3. **No application restart during migration**: Only at cutover
4. **Session preservation**: Active user sessions must not break

**Operational Constraints**:
1. **Monitoring required**: Real-time dashboards for migration progress
2. **Alerting thresholds**: Error rate >0.1%, latency >200ms, replication lag >5s
3. **Communication plan**: Stakeholder updates every 30 minutes
4. **Rollback readiness**: Can revert within 15 minutes at any point

---

## Risk Assessment

### High-Risk Areas

**Risk 1: Data Loss**
- **Probability**: Low (2%)
- **Impact**: Critical
- **Mitigation**:
  - Full database backup before starting
  - Continuous verification during dual-write period
  - Bidirectional sync ensures both schemas always have latest data
  - Rollback procedure tested in staging

**Risk 2: Application Errors After Cutover**
- **Probability**: Medium (15%)
- **Impact**: High
- **Mitigation**:
  - Comprehensive testing in staging environment
  - Canary deployment: Switch 1 pod first, monitor, then switch all
  - Automated health checks
  - Quick rollback procedure (< 15 minutes)

**Risk 3: Performance Degradation**
- **Probability**: Medium (20%)
- **Impact**: Medium
- **Mitigation**:
  - Throttle migration speed to limit impact
  - Monitor database metrics continuously
  - Tune trigger performance
  - Add indexes CONCURRENTLY (no locks)

**Risk 4: Name Splitting Inaccuracies**
- **Probability**: High (30%)
- **Impact**: Low
- **Mitigation**:
  - Sample 10,000 rows for accuracy verification (>99.9% required)
  - Manual review of edge cases
  - Support team briefed on potential issues
  - Post-migration cleanup script for problematic names

**Risk 5: Trigger Infinite Loop**
- **Probability**: Low (5%)
- **Impact**: Critical
- **Mitigation**:
  - Trigger guards to prevent recursion
  - Tested extensively in staging
  - Circuit breaker logic
  - Monitoring for trigger execution spikes

### Medium-Risk Areas

**Risk 6: High Replication Lag**
- **Probability**: Medium (25%)
- **Impact**: Medium
- **Mitigation**: Reduce write rate, scale up resources temporarily

**Risk 7: Unexpected Lock Contention**
- **Probability**: Medium (20%)
- **Impact**: Medium
- **Mitigation**: Use NOWAIT locks, monitor pg_locks, schedule during low traffic

**Risk 8: Insufficient Testing**
- **Probability**: Low (10%)
- **Impact**: High
- **Mitigation**: Full staging rehearsal, verification scripts, code review

### Low-Risk Areas

**Risk 9: Monitoring Blind Spots**
- **Probability**: Low (10%)
- **Impact**: Low
- **Mitigation**: Pre-configure all dashboards, test alerting

**Risk 10: Team Communication Breakdown**
- **Probability**: Low (5%)
- **Impact**: Low
- **Mitigation**: Dedicated Slack channel, regular status updates

---

## Migration Strategy Comparison

### Why NOT These Approaches?

**Approach 1: ALTER TABLE (Classic Migration)**
```sql
-- This would work...
ALTER TABLE users ADD COLUMN first_name TEXT;
ALTER TABLE users ADD COLUMN last_name TEXT;
UPDATE users SET
    first_name = split_part(full_name, ' ', 1),
    last_name = COALESCE(NULLIF(split_part(full_name, ' ', 2), ''), '');
ALTER TABLE users DROP COLUMN full_name;
```

**Why NOT**:
- ❌ `ALTER TABLE` would lock table for seconds to minutes
- ❌ `UPDATE` on 10M rows takes 30+ minutes with table locked
- ❌ Cannot roll back after `DROP COLUMN`
- ❌ Application breaks during migration
- ❌ **Downtime: 30-60 minutes** ← UNACCEPTABLE

---

**Approach 2: Read Replicas + DNS Switch**

**Why NOT**:
- ❌ Requires stopping writes to old database
- ❌ Complex DNS propagation issues
- ❌ Requires application code changes
- ❌ Risk of split-brain if switch fails
- ❌ Cannot easily roll back

---

**Approach 3: Blue/Green Deployment**

**Why NOT**:
- ❌ Requires duplicating entire database (expensive)
- ❌ Complex data synchronization during transition
- ❌ Higher resource costs (2x database)
- ❌ Difficult to sync writes during cutover window

---

### Why Schema-to-Schema (FDW)?

**Advantages**:
- ✅ **Zero downtime**: Old and new schemas coexist
- ✅ **Gradual migration**: Copy data incrementally
- ✅ **Bidirectional sync**: Both schemas stay current
- ✅ **Easy rollback**: Just switch connection back
- ✅ **Verification time**: Days to verify if needed
- ✅ **Low risk**: Tested approach, no destructive operations

**How It Works**:
1. Create new schema in same database
2. Use Foreign Data Wrapper to access old schema from new schema
3. Set up triggers for bidirectional synchronization
4. Copy data with transformation
5. Switch application to new schema (just connection string change)
6. Clean up after verification period

**Trade-offs**:
- Requires PostgreSQL FDW extension
- Slightly higher write latency during dual-write period (~10ms)
- More complex setup than simple ALTER TABLE
- Requires trigger maintenance during migration

---

## Success Metrics

### Migration Metrics

**Quantitative**:
- [ ] **Downtime**: 0 seconds (target: 0, max acceptable: 60)
- [ ] **Data loss**: 0 rows (target: 0, max acceptable: 0)
- [ ] **Accuracy**: >99.9% (target: 99.99%, min acceptable: 99.9%)
- [ ] **Duration**: <4 hours (target: 2, max acceptable: 6)
- [ ] **Performance impact**: <10% (target: 5%, max acceptable: 15%)

**Qualitative**:
- [ ] No user-visible errors during migration
- [ ] All application features work after cutover
- [ ] Team confident in process for future migrations
- [ ] Documentation complete and accurate

### Business Metrics

**Pre-Migration**:
- Email engagement: 2.5% (baseline)
- Support tickets: 200/month
- Developer time: 5 hours/week

**Post-Migration (Expected)**:
- Email engagement: 3.5% (+40% improvement)
- Support tickets: 50/month (-75%)
- Developer time: 1 hour/week (-80%)

**ROI Calculation**:
```
Cost:
- Engineering time: 40 hours × $100/hour = $4,000
- Database resources: $500
- Total: $4,500

Benefit (monthly):
- Email revenue improvement: $50,000 × 40% = $20,000
- Support cost reduction: 150 tickets × $50/ticket = $7,500
- Developer time saved: 16 hours × $100/hour = $1,600
- Total monthly: $29,100

ROI: ($29,100 × 12 - $4,500) / $4,500 = 77x return
Payback period: 0.15 months (4.6 days)
```

---

## Team and Communication

### Roles and Responsibilities

**Migration Lead** (Database Engineer):
- Overall migration execution
- Monitoring database metrics
- Decision authority for rollback
- Primary on-call during migration

**Application Lead** (Backend Engineer):
- Application cutover execution
- Code deployment coordination
- Application monitoring
- Secondary on-call during migration

**DevOps Lead**:
- Infrastructure monitoring
- Kubernetes deployment management
- Incident response coordination

**Product Manager**:
- Stakeholder communication
- Business metrics tracking
- Post-migration success validation

**Support Team Lead**:
- Customer communication plan
- Support ticket monitoring
- Escalation path for user-reported issues

### Communication Plan

**Pre-Migration** (1 week before):
- Email to all engineering: Migration scheduled, what to expect
- Slack announcement: Migration date/time, point of contact
- Stakeholder briefing: Business context, success criteria

**During Migration**:
- Slack updates every 30 minutes in #database-migrations
- Real-time dashboard shared with team
- War room (video call) open for entire migration
- On-call team available for escalations

**Post-Migration**:
- Immediate: Slack announcement of successful cutover
- 24 hours: Status update email (any issues, rollback status)
- 1 week: Post-mortem meeting
- 2 weeks: Lessons learned document published

### Escalation Path

```
Level 1: Migration Lead
  ↓ (if cannot resolve in 15 minutes)
Level 2: Database Team Lead
  ↓ (if critical issue)
Level 3: CTO
  ↓ (if requires business decision)
Level 4: CEO (for communication/PR)
```

---

## Testing Strategy

### Pre-Production Testing

**Staging Environment**:
- Full rehearsal of migration on staging database (1M rows)
- Verify all scripts execute successfully
- Measure performance impact
- Test rollback procedure
- Validate application against new schema

**Load Testing**:
- Simulate production traffic during migration
- Measure performance degradation
- Identify bottlenecks
- Tune batch sizes and throttling

**Verification Testing**:
- Run all verification scripts against staging data
- Validate accuracy metrics
- Test edge cases (NULL, empty strings, special characters)

### Production Testing Plan

**Phase 1: Canary Cutover**:
1. Switch 1 pod to new schema (5% traffic)
2. Monitor for 15 minutes
3. If healthy, proceed to full cutover
4. If issues, rollback single pod, investigate

**Phase 2: Full Cutover**:
1. Switch all pods to new schema
2. Monitor for 30 minutes intensively
3. Verify all API endpoints
4. Check database metrics

**Phase 3: Extended Monitoring**:
1. Monitor for 24 hours at regular intervals
2. Track business metrics
3. Review support tickets
4. Validate with product team

---

## Timeline

### Migration Timeline (Total: 4 hours)

```
T-0:00 (04:00 UTC) - Start Migration
├─ 0:00-0:30 - Setup phase
│  ├─ Create new schema
│  ├─ Deploy FDW
│  ├─ Deploy triggers
│  └─ Verification
│
├─ 0:30-2:30 - Data migration phase
│  ├─ Initial data copy (10M rows)
│  ├─ Progress monitoring
│  └─ Accuracy verification
│
├─ 2:30-3:30 - Dual-write verification phase
│  ├─ Test application writes to both schemas
│  ├─ Verify trigger performance
│  ├─ Monitor replication lag
│  └─ Final accuracy verification
│
└─ 3:30-4:00 - Cutover phase
   ├─ Canary cutover (1 pod)
   ├─ Monitor (15 min)
   ├─ Full cutover (all pods)
   └─ Verify application health

T+4:00 (08:00 UTC) - Migration Complete
```

### Post-Migration Timeline

```
T+4 hours: Migration complete, monitoring continues
T+24 hours: Decision point - keep or rollback
T+48 hours: If stable, drop old→new trigger
T+72 hours: Final decision point
T+1 week: Drop new→old trigger, cleanup FDW
T+2 weeks: Drop old schema, post-mortem complete
```

---

## Lessons from Past Migrations

### What Went Well

**Previous migration: Adding user_status column** (2024-08):
- ✅ Comprehensive testing in staging prevented production issues
- ✅ Incremental approach allowed catching issues early
- ✅ Good communication kept team aligned
- ✅ Monitoring dashboards gave confidence

### What Went Wrong

**Previous migration: Email verification redesign** (2024-06):
- ❌ Insufficient verification led to 2-hour rollback
- ❌ Trigger performance not tested at scale
- ❌ Missing rollback procedure caused panic
- ❌ Poor communication created confusion

### Key Learnings Applied

1. **Test triggers at production scale** - Load test with 1M+ rows
2. **Document rollback FIRST** - Before starting migration
3. **Verify, verify, verify** - Multiple independent verification methods
4. **Communicate proactively** - Regular updates, even if "no news"
5. **Have rollback authority** - Clear decision maker

---

## Appendix: Edge Cases

### Unusual Name Formats

**Format**: `"Dr. John Q. Public III"`
**Split Result**: `first_name="Dr. John Q. Public", last_name="III"`
**Acceptable**: Yes (suffixes treated as last name)

**Format**: `"Mary-Jane Watson-Parker"`
**Split Result**: `first_name="Mary-Jane", last_name="Watson-Parker"`
**Acceptable**: Yes (hyphens preserved)

**Format**: `"김철수"` (Korean name)
**Split Result**: `first_name="김철수", last_name=""`
**Acceptable**: Yes (single names handled)

**Format**: `"van der Berg, Johann"`
**Split Result**: `first_name="van der Berg,", last_name="Johann"`
**Acceptable**: No - **requires manual cleanup**

**Format**: `""` (empty)
**Split Result**: `first_name="", last_name=""`
**Acceptable**: Yes (but violates NOT NULL - must handle in migration)

### Manual Cleanup Required

Estimate: ~10,000 rows (0.1%) will require manual review post-migration.

**Cleanup Process**:
1. Export rows with suspicious patterns to CSV
2. Product team reviews and provides corrections
3. Bulk update with corrections
4. Re-verify accuracy

---

**Scenario**: Zero-Downtime Production Migration
**Strategy**: Schema-to-Schema (Medium 4)
**Risk Level**: Medium (with mitigations)
**Expected Duration**: 4 hours
**Expected Downtime**: 0 seconds

**Last Updated**: October 12, 2025
