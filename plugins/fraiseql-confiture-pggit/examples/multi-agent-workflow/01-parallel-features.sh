#!/bin/bash
# Example 1: Simple Parallel Development (No Conflicts)
#
# Scenario: Two agents working on completely independent tables
# Expected outcome: No conflicts, both can proceed

set -e

echo "=================================================="
echo "Example 1: Parallel Development (No Conflicts)"
echo "=================================================="
echo ""

# Agent A: Adding user authentication features
echo "🤖 Agent A (Authentication): Registering intention..."
confiture coordinate register \
    --agent-id claude-auth \
    --feature-name oauth2_provider \
    --schema-changes "ALTER TABLE users ADD COLUMN oauth_provider TEXT; ALTER TABLE users ADD COLUMN oauth_user_id TEXT; CREATE INDEX idx_users_oauth ON users(oauth_provider, oauth_user_id)" \
    --tables-affected users \
    --risk-level medium \
    --estimated-hours 4

echo ""
echo "✅ Agent A registered successfully"
echo ""

# Agent B: Adding payment tracking
echo "🤖 Agent B (Payments): Registering intention..."
confiture coordinate register \
    --agent-id claude-payments \
    --feature-name payment_tracking \
    --schema-changes "CREATE TABLE payments (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), user_id UUID REFERENCES users(id), amount DECIMAL(10,2), status TEXT, created_at TIMESTAMPTZ DEFAULT NOW()); CREATE INDEX idx_payments_user ON payments(user_id); CREATE INDEX idx_payments_status ON payments(status)" \
    --tables-affected payments \
    --risk-level low \
    --estimated-hours 3

echo ""
echo "✅ Agent B registered successfully"
echo ""

# List all intentions
echo "📋 Current intentions:"
confiture coordinate list-intents

echo ""
echo "🎉 Result: No conflicts! Both agents can work in parallel."
echo ""
echo "Both agents are working on different tables:"
echo "  - Agent A: users table (authentication)"
echo "  - Agent B: payments table (new table)"
echo ""
echo "Next steps for each agent:"
echo "  1. Implement their schema changes"
echo "  2. Mark as in_progress"
echo "  3. Test thoroughly"
echo "  4. Mark as completed"
echo "  5. Merge to main"
