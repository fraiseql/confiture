CREATE TABLE tenant.tb_thing (id INT PRIMARY KEY, name TEXT);
COMMENT ON TABLE tenant.tb_thing IS 'qualified';
CREATE INDEX idx_thing_name ON tenant.tb_thing (name);
