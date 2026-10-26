CREATE TABLE tb_tag (id int, name text);
CREATE UNIQUE INDEX ux_tag_name ON tb_tag (name);
