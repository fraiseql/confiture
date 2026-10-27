ALTER TABLE tb_big RENAME TO tb_old;
DROP TABLE tb_gone;
CREATE TABLE IF NOT EXISTS tb_gone (id int);
CREATE INDEX CONCURRENTLY ix_gone_id ON tb_gone (id);
