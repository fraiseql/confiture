-- Migration: golden
-- Version: <version>

-- confiture:tier irreversible
DROP TABLE tb_confiture;

-- confiture:tier destructive
DROP EXTENSION IF EXISTS "uuid-ossp";
