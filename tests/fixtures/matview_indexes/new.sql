-- A materialized view's indexes, compared as a table's are (#690): the pair's
-- diff adds a matview with its indexes, redefines one that carries its indexes
-- through the recreate, adds an index to one, and rebuilds one whose keys change.
CREATE TABLE tb_order (
    id BIGINT PRIMARY KEY,
    customer TEXT NOT NULL,
    total NUMERIC NOT NULL
);

CREATE MATERIALIZED VIEW mv_order_total AS
    SELECT customer, sum(total) AS total, max(total) AS largest
    FROM tb_order GROUP BY customer;

CREATE UNIQUE INDEX ux_order_total_customer ON mv_order_total (customer);

CREATE MATERIALIZED VIEW mv_order_count AS
    SELECT customer, count(*) AS n FROM tb_order GROUP BY customer;

CREATE UNIQUE INDEX ux_order_count_customer ON mv_order_count (customer);

CREATE MATERIALIZED VIEW mv_order_big AS
    SELECT id, customer, total FROM tb_order WHERE total > 100;

CREATE INDEX ix_order_big ON mv_order_big (customer, total);

CREATE MATERIALIZED VIEW mv_customer AS
    SELECT DISTINCT customer FROM tb_order;

CREATE UNIQUE INDEX ux_customer ON mv_customer (customer);
