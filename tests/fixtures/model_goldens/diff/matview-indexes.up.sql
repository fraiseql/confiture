-- Migration: golden
-- Version: <version>

-- confiture:destructive
-- confiture:tier destructive
DROP INDEX CONCURRENTLY IF EXISTS ix_order_big;

-- confiture:tier additive
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_order_big ON mv_order_big (customer, total);

-- confiture:tier additive
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS ux_order_count_customer ON mv_order_count (customer);

-- confiture:tier lock_risky
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_customer AS SELECT DISTINCT customer FROM tb_order;
CREATE UNIQUE INDEX IF NOT EXISTS ux_customer ON mv_customer (customer);

-- confiture:tier destructive
DROP MATERIALIZED VIEW IF EXISTS mv_order_total;
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_order_total AS SELECT customer, sum(total) AS total, max(total) AS largest FROM tb_order GROUP BY customer;
CREATE UNIQUE INDEX IF NOT EXISTS ux_order_total_customer ON mv_order_total (customer);
