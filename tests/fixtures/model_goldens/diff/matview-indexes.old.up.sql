-- Migration: golden
-- Version: <version>

-- confiture:tier additive
CREATE TABLE IF NOT EXISTS tb_order (
    id BIGINT NOT NULL,
    customer TEXT NOT NULL,
    total NUMERIC NOT NULL,
    PRIMARY KEY (id)
);

-- confiture:tier lock_risky
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_order_big AS SELECT id, customer, total FROM tb_order WHERE total > 100;
CREATE INDEX IF NOT EXISTS ix_order_big ON mv_order_big (customer);

-- confiture:tier additive
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_order_count AS SELECT customer, count(*) AS n FROM tb_order GROUP BY customer;

-- confiture:tier lock_risky
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_order_total AS SELECT customer, sum(total) AS total FROM tb_order GROUP BY customer;
CREATE UNIQUE INDEX IF NOT EXISTS ux_order_total_customer ON mv_order_total (customer);
