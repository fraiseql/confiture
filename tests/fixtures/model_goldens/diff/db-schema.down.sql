-- Migration: golden
-- Version: <version>

DROP EXTENSION IF EXISTS uuid-ossp;

-- confiture:tier irreversible
DROP TABLE tb_confiture;
