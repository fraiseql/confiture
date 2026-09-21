#!/bin/bash
# Example 2: Conflicting Changes on Same Table
#
# Scenario: Two agents both need to modify the users table
# Expected outcome: Conflict detected, agents coordinate

set -e

echo "=================================================="
echo "Example 2: Conflicting Tables (Coordination Required)"
echo "=================================================="
echo ""

# Agent A: Adding user preferences
echo "🤖 Agent A (User Experience): Registering intention..."
INTENT_A_OUTPUT=$(confiture coordinate register \
    --agent-id claude-ux \
    --feature-name user_preferences \
    --schema-changes "ALTER TABLE users ADD COLUMN preferences JSONB DEFAULT '{}'; CREATE INDEX idx_users_preferences ON users USING GIN(preferences)" \
    --tables-affected users \
    --risk-level low \
    --estimated-hours 2)

echo "$INTENT_A_OUTPUT"
echo ""
echo "✅ Agent A registered successfully"
echo ""

# Extract intent ID (simple grep - production should parse properly)
INTENT_A_ID=$(echo "$INTENT_A_OUTPUT" | grep "Intent ID" | awk '{print $3}')

# Agent B: Adding user profile data
echo "🤖 Agent B (Social): Registering intention..."
INTENT_B_OUTPUT=$(confiture coordinate register \
    --agent-id claude-social \
    --feature-name user_profiles \
    --schema-changes "ALTER TABLE users ADD COLUMN bio TEXT; ALTER TABLE users ADD COLUMN avatar_url TEXT; ALTER TABLE users ADD COLUMN display_name TEXT" \
    --tables-affected users \
    --risk-level low \
    --estimated-hours 3)

echo "$INTENT_B_OUTPUT"
echo ""

if echo "$INTENT_B_OUTPUT" | grep -q "conflict"; then
    echo "⚠️  Conflict detected! (Expected)"
else
    echo "ℹ️  No conflict detected (or conflict detection needs review)"
fi

echo ""
echo "📋 Current intentions:"
confiture coordinate list-intents

echo ""
echo "🤝 Coordination Process:"
echo ""
echo "1. Both agents are notified of the conflict"
echo "2. Agents review the conflict:"
echo "   - Agent A: preferences (JSONB column + GIN index)"
echo "   - Agent B: bio, avatar_url, display_name (text columns)"
echo ""
echo "3. Agents assess:"
echo "   - Column names: No overlap ✓"
echo "   - Data types: Compatible ✓"
echo "   - Indexes: No conflicts ✓"
echo ""
echo "4. Decision: Low risk, can proceed in parallel"
echo ""
echo "5. Document resolution:"
echo "   confiture coordinate conflicts  # Get conflict ID"
echo "   confiture coordinate resolve \\"
echo "       --conflict-id <ID> \\"
echo "       --notes 'Reviewed: No column name conflicts. Both can proceed.'"
echo ""
echo "6. Both agents continue with confidence"
echo ""
echo "🎯 Key Takeaway:"
echo "Table conflicts don't always mean incompatibility."
echo "Coordination ensures agents review and make informed decisions."
