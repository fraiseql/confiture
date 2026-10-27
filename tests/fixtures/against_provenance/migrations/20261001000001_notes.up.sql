CREATE TABLE IF NOT EXISTS tb_note (id int, title text);
CREATE INDEX ix_note_title ON tb_note (title);
