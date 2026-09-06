CREATE TABLE tb_events (id INT PRIMARY KEY, at TIMESTAMPTZ);
COMMENT ON TABLE tb_events IS 'events';
CREATE INDEX ON tb_events (at);
