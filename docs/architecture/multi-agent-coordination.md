# Multi-Agent Coordination Architecture

**System**: Confiture Multi-Agent Coordination
**Version**: 0.3.7
**Status**: Production-Ready
**Last Updated**: January 2026

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Architecture Principles](#architecture-principles)
3. [Component Architecture](#component-architecture)
4. [Database Schema Design](#database-schema-design)
5. [Conflict Detection Algorithm](#conflict-detection-algorithm)
6. [CLI Integration](#cli-integration)
7. [Data Flow & Interactions](#data-flow--interactions)
8. [Performance Characteristics](#performance-characteristics)
9. [Security Considerations](#security-considerations)
10. [Extension Points](#extension-points)
11. [Design Decisions & Trade-offs](#design-decisions--trade-offs)

---

## 1. System Overview

### 1.1 Purpose

The Multi-Agent Coordination system enables multiple agents (AI or human developers) to work in parallel on database schema changes with automatic conflict detection and resolution workflows.

### 1.2 Core Capabilities

- **Intent Declaration**: Agents declare schema changes before implementation
- **Automatic Conflict Detection**: Analyzes DDL for conflicting operations
- **Coordination Workflows**: Guides agents through conflict resolution
- **Audit Trail**: Complete history of all coordination decisions
- **CLI Integration**: User-friendly command-line interface
- **Production-Ready**: Tested, documented, and performant

### 1.3 Design Philosophy

```
┌─────────────────────────────────────────────┐
│       DECLARE FIRST, CODE SECOND            │
│                                             │
│  Intent Registration → Conflict Detection  │
│         ↓                     ↓            │
│    Branch Allocation    Coordination       │
│         ↓                     ↓            │
│    Implementation         Resolution       │
│         ↓                     ↓            │
│    Completion             Audit Trail      │
└─────────────────────────────────────────────┘
```

**Key Principle**: Detect conflicts **before** coding begins, not during merge.

---

## 2. Architecture Principles

### 2.1 Core Principles

1. **Database-First**: All state persisted in PostgreSQL (ACID guarantees)
2. **Fail-Fast**: Detect conflicts at registration time
3. **Audit Everything**: Complete history of all status transitions
4. **Minimal Coupling**: Loosely coupled components with clear boundaries
5. **CLI-Centric**: Human-readable CLI for all operations
6. **Test-Driven**: Comprehensive test coverage (97 tests, 100% pass rate)

### 2.2 Non-Goals

- ❌ Automatic conflict resolution (requires human judgment)
- ❌ pgGit branch management (separate concern)
- ❌ Migration generation (separate feature)
- ❌ Production migration execution (Confiture core handles this)

### 2.3 Scope Boundaries

```
┌─────────────────────────────────────────────────────────┐
│           Multi-Agent Coordination Scope                │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ✅ IN SCOPE                    ❌ OUT OF SCOPE        │
│  ─────────────                  ─────────────          │
│  • Intent registration          • pgGit branching      │
│  • Conflict detection           • Migration generation │
│  • Status tracking              • Production execution │
│  • Coordination workflow        • Code review          │
│  • Audit trail                  • Testing frameworks   │
│  • CLI interface                • CI/CD integration    │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## 3. Component Architecture

### 3.1 System Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    MULTI-AGENT COORDINATION                  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │                    CLI Layer                         │  │
│  │  (python/confiture/cli/coordinate.py)                │  │
│  │                                                       │  │
│  │  Commands:                                            │  │
│  │  • coordinate register                                │  │
│  │  • coordinate list-intents                            │  │
│  │  • coordinate check                                   │  │
│  │  • coordinate status                                  │  │
│  │  • coordinate conflicts                               │  │
│  │  • coordinate resolve                                 │  │
│  │  • coordinate abandon                                 │  │
│  └────────────────────┬─────────────────────────────────┘  │
│                       │                                     │
│                       ▼                                     │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              Coordination Core                       │  │
│  │  (python/confiture/integrations/pggit/coordination/) │  │
│  │                                                       │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌────────────┐ │  │
│  │  │   Models     │  │   Detector   │  │  Registry  │ │  │
│  │  │              │  │              │  │            │ │  │
│  │  │ Intent       │  │ Conflict     │  │ register() │ │  │
│  │  │ ConflictRpt  │  │ Detection    │  │ list()     │ │  │
│  │  │ Status Enum  │  │ Suggestions  │  │ mark_*()   │ │  │
│  │  │ Severity     │  │              │  │ conflicts()│ │  │
│  │  └──────────────┘  └──────────────┘  └────────────┘ │  │
│  │         │                  │                 │       │  │
│  └─────────┼──────────────────┼─────────────────┼───────┘  │
│            │                  │                 │          │
│            └──────────────────┴─────────────────┘          │
│                               │                            │
│                               ▼                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              Database Layer (PostgreSQL)             │  │
│  │                                                       │  │
│  │  Tables:                                              │  │
│  │  • tb_pggit_intent         (main registry)           │  │
│  │  • tb_pggit_conflict       (conflict tracking)       │  │
│  │  • tb_pggit_intent_history (audit trail)             │  │
│  │                                                       │  │
│  │  Indexes: 6 optimized indexes for fast queries       │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Component Responsibilities

#### 3.2.1 Models Layer (`models.py`)

**Purpose**: Define data structures and enums

**Components**:
- `Intent` - Agent's declared schema changes
- `ConflictReport` - Detected conflict details
- `IntentStatus` - Lifecycle states (REGISTERED → IN_PROGRESS → COMPLETED → MERGED)
- `ConflictType` - Conflict categories (TABLE, COLUMN, FUNCTION, etc.)
- `ConflictSeverity` - WARNING vs ERROR
- `RiskLevel` - LOW, MEDIUM, HIGH assessment

**Design Pattern**: Immutable dataclasses with serialization support

**Key Methods**:
- `to_dict()` - JSON serialization
- `from_dict()` - Deserialization from database

#### 3.2.2 Detector Layer (`detector.py`)

**Purpose**: Analyze schema changes for conflicts

**Algorithm**: Regex-based DDL parsing + set operations

**Conflict Types Detected**:
1. **TABLE**: Both agents modify same table (WARNING)
2. **COLUMN**: Both agents modify same column (ERROR)
3. **FUNCTION**: Both agents redefine same function (ERROR)
4. **INDEX**: Both agents create/modify same index (WARNING)
5. **CONSTRAINT**: Both agents modify constraints (WARNING)
6. **TIMING**: Temporal/naming conflicts (WARNING)

**Key Methods**:
- `detect_conflicts(intent_a, intent_b)` - Main entry point
- `_detect_table_conflicts()` - Table-level analysis
- `_detect_column_conflicts()` - Column-level analysis
- `_detect_function_conflicts()` - Function-level analysis
- `_generate_suggestions()` - Resolution advice

**Performance**: O(n*m) where n=agents, m=changes per agent (fast for typical cases)

#### 3.2.3 Registry Layer (`registry.py`)

**Purpose**: Orchestrate coordination workflow

**Responsibilities**:
- Intent registration with auto-conflict detection
- Branch name allocation (unique per intent)
- Status lifecycle management
- Conflict storage and retrieval
- Audit trail maintenance

**Key Methods**:
- `register()` - Register new intent + detect conflicts
- `get_intent()` - Retrieve intent by ID
- `list_intents()` - Query with filters (status, agent)
- `mark_in_progress()` - Update status → IN_PROGRESS
- `mark_completed()` - Update status → COMPLETED
- `mark_merged()` - Update status → MERGED
- `mark_abandoned()` - Update status → ABANDONED
- `get_conflicts()` - Get all conflicts for an intent
- `resolve_conflict()` - Mark conflict as reviewed

**Transaction Safety**: All database operations wrapped in transactions

#### 3.2.4 CLI Layer (`coordinate.py`)

**Purpose**: User-friendly command-line interface

**Design Pattern**: Typer-based CLI with Rich formatting

**Commands**:
- `register` - Declare new intention
- `list-intents` - View all intentions (with filters)
- `check` - Pre-flight conflict check
- `status` - Detailed intent status
- `conflicts` - List all conflicts
- `resolve` - Mark conflict resolved
- `abandon` - Abandon an intention

**Output**: Rich-formatted tables, colored text, clear error messages

---

## 4. Database Schema Design

### 4.1 Schema Overview

The database schema follows the **Trinity Pattern** (used throughout Confiture):
- `tb_` prefix for tables
- `idx_` prefix for indexes
- Consistent naming conventions

### 4.2 Table: `tb_pggit_intent`

**Purpose**: Main registry of agent intentions

```sql
CREATE TABLE tb_pggit_intent (
    -- Identity
    id VARCHAR(64) PRIMARY KEY,                  -- UUID for tracking
    agent_id VARCHAR(255) NOT NULL,              -- Agent identifier
    feature_name VARCHAR(255) NOT NULL,          -- Human-readable name
    branch_name VARCHAR(255) NOT NULL UNIQUE,    -- Allocated branch

    -- Schema Changes
    schema_changes JSONB NOT NULL DEFAULT '[]',  -- DDL statements
    tables_affected JSONB NOT NULL DEFAULT '[]', -- Table names

    -- Metadata
    estimated_duration_ms INTEGER,               -- Time estimate
    risk_level VARCHAR(50) DEFAULT 'low',        -- LOW, MEDIUM, HIGH
    status VARCHAR(50) NOT NULL DEFAULT 'registered',  -- Lifecycle status
    conflicts_with JSONB NOT NULL DEFAULT '[]',  -- Conflicting intent IDs
    metadata JSONB NOT NULL DEFAULT '{}',        -- Custom data

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for fast queries
CREATE INDEX idx_pggit_intent_agent ON tb_pggit_intent(agent_id);
CREATE INDEX idx_pggit_intent_status ON tb_pggit_intent(status);
CREATE INDEX idx_pggit_intent_tables ON tb_pggit_intent USING GIN(tables_affected);
```

**Design Rationale**:
- **JSONB for arrays**: Flexible schema, efficient querying with GIN indexes
- **Unique branch_name**: Prevents allocation conflicts
- **No foreign keys to agents**: Agents may be external (AI models, humans)
- **Timestamptz**: Full timezone support for distributed teams

### 4.3 Table: `tb_pggit_conflict`

**Purpose**: Track detected conflicts between intentions

```sql
CREATE TABLE tb_pggit_conflict (
    id SERIAL PRIMARY KEY,
    intent_a VARCHAR(64) NOT NULL REFERENCES tb_pggit_intent(id) ON DELETE CASCADE,
    intent_b VARCHAR(64) NOT NULL REFERENCES tb_pggit_intent(id) ON DELETE CASCADE,
    conflict_type VARCHAR(50) NOT NULL,          -- TABLE, COLUMN, etc.
    affected_objects JSONB NOT NULL DEFAULT '[]', -- Specific objects
    severity VARCHAR(50) NOT NULL,                -- WARNING, ERROR
    resolution_suggestions JSONB NOT NULL DEFAULT '[]',  -- Advice
    reviewed BOOLEAN DEFAULT FALSE,               -- Has been reviewed?
    reviewed_at TIMESTAMPTZ,                      -- When reviewed
    resolution_notes TEXT,                        -- Resolution details
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_pggit_conflict_intents ON tb_pggit_conflict(intent_a, intent_b);
CREATE INDEX idx_pggit_conflict_severity ON tb_pggit_conflict(severity);
```

**Design Rationale**:
- **Bidirectional references**: intent_a ↔ intent_b
- **CASCADE delete**: Clean up conflicts when intent abandoned
- **JSONB suggestions**: Flexible advice storage
- **reviewed flag**: Track resolution status

### 4.4 Table: `tb_pggit_intent_history`

**Purpose**: Audit trail of all status changes

```sql
CREATE TABLE tb_pggit_intent_history (
    id SERIAL PRIMARY KEY,
    intent_id VARCHAR(64) NOT NULL REFERENCES tb_pggit_intent(id) ON DELETE CASCADE,
    old_status VARCHAR(50),                      -- Previous status
    new_status VARCHAR(50) NOT NULL,             -- New status
    reason TEXT,                                 -- Why changed
    changed_by VARCHAR(255) DEFAULT 'system',    -- Who changed it
    changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for fast history lookup
CREATE INDEX idx_pggit_intent_history_id ON tb_pggit_intent_history(intent_id);
```

**Design Rationale**:
- **Append-only**: Never delete history (audit requirement)
- **Who/When/Why**: Full provenance tracking
- **CASCADE delete**: Clean up history when intent deleted

### 4.5 Index Strategy

| Index | Type | Purpose | Selectivity |
|-------|------|---------|-------------|
| `idx_pggit_intent_agent` | B-tree | Filter by agent | High |
| `idx_pggit_intent_status` | B-tree | Filter by status | Medium |
| `idx_pggit_intent_tables` | GIN | Search by affected tables | High |
| `idx_pggit_conflict_intents` | B-tree | Find conflicts for intent pair | High |
| `idx_pggit_conflict_severity` | B-tree | Filter by severity | Low |
| `idx_pggit_intent_history_id` | B-tree | Get history for intent | High |

**Performance**: All queries use indexes, < 10ms typical response time

---

## 5. Conflict Detection Algorithm

### 5.1 High-Level Algorithm

```
┌─────────────────────────────────────────────────────────┐
│          CONFLICT DETECTION ALGORITHM                    │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  Input: Intent A, Intent B                              │
│                                                         │
│  Step 1: Agent Check                                    │
│    IF intent_a.agent_id == intent_b.agent_id THEN      │
│      RETURN [] (same agent, no conflict)              │
│                                                         │
│  Step 2: Table-Level Analysis                           │
│    tables_a = extract_tables(intent_a.schema_changes)  │
│    tables_b = extract_tables(intent_b.schema_changes)  │
│    overlapping_tables = tables_a ∩ tables_b            │
│    IF overlapping_tables ≠ ∅ THEN                      │
│      CREATE ConflictReport(type=TABLE, severity=WARNING)│
│                                                         │
│  Step 3: Column-Level Analysis                          │
│    FOR each overlapping table:                          │
│      columns_a = extract_columns(intent_a, table)      │
│      columns_b = extract_columns(intent_b, table)      │
│      IF columns_a ∩ columns_b ≠ ∅ THEN                 │
│        CREATE ConflictReport(type=COLUMN, severity=ERROR)│
│                                                         │
│  Step 4: Function Analysis                              │
│    functions_a = extract_functions(intent_a)           │
│    functions_b = extract_functions(intent_b)           │
│    IF functions_a ∩ functions_b ≠ ∅ THEN               │
│      CREATE ConflictReport(type=FUNCTION, severity=ERROR)│
│                                                         │
│  Step 5: Index Analysis                                 │
│    (Similar to functions)                               │
│                                                         │
│  Step 6: Constraint Analysis                            │
│    (Similar to functions)                               │
│                                                         │
│  Step 7: Generate Suggestions                           │
│    FOR each conflict:                                   │
│      conflict.suggestions = generate_suggestions(conflict)│
│                                                         │
│  RETURN list of ConflictReport objects                  │
└─────────────────────────────────────────────────────────┘
```

### 5.2 DDL Parsing

**Regex Patterns**:
```python
# Table extraction
TABLE_PATTERN = r"(?:CREATE|ALTER|DROP)\s+TABLE\s+(?:IF\s+EXISTS\s+)?(\w+)"

# Column extraction
COLUMN_PATTERN = r"ALTER\s+TABLE\s+(\w+)\s+(?:ADD|DROP)\s+COLUMN\s+(\w+)"

# Function extraction
FUNCTION_PATTERN = r"(?:CREATE|ALTER|DROP)\s+FUNCTION\s+(?:IF\s+EXISTS\s+)?(\w+)"

# Index extraction
INDEX_PATTERN = r"(?:CREATE|DROP)\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+EXISTS\s+)?(\w+)"

# Constraint detection
CONSTRAINT_PATTERN = r"(?:ADD|DROP)\s+(?:PRIMARY\s+KEY|FOREIGN\s+KEY|UNIQUE|CHECK|DEFAULT)"
```

**Limitations**:
- Regex-based (not full SQL parser)
- Case-insensitive matching
- Handles common DDL patterns, not exotic syntax
- Future: Could use full SQL parser (e.g., sqlparse, pg_query)

### 5.3 Conflict Severity Rules

| Conflict Type | Default Severity | Rationale |
|---------------|------------------|-----------|
| TABLE | WARNING | Same table doesn't mean incompatible (could be different columns) |
| COLUMN | ERROR | Same column modification is likely incompatible |
| FUNCTION | ERROR | Cannot both redefine same function |
| INDEX | WARNING | Duplicate indexes are wasteful but not breaking |
| CONSTRAINT | WARNING | May or may not conflict (depends on specifics) |
| TIMING | WARNING | Informational, not technical conflict |

**Override**: Severity can be manually adjusted during resolution

### 5.4 Suggestion Generation

**Algorithm**: Rule-based suggestion system

```python
def generate_suggestions(conflict, intent_a, intent_b):
    suggestions = []

    if conflict.type == ConflictType.TABLE:
        suggestions.append("Coordinate column naming with other agent")
        suggestions.append("Consider sequential application")
        suggestions.append("Review for actual column conflicts")

    elif conflict.type == ConflictType.COLUMN:
        suggestions.append("Choose different column name")
        suggestions.append("Coordinate with other agent to merge changes")
        suggestions.append("One agent adjusts scope")

    elif conflict.type == ConflictType.FUNCTION:
        suggestions.append("Rename one of the functions")
        suggestions.append("Merge function logic if possible")
        suggestions.append("Sequential application with coordination")

    # ... more rules ...

    return suggestions
```

**Extensible**: Custom suggestion generators can be added

---

## 6. CLI Integration

### 6.1 Command Architecture

```
confiture (main CLI app)
  │
  └── coordinate (sub-app)
        │
        ├── register
        ├── list-intents
        ├── check
        ├── status
        ├── conflicts
        ├── resolve
        └── abandon
```

### 6.2 Command Flow Example

**`confiture coordinate register`**:

```
User Input
    ↓
Parse CLI arguments (Typer)
    ↓
Validate required fields
    ↓
Get database connection
    ↓
Create IntentRegistry instance
    ↓
Parse schema changes (from file or string)
    ↓
Parse tables affected
    ↓
Parse metadata (JSON)
    ↓
registry.register(...)
    ↓
Allocate branch name
    ↓
Detect conflicts (automatic)
    ↓
Store intent in database
    ↓
Store conflicts in database
    ↓
Format output (Rich tables)
    ↓
Display to user (colored, formatted)
    ↓
Show conflicts if any (warning message)
    ↓
Close database connection
```

### 6.3 Output Formatting

**Technology**: Rich library (tables, colors, formatting)

**Example Output**:
```
┌─────────────────────────────────────────┐
│ Intention Registered                     │
├─────────────────────────────────────────┤
│ Intent ID:     int_abc123def456          │
│ Agent:         claude-payments           │
│ Feature:       stripe_integration        │
│ Branch:        feature/stripe_int_001    │
│ Status:        REGISTERED                │
│ Risk Level:    medium                    │
│ Tables Affected: users                   │
└─────────────────────────────────────────┘

⚠️  Warning: Found 1 conflict(s) with existing intentions:
  - table: users [warning]
```

---

## 7. Data Flow & Interactions

### 7.1 Complete Registration Flow

```
┌─────────────────────────────────────────────────────────────┐
│                 INTENT REGISTRATION FLOW                     │
└─────────────────────────────────────────────────────────────┘

Agent
  │
  ├─[1]─▶ CLI Command
  │       "confiture coordinate register --agent-id claude-auth ..."
  │
  ▼
CLI Layer (coordinate.py)
  │
  ├─[2]─▶ Parse arguments
  ├─[3]─▶ Get database connection
  ├─[4]─▶ Create IntentRegistry
  │
  ▼
Registry Layer (registry.py)
  │
  ├─[5]─▶ Generate UUID for intent
  ├─[6]─▶ Allocate branch name (feature/<name>_###)
  ├─[7]─▶ Parse tables from DDL (if not provided)
  ├─[8]─▶ Create Intent object
  ├─[9]─▶ Query existing intents (REGISTERED, IN_PROGRESS)
  │
  ▼
Detector Layer (detector.py)
  │
  ├─[10]─▶ FOR each existing intent:
  │          detect_conflicts(new_intent, existing_intent)
  ├─[11]─▶ Extract tables, columns, functions from DDL
  ├─[12]─▶ Compare with existing intent's DDL
  ├─[13]─▶ Create ConflictReport for each conflict
  ├─[14]─▶ Generate resolution suggestions
  │
  ▼
Registry Layer (registry.py)
  │
  ├─[15]─▶ INSERT intent into tb_pggit_intent
  ├─[16]─▶ INSERT conflicts into tb_pggit_conflict
  ├─[17]─▶ INSERT history into tb_pggit_intent_history
  ├─[18]─▶ COMMIT transaction
  │
  ▼
CLI Layer (coordinate.py)
  │
  ├─[19]─▶ Format output (Rich tables)
  ├─[20]─▶ Display intent details
  ├─[21]─▶ Display conflicts (if any)
  │
  ▼
Agent
```

### 7.2 Status Transition Flow

```
IntentStatus Lifecycle:

  REGISTERED ────────▶ IN_PROGRESS ────────▶ COMPLETED ────────▶ MERGED
      │                     │                     │
      │                     │                     │
      └─────────────────────┴─────────────────────┴──────▶ ABANDONED


                            ▼
                       CONFLICTED
                         (flag)
```

**Transitions**:
- `REGISTERED → IN_PROGRESS`: Agent starts work (`mark_in_progress()`)
- `IN_PROGRESS → COMPLETED`: Agent finishes work (`mark_completed()`)
- `COMPLETED → MERGED`: Merged to main branch (`mark_merged()`)
- `* → ABANDONED`: Agent gives up (`mark_abandoned()`)
- `* → CONFLICTED`: Status flag when conflicts detected

**Audit**: Every transition recorded in `tb_pggit_intent_history`

### 7.3 Conflict Resolution Flow

```
Conflict Detected
      │
      ▼
├─[Option 1]─▶ Sequential Execution
│              - Agent A completes first
│              - Agent B waits
│              - No overlap
│
├─[Option 2]─▶ Scope Adjustment
│              - One agent changes plan
│              - Abandon old intent
│              - Register new intent
│
├─[Option 3]─▶ Risk Acceptance
│              - Review conflict
│              - Determine low risk
│              - Mark as resolved
│              - Proceed with caution
│
└─[Option 4]─▶ Merge Efforts
               - Agents collaborate
               - Combine into single intent
               - Abandon duplicates
```

---

## 8. Performance Characteristics

> **📊 Comprehensive Benchmarks**: See [coordination-performance.md](../performance/coordination-performance.md) for detailed performance analysis with 18 comprehensive benchmark tests.

### 8.1 Performance Summary

**Key Finding**: Performance exceeds all targets by **10-100x**.

| Operation | Actual Performance | Target | Status |
|-----------|-------------------|--------|--------|
| Intent registration | ~1.3ms | <100ms | ✅ **76x faster** |
| Conflict detection | <1ms (even with 100 intents) | <100ms | ✅ **100x faster** |
| Database queries | <1ms (most operations) | <10ms | ✅ **10x faster** |
| CLI response (core ops) | ~1-2ms | <100ms | ✅ **50-100x faster** |

**Test Environment**: PostgreSQL 17.4 on localhost, Python 3.11.14

### 8.2 Scalability

**Actual Benchmark Results**:

| Scale | Total Time | Avg Time/Intent | Scaling |
|-------|------------|-----------------|---------|
| 1 intent | 1.31ms | 1.31ms | Baseline |
| 10 intents | 6.99ms | 0.70ms | Linear |
| 100 intents | 96.49ms | 0.96ms | Linear |
| 1,000 intents | 1.54s | 1.54ms | Linear |

**Scaling Characteristics**:
- ✅ **Linear scaling (O(n))** for intent registration
- ✅ **Constant time (O(1))** for conflict detection
- ✅ **Sub-linear (O(log n))** for list operations (indexed queries)

**Tested Scenarios**:
- ✅ 1,000 concurrent intents (stress test)
- ✅ 100 intents with complex conflicts (benchmark test)
- ✅ Diamond dependencies (3+ agents, E2E test)
- ✅ 61 active intents with conflict detection (scalability summary)

### 8.3 Database Performance

**Actual Query Performance**:

| Query Type | Time | Notes |
|------------|------|-------|
| Intent lookup by ID | 0.09ms | Primary key index scan |
| Filter by status | 0.13ms | Status index scan |
| Filter by agent | 0.18ms | Agent ID index scan |
| List all (50 intents) | 0.37ms | Sequential scan with limit |
| Update status | 0.69ms | Single row update + audit |
| Get conflicts | 0.10ms | Indexed lookup |

**Database Indexes**:
- Primary key on `id` (UUID)
- Index on `agent_id` (for agent filtering)
- Index on `status` (for workflow queries)
- Index on `created_at` (for ordering)

**Query Plans**: All queries use index scans, no sequential scans observed.

**Connection Pooling**: Not required for current performance. Consider only if >100 concurrent CLI users expected.

### 8.4 Bottleneck Analysis

**No Significant Bottlenecks Identified**:
- Database operations: Sub-millisecond, well-indexed
- Conflict detection: In-memory comparisons, <1ms
- DDL parsing: Regex-based, <0.1ms per statement
- Network latency: Localhost testing (minimal)

**Theoretical Limits**:
- Maximum throughput: ~650 intent registrations/second (single connection)
- Maximum concurrent agents: Limited by PostgreSQL connections (default: 100)
- Maximum active intents: >10,000 with sub-second query times

**Real-world usage**: 10-50 concurrent agents, 100-500 active intents → **negligible performance impact**

### 8.5 Production Recommendations

**Current Status**: ✅ **Production-ready without optimization**

1. **No immediate optimizations needed** - performance exceeds targets by 10-100x
2. **Monitor with PostgreSQL slow query log** (threshold: 50ms) to catch regressions
3. **Consider connection pooling** only if >100 concurrent CLI users
4. **Add metrics** to track p50, p95, p99 latency in production

**Future Optimization** (low priority, unlikely to be needed):
- Rust extension for DDL parsing (0.1ms → 0.01ms)
- Read replicas for high-read scenarios
- Caching layer (Redis) for frequently accessed intents
- Batch APIs for bulk operations

### 8.6 Benchmark Test Suite

**Location**: `tests/performance/test_coordination_benchmarks.py`

**Coverage**: 18 comprehensive benchmarks
- 4 tests: Intent registration (1, 10, 100, 1,000 intents)
- 3 tests: Conflict detection (simple, moderate, complex)
- 6 tests: Database queries (list, filter, get, update)
- 4 tests: CLI operations (register, list, status, check)
- 1 test: Scalability summary

**Execution Time**: 2.13 seconds (all 18 tests)

**Run Benchmarks**:
```bash
uv run pytest tests/performance/test_coordination_benchmarks.py -v -s
```

---

## 9. Security Considerations

### 9.1 SQL Injection Protection

**Strategy**: psycopg3 parameterized queries throughout

```python
# Good: Parameterized query (used everywhere in codebase)
cursor.execute(
    "SELECT * FROM tb_pggit_intent WHERE id = %s",
    (intent_id,)
)

# Bad: String interpolation (NEVER used)
cursor.execute(f"SELECT * FROM tb_pggit_intent WHERE id = '{intent_id}'")
```

**Validation**: All user input validated before database operations

### 9.2 Authentication & Authorization

**Current State**: No authentication layer (coordination system is database-backed)

**Recommended Integration**:
- Application-level auth (OAuth, JWT)
- Database-level auth (PostgreSQL roles)
- Row-level security (RLS) for multi-tenant scenarios

**Example RLS Policy**:
```sql
-- Enable RLS on intents table
ALTER TABLE tb_pggit_intent ENABLE ROW LEVEL SECURITY;

-- Policy: Users can only see their own intents
CREATE POLICY intent_isolation ON tb_pggit_intent
    USING (agent_id = current_user);
```

### 9.3 Data Privacy

**PII Considerations**:
- `agent_id`: May contain human names (consider hashing)
- `feature_name`: May contain sensitive project info
- `metadata`: May contain arbitrary data (validate)

**Recommendations**:
- Avoid storing PII in `metadata`
- Use pseudonymous agent IDs
- Encrypt database at rest (PostgreSQL feature)

### 9.4 Audit Trail Integrity

**Protection**: Append-only history table

**Best Practice**:
```sql
-- Make history table immutable (PostgreSQL 12+)
CREATE RULE prevent_delete AS
    ON DELETE TO tb_pggit_intent_history DO INSTEAD NOTHING;

CREATE RULE prevent_update AS
    ON UPDATE TO tb_pggit_intent_history DO INSTEAD NOTHING;
```

---

## 10. Extension Points

### 10.1 Custom Conflict Detectors

**Interface**:
```python
class CustomConflictDetector:
    """Example custom detector for domain-specific conflicts."""

    def detect_conflicts(self, intent_a: Intent, intent_b: Intent) -> list[ConflictReport]:
        """Implement custom conflict detection logic."""
        conflicts = []

        # Example: Detect conflicts based on custom metadata
        if intent_a.metadata.get("team") == intent_b.metadata.get("team"):
            # Same team, apply stricter rules
            conflicts.extend(self._check_team_conventions(intent_a, intent_b))

        return conflicts
```

**Integration**:
```python
# Extend IntentRegistry
class CustomRegistry(IntentRegistry):
    def __init__(self, connection):
        super().__init__(connection)
        self._detector = CustomConflictDetector()  # Override detector
```

### 10.2 Custom Suggestion Generators

**Interface**:
```python
def generate_custom_suggestions(conflict: ConflictReport) -> list[str]:
    """Generate domain-specific suggestions."""
    if conflict.metadata.get("org") == "finance":
        return [
            "Coordinate with compliance team",
            "Ensure audit trail is preserved",
        ]
    return []
```

### 10.3 Webhook Notifications

**Example Integration**:
```python
class WebhookRegistry(IntentRegistry):
    def register(self, ...):
        intent = super().register(...)

        # Send webhook notification
        if intent.conflicts_with:
            self._send_webhook({
                "event": "conflict_detected",
                "intent_id": intent.id,
                "conflicts": len(intent.conflicts_with),
            })

        return intent

    def _send_webhook(self, payload):
        import requests
        requests.post(WEBHOOK_URL, json=payload)
```

### 10.4 Custom Status Workflows

**Example**: Add custom statuses
```python
class ExtendedIntentStatus(Enum):
    REGISTERED = "registered"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    MERGED = "merged"
    ABANDONED = "abandoned"
    CONFLICTED = "conflicted"
    # Custom statuses
    PENDING_REVIEW = "pending_review"  # NEW
    APPROVED = "approved"              # NEW
    REJECTED = "rejected"              # NEW
```

---

## 11. Design Decisions & Trade-offs

### 11.1 Key Design Decisions

#### Decision 1: Regex-based DDL Parsing vs Full SQL Parser

**Choice**: Regex-based parsing

**Rationale**:
- ✅ Fast (< 10ms typical)
- ✅ Simple implementation
- ✅ Handles 95% of real-world DDL
- ✅ Easy to extend

**Trade-offs**:
- ❌ Doesn't handle exotic SQL syntax
- ❌ Not 100% accurate for complex DDL
- ❌ Requires manual pattern updates

**Future**: Could migrate to sqlparse or pg_query for 100% accuracy

---

#### Decision 2: Database-backed State vs In-Memory

**Choice**: PostgreSQL-backed state

**Rationale**:
- ✅ ACID guarantees (consistency)
- ✅ Persistent state across restarts
- ✅ Multi-process safe
- ✅ Queryable with SQL
- ✅ Audit trail built-in

**Trade-offs**:
- ❌ Requires database connection
- ❌ Slightly slower than in-memory
- ❌ Requires database setup

**Alternatives Considered**: Redis, SQLite, in-memory dict

---

#### Decision 3: Automatic Conflict Detection vs Manual

**Choice**: Automatic detection on registration

**Rationale**:
- ✅ Fail-fast (detect immediately)
- ✅ Better UX (no extra step)
- ✅ Impossible to forget
- ✅ Consistent behavior

**Trade-offs**:
- ❌ Registration slightly slower
- ❌ False positives possible

**Mitigation**: Severity levels (WARNING vs ERROR) reduce false positive impact

---

#### Decision 4: Branch Allocation Strategy

**Choice**: Automatic counter-based naming (`feature/<name>_001`)

**Rationale**:
- ✅ Unique names guaranteed
- ✅ Deterministic
- ✅ Human-readable
- ✅ Sortable

**Trade-offs**:
- ❌ Doesn't prevent branch name conflicts in git (separate concern)
- ❌ Counter can grow large

**Future**: Could integrate with actual pgGit branch creation

---

#### Decision 5: CLI-First vs API-First

**Choice**: CLI-first with API underneath

**Rationale**:
- ✅ User-friendly for humans
- ✅ Easy to script
- ✅ Dogfooding (ensures API is complete)
- ✅ Better error messages

**Trade-offs**:
- ❌ API slightly more complex (supports CLI)

**Result**: Both CLI and Python API are first-class

---

### 11.2 Alternative Approaches Considered

#### Alternative 1: Event Sourcing

**Approach**: Store all events, derive state

**Rejected Because**:
- Overkill for current requirements
- Adds complexity without clear benefit
- Audit trail already provided by history table

**Future**: Could migrate if event replay needed

---

#### Alternative 2: Graph Database for Conflicts

**Approach**: Use Neo4j or similar for conflict graph

**Rejected Because**:
- Adds dependency (PostgreSQL sufficient)
- Conflict graph is simple (not deeply nested)
- PostgreSQL JSONB handles it fine

**Future**: If conflict graphs become deeply nested (10+ levels)

---

#### Alternative 3: Automatic Conflict Resolution

**Approach**: AI/ML-based conflict resolution

**Rejected Because**:
- Conflicts require human judgment
- False positives dangerous (data loss risk)
- Transparency needed (why was it resolved?)

**Future**: Could add suggestion ranking with ML

---

## Summary

The Multi-Agent Coordination system is designed for:
- ✅ **Simplicity**: Clear component boundaries
- ✅ **Reliability**: Database-backed, ACID guarantees
- ✅ **Performance**: < 100ms typical operations
- ✅ **Extensibility**: Clear extension points
- ✅ **Security**: SQL injection protected, audit trail
- ✅ **Testing**: 97 tests, 100% pass rate

**Production-Ready**: Yes, all acceptance criteria met (97.6% completion)

---

**Related Documentation**:
- [User Guide](../guides/multi-agent-coordination.md)
- [API Reference](../api/)
- [Examples](../../examples/multi-agent-workflow/)

**Version**: 0.3.7
**Last Updated**: January 2026
**Status**: Production-Ready
