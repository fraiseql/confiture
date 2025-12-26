# Phase 4 Specialist Review Checklist

**Document Purpose**: Structured review guide for specialists to validate Phase 4 strategy against existing tools and patterns

**Review Date**: [To be filled by reviewer]
**Reviewer Name**: [To be filled by reviewer]
**Expertise Areas**: [Check all that apply]
- [ ] PostgreSQL Performance & Administration
- [ ] Python Application Architecture
- [ ] pggit Version Control System
- [ ] Confiture Migration Framework
- [ ] PrintOptim CQRS Architecture
- [ ] Data Privacy & Anonymization
- [ ] DevOps & CI/CD

---

## Section 1: Migration Hooks Validation

### Current State Analysis

**Existing Patterns**:
- [ ] Review Confiture's current migration execution model (phases 1-3)
  - Files to review: `confiture/core/migrator.py`, `confiture/core/builder.py`
  - Question: How are migrations currently executed? Sequential or parallel?
  - Finding: _______________________________________________

- [ ] Check PrintOptim's hook patterns in stored procedures
  - Files to review: `printoptim_backend/db/0_schema/03_functions/`
  - Question: Are there existing trigger patterns that should inform hook design?
  - Finding: _______________________________________________

- [ ] Examine pggit's trigger-based DDL capture
  - Files to review: `/home/lionel/code/pggit/sql/v1.0.0/phase_1_triggers.sql`
  - Question: Can pggit's trigger patterns be reused for hook execution?
  - Finding: _______________________________________________

### Hook System Design

**[ ] Architecture Validation**

- [ ] **Transaction Handling**:
  - Assess: Does the proposed savepoint-per-hook approach fit with Confiture's connection pooling?
  - Concern: What if connection is lost mid-savepoint?
  - Recommendation: _____________________________________________

- [ ] **Error Handling**:
  - Question: Should hook failures automatically trigger rollback or notify operator?
  - Current practice: In PrintOptim, how are stored procedure errors handled?
  - Recommendation: _____________________________________________

- [ ] **Hook Registry**:
  - Assess: Is the proposed plugin system (using names like `backfill_read_model`) compatible with Confiture's configuration system?
  - Question: Should hooks be Python classes, YAML configs, or SQL functions?
  - Recommendation: _____________________________________________

**[ ] Hook Types**

- [ ] **BEFORE_VALIDATION Hook**:
  - Realistic? Are there real use cases in PrintOptim or pggit that require pre-flight checks?
  - Example from your experience: _________________________________

- [ ] **BEFORE_DDL Hook**:
  - Practical? What would typically need to happen before DDL?
  - PrintOptim example: Backfilling temp tables before column addition?
  - Concern: How to prevent deadlocks during concurrent operations?
  - Recommendation: _____________________________________________

- [ ] **AFTER_DDL Hook**:
  - Essential? For CQRS backfill in PrintOptim, is this the right time to populate read models?
  - Alternative approaches considered?
  - Recommendation: _____________________________________________

- [ ] **AFTER_VALIDATION Hook**:
  - Use case unclear? When would this differ from AFTER_DDL validation?
  - Suggestion: Merge with AFTER_DDL or clarify distinction?
  - Recommendation: _____________________________________________

- [ ] **CLEANUP Hook**:
  - Necessary? Or can this be handled in application code post-migration?
  - Risk: What if CLEANUP hook fails?
  - Recommendation: _____________________________________________

- [ ] **ON_ERROR Hook**:
  - Strategy validation: Is triggering error handlers the right approach?
  - Concern: Multiple error handlers could hide original error
  - Recommendation: _____________________________________________

### Performance Implications

- [ ] **Overhead**: What's the expected performance impact of hook infrastructure?
  - Metric: Extra latency per hook?
  - Test plan: Should we benchmark against Phase 3 migrations?
  - Recommendation: _____________________________________________

- [ ] **Backfill Performance**: For AFTER_DDL backfill hooks in PrintOptim:
  - Question: Is batching the right approach or should we use COPY?
  - Concern: Parallel workers (4 by default) may cause lock contention
  - Recommendation: Test with actual PrintOptim data (2.1M customer records)?

- [ ] **Savepoint Overhead**: Each hook creates a savepoint
  - Concern: Do nested savepoints have performance penalty in PostgreSQL?
  - Test needed: Benchmark 5-10 hooks in sequence
  - Recommendation: _____________________________________________

### Rollback Strategy

- [ ] **Hook Rollback**: How are hooks rolled back when migration is rolled back?
  - Current design: Silent rollback via savepoint?
  - Concern: If hook modified external system (log file, cache), savepoint won't help
  - Recommendation: Document that hooks should only modify database? Or provide hook-specific rollback?

- [ ] **Idempotency**: Can hooks be safely re-executed if migration is re-run?
  - Example: Backfill hook on duplicate run - should it use INSERT IGNORE or upsert?
  - Concern: What if backfill already happened?
  - Recommendation: _____________________________________________

---

## Section 2: Custom Anonymization Strategies

### Integration with Phase 3

- [ ] **Phase 3 Compatibility**: Current Phase 3 anonymizer uses functions like `mask_email()`
  - Files to review: `confiture/core/syncer.py` (anonymization code from Phase 3)
  - Question: Can Phase 4 strategies replace Phase 3 approach or should they coexist?
  - Concern: Breaking change if we deprecate Phase 3 API?
  - Recommendation: _____________________________________________

### Strategy Design

**[ ] Strategy Implementation**

- [ ] **EmailMaskingStrategy**: Keeping domain makes sense, but:
  - Question: What about subdomains? (user@mail.example.com → user+anon@mail.example.com?)
  - Edge case: What about addresses with + already? (user+tag@example.com)
  - Recommendation: _____________________________________________

- [ ] **DeterministicHashStrategy**: Using SHA-256 with salt
  - Concern: Is SHA-256 strong enough or should we use bcrypt?
  - Question: Where is salt stored securely? Should it be rotatable?
  - Recommendation: _____________________________________________

- [ ] **PatternMaskingStrategy**: Using string matching
  - Practical? For SSN (***-**-9999), works for fixed-length, what about variable?
  - Edge case: What if value length doesn't match pattern?
  - Recommendation: _____________________________________________

- [ ] **ConditionalStrategy**: Applies different strategies based on row data
  - Use case from PrintOptim: "Skip anonymization for internal customers?"
  - Question: Can conditions reference multiple columns?
  - Recommendation: _____________________________________________

### Configuration & Profiles

- [ ] **YAML Format**: Proposed format supports custom strategies but:
  - Question: Is the configuration discoverable enough for operators?
  - Concern: Complex nested rules might become unmanageable
  - Suggestion: Validation schema or code generator?
  - Recommendation: _____________________________________________

- [ ] **Environment Profiles**: qa, test, staging, production
  - Question: How to version/track changes to anonymization rules?
  - Concern: If QA profile changes, should existing QA data be re-anonymized?
  - Recommendation: _____________________________________________

### PrintOptim Specific

- [ ] **Multi-Tenant Integrity**: The guidance says "Keep tenant_id, mask customer_id"
  - Question: How do we verify that masked customer_ids remain valid (exist in customers)?
  - Concern: Foreign key constraints might fail after anonymization
  - Recommendation: Run verification queries post-anonymization?

- [ ] **Read Model Consistency**: After syncing w_customers with masked IDs:
  - Question: How do we keep r_customer_lifetime_value consistent?
  - Concern: If customer_id is hashed, the hash must be identical across all tables
  - Test needed: Verify same source customer_id hashes to same value in all tables?
  - Recommendation: _____________________________________________

### Data Loss Risk

- [ ] **Verification Tool**: Proposed `AnonymizationVerifier` checks reversibility and consistency
  - Question: What's the minimum check suite for production?
  - Concern: False confidence if verification isn't comprehensive
  - Recommendation: Mandatory checks for Phase 4?

---

## Section 3: Interactive Migration Wizard

### User Experience Design

- [ ] **Risk Assessment**: Proposed risk levels (low/medium/high)
  - Question: How are they calculated? Lock time thresholds? Row count impact?
  - Concern: Different users might assess risk differently
  - Suggestion: Customizable thresholds per environment?
  - Recommendation: _____________________________________________

- [ ] **Recommendations**: Wizard provides actionable advice
  - Example: "Deploy application code BEFORE this migration"
  - Question: How are recommendations generated? Hard-coded rules or AI?
  - Concern: Recommendations must be accurate to build trust
  - Recommendation: Start with conservative recommendations?

- [ ] **Interactive Prompts**: Multiple options (yes/no/preview/skip/details)
  - Usability concern: Too many options might confuse operators
  - Question: Should there be a "fast mode" with sensible defaults?
  - Recommendation: _____________________________________________

### Rich Terminal Output

- [ ] **Formatting Library**: Using `rich` for pretty printing
  - Question: Is `rich` already a dependency in Confiture?
  - Concern: If not, adds external dependency
  - Recommendation: Check pyproject.toml for existing `rich` usage?

- [ ] **Progress Bars**: Showing migration progress live
  - Question: How accurate are progress estimates during backfill?
  - Concern: If estimate is wrong, user loses confidence
  - Recommendation: Only show progress if margin of error is <20%?

### Accessibility Concerns

- [ ] **Terminal Support**: Rich output requires modern terminal
  - Question: What about legacy systems or CI/CD environments?
  - Concern: Colors/formatting might not work in all terminals
  - Recommendation: Provide `--no-color` flag?

---

## Section 4: Migration Dry-Run Mode

### Transaction Rollback Strategy

- [ ] **Automatic Rollback**: Using transaction with savepoint
  - Question: Does automatic rollback work in Confiture's connection pooling?
  - Concern: If connection drops, does savepoint rollback or commit?
  - PostgreSQL version dependency: How far back does this work?
  - Recommendation: Test on PostgreSQL 13+?

- [ ] **Lock Implications**: Dry-run takes same locks as real migration
  - Question: Is this acceptable in production during business hours?
  - Concern: Locks during dry-run could block other operations
  - Recommendation: Dry-run should target replica or scheduled maintenance window?

### Metrics Capture

- [ ] **What's Measured**: Proposed metrics include rows affected, lock times, index creation times
  - Question: Are these accurate or estimates?
  - Concern: Estimated time might not match real execution (WAL, cache state)
  - Suggestion: Run dry-run 2-3 times and average?
  - Recommendation: _____________________________________________

- [ ] **Confidence Level**: Estimated production time with ±15% confidence
  - Question: How is confidence calculated?
  - Concern: ±15% is wide; what if actual is 2x slower?
  - Recommendation: More conservative estimate for risky migrations?

### Edge Cases

- [ ] **Foreign Key Constraints**: What if dry-run violates constraints?
  - Question: Should dry-run prevent violations or just report them?
  - Concern: False confidence if dry-run passes but production fails
  - Recommendation: _____________________________________________

- [ ] **Triggers & Rules**: What if database has triggers that prevent test data?
  - Example: Audit triggers that reject test migrations
  - Concern: Dry-run might not be realistic if triggers behave differently
  - Recommendation: Disable specific triggers for dry-run?

---

## Section 5: Database Schema Linting

### Rule Coverage

**[ ] Built-in Rules Assessment**

- [ ] **NamingConventionRule**: Enforces snake_case
  - Question: How strict should naming be?
  - Concern: Legacy code might not follow conventions
  - Suggestion: Severity should be warning, not error?
  - Recommendation: _____________________________________________

- [ ] **PrimaryKeyRule**: Requires PK on all tables
  - Question: Are there legitimate tables without PKs (e.g., audit log)?
  - Concern: Strict enforcement might be too rigid
  - Recommendation: Allow exemption list?

- [ ] **DocumentationRule**: Requires COMMENT on tables
  - Practical? For 1,256 files in PrintOptim, enforcing comments on all?
  - Concern: Maintenance burden to keep comments updated
  - Recommendation: Start with public tables only?

- [ ] **MultiTenantRule**: Requires tenant_id in tables
  - Perfect for PrintOptim! But:
  - Question: How to avoid false positives on shared/lookup tables?
  - Concern: System tables, reference data might not need tenant_id
  - Recommendation: _____________________________________________

- [ ] **MissingIndexRule**: Detects FKs without indexes
  - Practical? Could be many false positives for rarely-joined columns
  - Question: Should rule consider actual query patterns or just schema?
  - Recommendation: Start conservative, add to warning only?

- [ ] **SecurityRule**: Checks for unlogged tables, password fields
  - Question: How does it detect password fields? Column name pattern?
  - Concern: Could miss passwords stored as `pwd_hash` or `auth_token`
  - Recommendation: _____________________________________________

### Custom Rules System

- [ ] **Plugin Architecture**: Users can define custom rules
  - Question: What's the interface for custom rules?
  - Concern: Complexity - should we support this in v1 or Phase 4.1?
  - Recommendation: Start with built-in rules, add plugins in Phase 4.1?

- [ ] **PrintOptim-Specific Rules**: Proposed CQRS validation rules
  - Example: "Read models must be derived from write models"
  - Question: How does linter verify this? Analyze view definitions?
  - Concern: Complex to detect all derivation patterns
  - Recommendation: Require explicit mapping in migration YAML?

### False Positives

- [ ] **Testing**: What's the plan to validate linting accuracy?
  - Concern: Rules might produce false positives on valid schemas
  - Suggestion: Test against PrintOptim's 1,256 files?
  - Recommendation: Acceptable false positive rate?

- [ ] **Severity Configuration**: Rules have error/warning/info levels
  - Question: Can severity be overridden per rule?
  - Concern: Different teams might have different standards
  - Recommendation: Support per-environment linting profiles?

---

## Section 6: pggit Integration

### Current pggit State

- [ ] **Phase 1 Complete**: pggit has 8 tables, utility functions, DDL triggers
  - Files to review: `/home/lionel/code/pggit/sql/v1.0.0/`
  - Question: What's the data model for tracking schema changes?
  - Key tables: audit trail table for DDL, change log structure?
  - Finding: _______________________________________________

- [ ] **Python Client**: Does pggit Phase 1 include Python client?
  - Files to review: `/home/lionel/code/pggit/src/` (if exists)
  - Question: What's the API surface?
  - Concern: Phase 4 depends on pggit client library (Phase 2 work)
  - Recommendation: Verify pggit Phase 2 timeline aligns with Confiture Phase 4?

### Integration Points

**[ ] Builder Integration**

- [ ] **SchemaBuilder.build_from_git_history()**:
  - Question: How does pggit store DDL statements? Raw SQL or compressed?
  - Concern: Performance of reconstructing schema from audit trail
  - Recommendation: Test with realistic pggit dataset?

- [ ] **Schema Diffing Against pggit Refs**:
  - Question: Will this work across branches/tags?
  - Use case: "Show me schema changes between main and feature branch"
  - Concern: Performance of diffing large schemas
  - Recommendation: Cache diff results?

**[ ] Migrator Integration**

- [ ] **Event Registration**:
  - Design: Migrator registers "MIGRATION_APPLIED" events in pggit
  - Question: What happens if pggit is down during migration?
  - Concern: Should we fail migration or queue event for later?
  - Current design allows async registration - is this correct?
  - Recommendation: _____________________________________________

- [ ] **Migration History**:
  - Use case: Dashboard showing all migrations with timestamps/operators
  - Question: How detailed should events be? Just name and status?
  - Concern: Long-term storage of audit trail - will pggit table grow too large?
  - Recommendation: Archival strategy for old events?

### Dependency Risks

- [ ] **Tight Coupling**: Confiture Phase 4 depends on pggit Phase 2
  - Question: What if pggit Phase 2 delays?
  - Concern: Can Confiture Phase 4 ship without pggit integration?
  - Recommendation: Make pggit optional dependency?

- [ ] **API Stability**: What if pggit's Python client API changes?
  - Question: How to version the API?
  - Concern: Breaking changes would require Confiture updates
  - Recommendation: Define stable interface early?

---

## Section 7: PrintOptim Integration Deep Dive

### CQRS Architecture Fit

- [ ] **Current State**: PrintOptim has write-side (01_write_side) and read-side (02_query_side)
  - Files to review: `printoptim_backend/db/0_schema/01_write_side/`, `02_query_side/`
  - Question: How are read models currently synchronized?
  - Current approach: Views? Materialized views? Scheduled jobs?
  - Finding: _______________________________________________

- [ ] **Hook Applicability**: Phase 4 proposes AFTER_DDL hooks for read model backfill
  - Question: Is this the right place for backfill?
  - Concern: Backfill during migration might lock tables
  - Alternative: Async backfill job after migration completes?
  - Recommendation: _____________________________________________

- [ ] **Consistency Verification**: After backfill, need to verify read model matches write model
  - Question: What consistency checks are needed?
  - Example: Row counts, sum totals, average values
  - Concern: Validation queries might themselves be slow
  - Recommendation: Spot-check vs exhaustive verification?

### Multi-Tenant Constraints

- [ ] **tenant_id Enforcement**: Linting rule requires tenant_id in all tables
  - Question: How consistent is this in current PrintOptim schema?
  - Concern: Missing tenant_id in legacy tables could cause data leakage
  - Recommendation: Audit existing schema for compliance?

- [ ] **Anonymization Edge Case**: When syncing to QA, tenant_id must be preserved
  - Question: How to ensure tenant_id is never anonymized?
  - Current risk: Accidental masking of tenant_id would break relationships
  - Recommendation: Explicit safety check: "tenant_id is immutable"?

### Schema Organization

- [ ] **Load Order**: Phase 4 proposes specific load order for schema directories
  - Proposed order: security → extensions → functions → write → read → procedures → seed
  - Question: Does current PrintOptim schema have dependency issues?
  - Concern: Missing function imports or circular dependencies?
  - Test needed: Build fresh database from scratch, verify success?
  - Recommendation: _____________________________________________

- [ ] **1,256 Files**: Managing this many files with Confiture
  - Question: Is file discovery (glob patterns) performant?
  - Concern: YAML parsing 1,256 files might be slow
  - Recommendation: Benchmark file discovery performance?

### Practical Migration Examples

- [ ] **Adding Read Model**: Proposed example (003_add_customer_analytics)
  - Question: Is this representative of real PrintOptim migrations?
  - Concern: Backfill of 2.1M rows might be too slow during business hours
  - Recommendation: Size limit for automatic backfill? Manual for large tables?

- [ ] **Adding Write-Side Column**: What about migrations to write-side tables?
  - Question: When write-side changes, must read-side views be updated?
  - Concern: Cascading migrations across CQRS boundary
  - Recommendation: Document CQRS update strategy?

---

## Section 8: Technical Implementation Details

### Language & Framework Choices

- [ ] **Hook Language**: Should hooks be Python classes or SQL?
  - Question: Can hooks be written in SQL (PL/pgSQL)?
  - Concern: Cross-language support complexity
  - Current design: Python hooks only?
  - Recommendation: _____________________________________________

- [ ] **Async/Await**: Phase 4 uses `async/await` throughout
  - Question: Is Confiture already async-based?
  - Concern: If not, adding async might require significant refactoring
  - Recommendation: Review existing Confiture code for async patterns?

- [ ] **Rich Library**: Using `rich` for terminal formatting
  - Question: Is this already a dependency?
  - Concern: Adding new dependency might require review
  - Recommendation: Check if justified for UX improvement?

### Database Driver

- [ ] **psycopg3 Features**: Phase 4 relies on psycopg3 (Python 3 only)
  - Question: Which psycopg3 version supports all needed features?
  - Concern: Savepoints, connection pooling, async
  - Recommendation: Document minimum version?

- [ ] **Connection Pooling**: How are connections managed during hooks?
  - Question: Does Confiture use connection pool?
  - Concern: Per-hook transaction might need dedicated connection
  - Recommendation: Review connection pool architecture?

### Data Structure Design

- [ ] **Hook Result Objects**: Proposed data structures for returning results
  - Question: Are dataclasses, TypedDict, or Pydantic models preferred?
  - Concern: Consistency with rest of Confiture codebase
  - Recommendation: Audit Confiture's existing data structures?

---

## Section 9: Testing Strategy

### Test Coverage

- [ ] **Unit Tests**: Proposed >90% coverage for Phase 4
  - Question: Is this realistic given complexity?
  - Concern: Some features (risk assessment) hard to test in isolation
  - Recommendation: Acceptable coverage threshold?

- [ ] **Integration Tests**: Database-dependent tests
  - Question: Can tests use PostgreSQL container (Docker)?
  - Concern: Test isolation - cleaning up after each test
  - Recommendation: Use conftest.py fixtures like Phase 1-3?

- [ ] **E2E Tests**: Full workflows with all Phase 4 features
  - Question: How long would e2e tests take? (performance concern)
  - Recommendation: Separate fast vs slow tests?

### Real-World Validation

- [ ] **PrintOptim Testing**: Before Phase 4 is declared complete
  - Question: Should all examples be tested against real PrintOptim schema?
  - Concern: 1,256 files is a large test case
  - Recommendation: Run Phase 4 migrations against PrintOptim test database?

---

## Section 10: Risk Summary & Recommendations

### High-Risk Areas

**[  ] Identify Specific Risks**

Based on your review, what are the highest-risk aspects of Phase 4?

1. Risk: _________________________________________________________________
   Impact: ________________________________________________________________
   Mitigation: _____________________________________________________________

2. Risk: _________________________________________________________________
   Impact: ________________________________________________________________
   Mitigation: _____________________________________________________________

3. Risk: _________________________________________________________________
   Impact: ________________________________________________________________
   Mitigation: _____________________________________________________________

### Critical Path Items

**[ ] What Must Happen Before Phase 4 Starts?**

- [ ] pggit Phase 2 (Python client library) - status: _________________
- [ ] Benchmark tests (hook overhead, anonymization throughput) - status: _________________
- [ ] PrintOptim schema audit (tenant_id compliance, dependencies) - status: _________________
- [ ] PostgreSQL version requirements clarified - status: _________________

### Implementation Order Recommendations

**[ ] Suggested Milestone Sequence**

Reviewer's recommended order (may differ from document's Weeks 1-8):

1. Milestone: ___________________________________________ (priority: HIGH/MEDIUM/LOW)
   Rationale: ____________________________________________________________

2. Milestone: ___________________________________________ (priority: HIGH/MEDIUM/LOW)
   Rationale: ____________________________________________________________

3. Milestone: ___________________________________________ (priority: HIGH/MEDIUM/LOW)
   Rationale: ____________________________________________________________

---

## Section 11: Specialist Recommendations

### Approve/Require Changes?

**Overall Assessment**:
- [ ] **APPROVED** - Proceed with Phase 4 as documented
- [ ] **APPROVED WITH CONDITIONS** - See conditions below
- [ ] **REQUEST REVISIONS** - Major changes needed (see details below)
- [ ] **DEFER** - Phase 4 should wait for prerequisite work

**Conditions (if applicable)**:
```
1. _________________________________________________________________
2. _________________________________________________________________
3. _________________________________________________________________
```

**Revisions Needed (if applicable)**:
```
1. _________________________________________________________________
2. _________________________________________________________________
3. _________________________________________________________________
```

### Alternative Approaches Considered

Based on your expertise, are there better approaches for:

**1. Hook Execution**:
   Alternative: ___________________________________________________________
   Pros: __________________________________________________________________
   Cons: __________________________________________________________________
   Recommendation: _________________________________________________________

**2. Anonymization Strategies**:
   Alternative: ___________________________________________________________
   Pros: __________________________________________________________________
   Cons: __________________________________________________________________
   Recommendation: _________________________________________________________

**3. pggit Integration**:
   Alternative: ___________________________________________________________
   Pros: __________________________________________________________________
   Cons: __________________________________________________________________
   Recommendation: _________________________________________________________

### Success Metrics Validation

**Are the proposed success metrics achievable?**

- [ ] Hook Reliability: 99.9% success rate
  - Assessment: ACHIEVABLE / OPTIMISTIC / UNREALISTIC
  - Reasoning: ____________________________________________________________

- [ ] Linting Accuracy: <2% false positive rate
  - Assessment: ACHIEVABLE / OPTIMISTIC / UNREALISTIC
  - Reasoning: ____________________________________________________________

- [ ] Risk Estimation: ±15% accuracy on execution time
  - Assessment: ACHIEVABLE / OPTIMISTIC / UNREALISTIC
  - Reasoning: ____________________________________________________________

---

## Section 12: Reviewer Sign-Off

**Reviewer Information**:
- Name: _________________________________________________________________
- Date: __________________________________________________________________
- Expertise Areas: ________________________________________________________
- Organization/Company: __________________________________________________

**Overall Comment**:
```
[Provide summary of review, key findings, and overall assessment]




```

**Signature**: _________________________ Date: _________________________

---

## Appendix: Quick Reference

### Files to Review

Essential files for reviewer to examine:

**Confiture Codebase**:
- `pyproject.toml` - Dependencies, Python version
- `confiture/core/migrator.py` - Migration execution model
- `confiture/core/syncer.py` - Phase 3 anonymization (baseline)
- `confiture/cli/main.py` - CLI structure (for wizard integration)

**pggit Codebase**:
- `README.md` - Project overview
- `sql/v1.0.0/phase_1_schema.sql` - Data model for audit trail
- `sql/v1.0.0/phase_1_triggers.sql` - DDL capture mechanism

**PrintOptim Codebase**:
- `db/0_schema/00_common/` - Shared schema, security, functions
- `db/0_schema/01_write_side/` - Write-side tables (sample files)
- `db/0_schema/02_query_side/` - Read-side tables (sample files)

### Useful Queries for Review

**Check PrintOptim for tenant_id compliance**:
```sql
SELECT table_name
FROM information_schema.tables
WHERE table_schema IN ('01_write_side', '02_query_side')
  AND table_name NOT LIKE '_*'
  AND table_name NOT LIKE 'system_%'
  AND NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = information_schema.tables.table_name
      AND column_name = 'tenant_id'
  );
```

**Count tables in PrintOptim schema**:
```sql
SELECT COUNT(*) FROM information_schema.tables
WHERE table_schema IN ('00_common', '01_write_side', '02_query_side', '03_functions');
```

**Identify foreign keys that might benefit from indexing**:
```sql
SELECT tc.table_name, kcu.column_name, tc.constraint_name
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name
WHERE tc.constraint_type = 'FOREIGN KEY'
  AND NOT EXISTS (
    SELECT 1 FROM pg_stat_user_indexes
    WHERE schemaname = kcu.table_schema
      AND tablename = kcu.table_name
      AND indexdef LIKE '%' || kcu.column_name || '%'
  );
```

---

## Notes for Reviewers

1. **Purpose of This Document**: This is a structured guide to help you systematically evaluate Phase 4 strategy against your expertise and knowledge of the existing systems.

2. **Completeness**: You don't need to answer every question. Focus on areas where you have expertise or concerns.

3. **Honesty**: If something seems wrong or oversimplified, say so. This document is meant to catch issues before implementation.

4. **Suggestions**: Alternative approaches are valuable. If you have a better way to implement a feature, please propose it.

5. **Timeline**: Your review will inform implementation priorities. What should be done first?

6. **Communication**: After completing review, discuss findings with team before implementation begins.

Thank you for taking time to review this long-term strategy! Your expertise is critical for success.

---

**Document Version**: 1.0
**Created**: 2025-12-26
**Status**: Ready for Specialist Review
