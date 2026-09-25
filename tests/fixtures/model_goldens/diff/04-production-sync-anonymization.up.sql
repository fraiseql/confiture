-- Migration: golden
-- Version: <version>

-- confiture:tier additive
CREATE TABLE IF NOT EXISTS audit_logs (
    id BIGINT NOT NULL,
    actor_email TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);

-- confiture:tier additive
CREATE TABLE IF NOT EXISTS employees (
    id BIGINT NOT NULL,
    email TEXT NOT NULL,
    full_name TEXT NOT NULL,
    phone TEXT,
    ssn TEXT,
    bank_account_number TEXT,
    department TEXT NOT NULL,
    hired_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);

-- confiture:tier lock_risky
CREATE TABLE IF NOT EXISTS order_items (
    id BIGINT NOT NULL,
    order_id BIGINT NOT NULL,
    product_id BIGINT NOT NULL,
    quantity INTEGER NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY (order_id) REFERENCES orders (id),
    FOREIGN KEY (product_id) REFERENCES products (id),
    CHECK (quantity > 0)
);
CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items (order_id);

-- confiture:tier lock_risky
CREATE TABLE IF NOT EXISTS orders (
    id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    billing_email TEXT,
    customer_notes TEXT,
    total_cents INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'paid',
    placed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY (user_id) REFERENCES users (id),
    CHECK (total_cents >= 0)
);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders (user_id);

-- confiture:tier lock_risky
CREATE TABLE IF NOT EXISTS payments (
    id BIGINT NOT NULL,
    order_id BIGINT NOT NULL,
    cardholder_name TEXT NOT NULL,
    card_last4 TEXT NOT NULL,
    stripe_customer_id TEXT NOT NULL,
    billing_zip TEXT,
    amount_cents INTEGER NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY (order_id) REFERENCES orders (id),
    CHECK (amount_cents >= 0)
);
CREATE INDEX IF NOT EXISTS idx_payments_order ON payments (order_id);

-- confiture:tier additive
CREATE TABLE IF NOT EXISTS products (
    id BIGINT NOT NULL,
    sku TEXT NOT NULL,
    name TEXT NOT NULL,
    price_cents INTEGER NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (sku),
    CHECK (price_cents >= 0)
);

-- confiture:tier lock_risky
CREATE TABLE IF NOT EXISTS support_tickets (
    id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    customer_email TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    opened_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY (user_id) REFERENCES users (id)
);
CREATE INDEX IF NOT EXISTS idx_tickets_user ON support_tickets (user_id);

-- confiture:tier lock_risky
CREATE TABLE IF NOT EXISTS user_sessions (
    id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    ip_address TEXT,
    user_agent TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY (user_id) REFERENCES users (id)
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON user_sessions (user_id);

-- confiture:tier additive
CREATE TABLE IF NOT EXISTS users (
    id BIGINT NOT NULL,
    email TEXT NOT NULL,
    full_name TEXT NOT NULL,
    phone TEXT,
    ssn TEXT,
    country_code TEXT NOT NULL DEFAULT 'US',
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);
