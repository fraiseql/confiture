-- Migration: golden
-- Version: <version>

-- confiture:creates tb_order
-- confiture:tier additive
CREATE TABLE tb_order (
    id BIGINT NOT NULL,
    customer TEXT NOT NULL,
    total NUMERIC NOT NULL,
    PRIMARY KEY (id)
);

-- confiture:creates mv_customer
-- confiture:tier lock_risky
CREATE MATERIALIZED VIEW mv_customer AS SELECT DISTINCT customer FROM tb_order;
CREATE UNIQUE INDEX IF NOT EXISTS ux_customer ON mv_customer (customer);

-- confiture:creates mv_order_big
-- confiture:tier lock_risky
CREATE MATERIALIZED VIEW mv_order_big AS SELECT id, customer, total FROM tb_order WHERE total > 100;
CREATE INDEX IF NOT EXISTS ix_order_big ON mv_order_big (customer, total);

-- confiture:creates mv_order_count
-- confiture:tier lock_risky
CREATE MATERIALIZED VIEW mv_order_count AS SELECT customer, count(*) AS n FROM tb_order GROUP BY customer;
CREATE UNIQUE INDEX IF NOT EXISTS ux_order_count_customer ON mv_order_count (customer);

-- confiture:creates mv_order_total
-- confiture:tier lock_risky
CREATE MATERIALIZED VIEW mv_order_total AS SELECT customer, sum(total) AS total, max(total) AS largest FROM tb_order GROUP BY customer;
CREATE UNIQUE INDEX IF NOT EXISTS ux_order_total_customer ON mv_order_total (customer);
