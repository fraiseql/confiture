-- Migration: golden
-- Version: <version>

-- confiture:tier destructive
DROP MATERIALIZED VIEW IF EXISTS mv_order_total;

-- confiture:tier destructive
DROP MATERIALIZED VIEW IF EXISTS mv_order_count;

-- confiture:tier destructive
DROP MATERIALIZED VIEW IF EXISTS mv_order_big;

-- confiture:tier destructive
DROP MATERIALIZED VIEW IF EXISTS mv_customer;

-- confiture:tier irreversible
DROP TABLE tb_order;
