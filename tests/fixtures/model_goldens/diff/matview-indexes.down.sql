-- Migration: golden
-- Version: <version>

-- confiture:tier lock_risky
DROP MATERIALIZED VIEW IF EXISTS mv_order_total;
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_order_total AS SELECT customer, sum(total) AS total FROM tb_order GROUP BY customer;
CREATE UNIQUE INDEX IF NOT EXISTS ux_order_total_customer ON mv_order_total (customer);

-- confiture:tier destructive
DROP MATERIALIZED VIEW IF EXISTS mv_customer;

-- confiture:tier destructive
DROP INDEX CONCURRENTLY IF EXISTS ux_order_count_customer;

-- confiture:tier destructive
DROP INDEX CONCURRENTLY IF EXISTS ix_order_big;

-- confiture:tier additive
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_order_big ON mv_order_big (customer);
