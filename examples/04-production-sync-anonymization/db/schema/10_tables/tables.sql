-- The e-commerce schema, shared by production and staging.
--
-- `confiture sync` copies *data*, never DDL: the target must already have the
-- tables. Both environments therefore build from this same directory, and a
-- staging refresh is "build once, sync often".
--
-- Columns are grouped by what the anonymization config has to say about them,
-- because that is the decision this example is about: every column here is
-- either PII to be masked, a key that must survive masking, or neither.

-- =============================================================================
-- Customers
-- =============================================================================

CREATE TABLE IF NOT EXISTS users (
    id              BIGINT PRIMARY KEY,
    -- PII
    email           TEXT NOT NULL,
    full_name       TEXT NOT NULL,
    phone           TEXT,
    ssn             TEXT,
    -- Not PII: shape and volume analytics depend on these
    country_code    TEXT NOT NULL DEFAULT 'US',
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON COLUMN users.email IS 'PII - anonymized on sync (email strategy)';
COMMENT ON COLUMN users.ssn IS 'PII - redacted on sync; never leaves production intact';

-- =============================================================================
-- Internal staff — a separate seed, so staff pseudonyms cannot be correlated
-- with customer pseudonyms even though both are keyed by the same secret.
-- =============================================================================

CREATE TABLE IF NOT EXISTS employees (
    id                  BIGINT PRIMARY KEY,
    email               TEXT NOT NULL,
    full_name           TEXT NOT NULL,
    phone               TEXT,
    ssn                 TEXT,
    bank_account_number TEXT,
    department          TEXT NOT NULL,
    hired_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- Commerce
-- =============================================================================

CREATE TABLE IF NOT EXISTS products (
    id          BIGINT PRIMARY KEY,
    sku         TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    price_cents INTEGER NOT NULL CHECK (price_cents >= 0)
);

CREATE TABLE IF NOT EXISTS orders (
    id              BIGINT PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(id),
    -- PII
    billing_email   TEXT,
    customer_notes  TEXT,
    -- Not PII
    total_cents     INTEGER NOT NULL CHECK (total_cents >= 0),
    status          TEXT NOT NULL DEFAULT 'paid',
    placed_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS order_items (
    id         BIGINT PRIMARY KEY,
    order_id   BIGINT NOT NULL REFERENCES orders(id),
    product_id BIGINT NOT NULL REFERENCES products(id),
    quantity   INTEGER NOT NULL CHECK (quantity > 0)
);

CREATE TABLE IF NOT EXISTS payments (
    id                 BIGINT PRIMARY KEY,
    order_id           BIGINT NOT NULL REFERENCES orders(id),
    -- PII
    cardholder_name    TEXT NOT NULL,
    card_last4         TEXT NOT NULL,
    stripe_customer_id TEXT NOT NULL,
    -- Not PII: fraud rules are tested against real geography
    billing_zip        TEXT,
    amount_cents       INTEGER NOT NULL CHECK (amount_cents >= 0)
);

-- =============================================================================
-- Operational
-- =============================================================================

CREATE TABLE IF NOT EXISTS user_sessions (
    id         BIGINT PRIMARY KEY,
    user_id    BIGINT NOT NULL REFERENCES users(id),
    ip_address TEXT,
    user_agent TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS support_tickets (
    id             BIGINT PRIMARY KEY,
    user_id        BIGINT NOT NULL REFERENCES users(id),
    customer_email TEXT NOT NULL,
    subject        TEXT NOT NULL,
    body           TEXT NOT NULL,
    opened_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Never synced at all — see `--exclude` in run.sh. Some data should not leave
-- production even masked, because the masking is the only thing standing
-- between staging access and a security record.
CREATE TABLE IF NOT EXISTS audit_logs (
    id         BIGINT PRIMARY KEY,
    actor_email TEXT NOT NULL,
    action     TEXT NOT NULL,
    detail     TEXT,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE audit_logs IS 'Excluded from sync entirely - never copied to staging';

-- =============================================================================
-- Indexes
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);
CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_payments_order ON payments(order_id);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON user_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_tickets_user ON support_tickets(user_id);
