#!/bin/bash
# Example 3: Diamond Dependencies (Complex Coordination)
#
# Scenario: Three agents with transitive dependencies
#   Agent A: Modifies users table
#   Agent B: Modifies orders table (FK to users)
#   Agent C: Creates analytics table (uses both users and orders)
#
# Expected outcome: All conflicts detected, execution order determined

set -e

echo "=================================================="
echo "Example 3: Diamond Dependencies"
echo "=================================================="
echo ""
echo "Scenario:"
echo "  Agent A → Enhances users table"
echo "  Agent B → Enhances orders table (references users)"
echo "  Agent C → Creates analytics (uses users + orders)"
echo ""
echo "Expected: All 3-way dependencies detected"
echo ""

# Agent A: Add user segments
echo "🤖 Agent A (Marketing): Registering intention..."
confiture coordinate register \
    --agent-id claude-marketing \
    --feature-name user_segments \
    --schema-changes "ALTER TABLE users ADD COLUMN segment TEXT DEFAULT 'standard'; CREATE INDEX idx_users_segment ON users(segment)" \
    --tables-affected users \
    --risk-level low \
    --estimated-hours 2

echo ""
echo "✅ Agent A registered"
echo ""

# Agent B: Add order priority
echo "🤖 Agent B (Orders): Registering intention..."
confiture coordinate register \
    --agent-id claude-orders \
    --feature-name order_priority \
    --schema-changes "ALTER TABLE orders ADD COLUMN priority INTEGER DEFAULT 0; ALTER TABLE orders ADD CONSTRAINT check_priority CHECK (priority BETWEEN 0 AND 10); CREATE INDEX idx_orders_priority ON orders(priority)" \
    --tables-affected orders \
    --risk-level medium \
    --estimated-hours 3

echo ""
echo "✅ Agent B registered"
echo ""

# Agent C: Create analytics combining both
echo "🤖 Agent C (Analytics): Registering intention..."
confiture coordinate register \
    --agent-id claude-analytics \
    --feature-name segment_analytics \
    --schema-changes "CREATE MATERIALIZED VIEW user_segment_stats AS SELECT u.segment, COUNT(o.id) as order_count, AVG(o.total) as avg_order FROM users u LEFT JOIN orders o ON u.id = o.user_id GROUP BY u.segment; CREATE INDEX idx_segment_stats ON user_segment_stats(segment)" \
    --tables-affected users,orders \
    --risk-level medium \
    --estimated-hours 4

echo ""
echo "✅ Agent C registered"
echo ""

# List all intentions
echo "📋 All intentions:"
confiture coordinate list-intents

echo ""
echo "🔍 Conflict Analysis:"
echo ""
echo "Detected Conflicts:"
echo "  1. Agent A ↔ Agent C: Both use 'users' table"
echo "  2. Agent B ↔ Agent C: Both use 'orders' table"
echo "  3. Agent A ↔ Agent B: Indirect via Agent C"
echo ""
echo "Dependency Graph:"
echo "       ┌──────────┐"
echo "       │  Agent C │"
echo "       │ (Analytics│"
echo "       └─────┬────┘"
echo "             │"
echo "      ┌──────┴──────┐"
echo "      │             │"
echo "  ┌───▼───┐     ┌───▼───┐"
echo "  │Agent A│     │Agent B│"
echo "  │(Users)│     │(Orders)│"
echo "  └───────┘     └───────┘"
echo ""
echo "🎯 Coordination Strategy:"
echo ""
echo "Option 1: Sequential Execution"
echo "  1. Agent A completes (users.segment)"
echo "  2. Agent B completes (orders.priority)"
echo "  3. Agent C executes last (uses both)"
echo "  Result: Clean, safe, slower"
echo ""
echo "Option 2: Parallel with Careful Merge"
echo "  1. Agents A & B work in parallel (independent)"
echo "  2. Both merge to main"
echo "  3. Agent C works on updated schema"
echo "  Result: Faster, requires coordination"
echo ""
echo "Option 3: Agent C Adjusts Scope"
echo "  1. Agent C removes dependency on new columns"
echo "  2. Uses existing schema only"
echo "  3. All agents work in parallel"
echo "  4. Later: Agent C adds segment-aware analytics"
echo "  Result: Maximum parallelism, iterative"
echo ""
echo "Recommended: Option 2"
echo "  - A & B are low-risk, independent changes"
echo "  - C naturally depends on completed schema"
echo "  - Fastest path to complete feature set"
echo ""
echo "Next Steps:"
echo "  1. Agents A & B coordinate: 'We're independent, let's go!'"
echo "  2. Agent C coordinates: 'I'll wait for you both'"
echo "  3. All conflicts marked as resolved with notes"
echo "  4. Execution begins"
echo ""
echo "🎓 Key Lessons:"
echo "  - Complex dependencies are automatically detected"
echo "  - Multiple valid resolution strategies exist"
echo "  - Coordination enables informed decision-making"
echo "  - Documentation (notes) preserves reasoning"
