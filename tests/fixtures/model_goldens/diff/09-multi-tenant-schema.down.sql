-- Migration: golden
-- Version: <version>

-- confiture:irreversible no rollback derived for ADD_STATISTICS app.st_order_line_tenant_order

-- confiture:tier destructive
DROP VIEW IF EXISTS app.v_unit;

-- confiture:tier destructive
DROP VIEW IF EXISTS app.v_order;

-- confiture:tier destructive
DROP FUNCTION IF EXISTS app.fn_create_order(uuid, uuid, text);

-- confiture:tier irreversible
DROP TABLE app.tb_order_line;

-- confiture:tier irreversible
DROP TABLE app.tb_order;

-- confiture:tier irreversible
DROP TABLE app.tb_provider;

-- confiture:tier irreversible
DROP TABLE app.tb_custom_unit;

-- confiture:tier irreversible
DROP TABLE management.tb_organization;

-- confiture:tier irreversible
DROP TABLE catalog.tb_unit;

-- confiture:tier irreversible
DROP TABLE catalog.tb_product;

-- confiture:tier irreversible
DROP TABLE catalog.tb_company;

-- confiture:tier irreversible
DROP SCHEMA IF EXISTS management;

-- confiture:tier irreversible
DROP SCHEMA IF EXISTS catalog;

-- confiture:tier irreversible
DROP SCHEMA IF EXISTS app;
