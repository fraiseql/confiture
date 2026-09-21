-- Migration: golden
-- Version: <version>

-- confiture:tier irreversible
DROP TABLE users;

-- confiture:tier irreversible
DROP TABLE user_sessions;

-- confiture:tier irreversible
DROP TABLE support_tickets;

-- confiture:tier irreversible
DROP TABLE products;

-- confiture:tier irreversible
DROP TABLE payments;

-- confiture:tier irreversible
DROP TABLE orders;

-- confiture:tier irreversible
DROP TABLE order_items;

-- confiture:tier irreversible
DROP TABLE employees;

-- confiture:tier irreversible
DROP TABLE audit_logs;
